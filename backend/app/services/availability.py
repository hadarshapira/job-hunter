"""Find jobs whose posting is gone (closed, filled, deleted) and remove them from the user's list.

Runs on "Find jobs now", and as a small background sweep every 30 minutes (worker.py) so LinkedIn
is asked a few jobs at a time instead of many at once. Only jobs the user hasn't acted on yet are
checked (status new or saved): applications in progress keep their history even when the posting closes.

A job is removed only when the site clearly says it's gone. Anything unclear (timeouts, blocks,
rate limits, server errors, login walls) keeps the job, so a flaky site never empties the list.

LinkedIn often answers "too many requests" (HTTP 429). Each LinkedIn job is asked through the guest
API and, if that's refused, through the public job page (a closed job's page is "Page not found",
HTTP 404, or says "No longer accepting applications"); after a pause it's tried once more. Only
after several jobs in a row stay refused does the run stop asking LinkedIn.
"""

import asyncio
import logging
import random
import re
from datetime import datetime, timezone
from enum import StrEnum
from urllib.parse import urlparse

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Job, Status
from app.services.ats import _ASHBY, _GH, _LEVER
from app.services.importer import USER_AGENT
from app.services.sites.linkedin import GUEST_API, linkedin_job_id

log = logging.getLogger("jobhunter.availability")
CHECK_STATUSES = (Status.new, Status.saved)
MAX_LINKEDIN = 15   # LinkedIn jobs checked on "Find jobs now" (it searches LinkedIn right after)
MAX_OTHER = 150     # other links checked per run
SWEEP_LINKEDIN = 6  # per user in each 30-minute background sweep
SWEEP_OTHER = 30
LINKEDIN_DELAY = (1.0, 2.0)
LIMIT_WAIT = (8.0, 15.0)  # pause after LinkedIn says "too many requests", then try that job once more
MAX_LIMITED = 3           # stop asking LinkedIn after this many jobs in a row stay refused
VIEW_URL = "https://www.linkedin.com/jobs/view/{id}/"
GONE_HTTP = (404, 410)
_LINKEDIN_CLOSED = re.compile(r"no longer accepting applications|this job is no longer available", re.I)


class Verdict(StrEnum):
    open = "open"
    gone = "gone"
    unknown = "unknown"


class LinkedInLimited(Exception):
    pass


def _board_ref(job: Job) -> tuple[str, str, str] | None:
    """(ats, board, job id) for jobs that live on a Greenhouse / Lever / Ashby board."""
    if job.source in ("greenhouse", "lever", "ashby") and job.posting_key and "/" in job.posting_key:
        board, _, job_id = job.posting_key.split(":", 1)[1].rpartition("/")
        if board and job_id:
            return job.source, board, job_id
    u = urlparse(job.url or "")
    host = u.netloc.lower()
    # Only the ATS's own domain: a company site with ?gh_jid= would need the board name guessed
    if host.endswith("greenhouse.io") and (m := _GH.match(u.path)):
        return "greenhouse", m.group(1), m.group(2)
    if host == "jobs.lever.co" and (m := _LEVER.match(u.path)):
        return "lever", m.group(1), m.group(2)
    if host == "jobs.ashbyhq.com" and (m := _ASHBY.match(u.path)):
        return "ashby", m.group(1), m.group(2)
    return None


async def _check_board(client: httpx.AsyncClient, ats: str, board: str, job_id: str) -> Verdict:
    if ats == "greenhouse":
        r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}")
    elif ats == "lever":
        r = await client.get(f"https://api.lever.co/v0/postings/{board}/{job_id}")
    else:  # Ashby has no single-job API: the job is gone when the board no longer lists it
        r = await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{board}")
        if r.status_code != 200:
            return Verdict.unknown
        ids = {j.get("id") for j in r.json().get("jobs", [])}
        return Verdict.open if job_id in ids else Verdict.gone
    if r.status_code in GONE_HTTP:
        return Verdict.gone
    return Verdict.open if r.status_code == 200 else Verdict.unknown


def _linkedin_verdict(r: httpx.Response) -> Verdict | None:
    """None = LinkedIn refused (too many requests), so the answer says nothing about the job."""
    if r.status_code in (429, 999, 403):
        return None
    if r.status_code in GONE_HTTP:
        return Verdict.gone
    if r.status_code != 200:
        return Verdict.unknown
    return Verdict.gone if _LINKEDIN_CLOSED.search(r.text) else Verdict.open


async def _check_linkedin(client: httpx.AsyncClient, job_id: str) -> Verdict:
    """Guest API first, then the public job page; when both refuse, pause and try once more."""
    for attempt in range(2):
        if attempt:
            await asyncio.sleep(random.uniform(*LIMIT_WAIT))
        for url in (GUEST_API.format(id=job_id), VIEW_URL.format(id=job_id)):
            verdict = _linkedin_verdict(await client.get(url, headers={"Accept-Language": "en-US,en;q=0.9"}))
            if verdict is not None:
                return verdict
    raise LinkedInLimited("LinkedIn refused both the guest API and the job page")


async def _check_page(client: httpx.AsyncClient, url: str) -> Verdict:
    r = await client.get(url)
    if r.status_code in GONE_HTTP:
        return Verdict.gone
    return Verdict.open if r.status_code == 200 else Verdict.unknown


async def check(client: httpx.AsyncClient, job: Job) -> Verdict:
    """Is this job's posting still up? LinkedInLimited is raised so the caller can stop asking LinkedIn."""
    try:
        if ref := _board_ref(job):
            return await _check_board(client, *ref)
        if li := linkedin_job_id(job.url or ""):
            return await _check_linkedin(client, li)
        return await _check_page(client, job.url)
    except LinkedInLimited:
        raise
    except (httpx.HTTPError, ValueError):
        return Verdict.unknown


async def remove_unavailable(
    session: AsyncSession, client: httpx.AsyncClient, user_id: int, *,
    max_linkedin: int = MAX_LINKEDIN, max_other: int = MAX_OTHER,
) -> dict:
    """Check this user's unhandled jobs and delete the ones whose posting is gone. Returns a small report."""
    jobs = (await session.scalars(
        select(Job)
        .where(Job.user_id == user_id, Job.status.in_(CHECK_STATUSES), Job.url.is_not(None), Job.url != "")
        .order_by(Job.checked_at.is_not(None), Job.checked_at, Job.id)  # never / longest ago checked first
    )).all()
    linkedin_jobs = [j for j in jobs if not _board_ref(j) and linkedin_job_id(j.url)][:max_linkedin]
    other_jobs = [j for j in jobs if _board_ref(j) or not linkedin_job_id(j.url)][:max_other]

    gone: list[Job] = []
    checked = 0
    now = datetime.now(timezone.utc)
    sem = asyncio.Semaphore(6)

    async def one(job: Job) -> None:
        nonlocal checked
        async with sem:
            verdict = await check(client, job)
        checked += 1
        job.checked_at = now
        if verdict == Verdict.gone:
            gone.append(job)

    await asyncio.gather(*(one(j) for j in other_jobs))

    limited = False
    refused_in_a_row = 0
    for i, job in enumerate(linkedin_jobs):  # one at a time, spaced out, like the LinkedIn collector
        if i:
            await asyncio.sleep(random.uniform(*LINKEDIN_DELAY))
        try:
            await one(job)
            refused_in_a_row = 0
        except LinkedInLimited:  # this job stays unchecked, so it's first in line next time
            refused_in_a_row += 1
            if refused_in_a_row >= MAX_LIMITED:
                limited = True
                break

    if gone:
        ids = [j.id for j in gone]
        await session.execute(delete(Event).where(Event.job_id.in_(ids)))
        await session.execute(delete(Job).where(Job.user_id == user_id, Job.id.in_(ids)))
    await session.commit()
    log.info("availability user=%s checked=%d removed=%d limited=%s", user_id, checked, len(gone), limited)
    return {
        "checked": checked,
        "removed": len(gone),
        "removed_jobs": [{"title": j.title, "company": j.company} for j in gone][:50],
        "linkedin_limited": limited,
    }


async def sweep(maker, client: httpx.AsyncClient | None = None) -> dict:
    """Background check for every user, a few jobs at a time (worker, every 30 minutes).
    Once LinkedIn refuses, the remaining users' LinkedIn jobs wait for the next sweep."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    result: dict[int, dict] = {}
    linkedin_ok = True
    try:
        async with maker() as session:
            user_ids = (await session.scalars(
                select(Job.user_id).where(Job.status.in_(CHECK_STATUSES)).distinct()
            )).all()
        for uid in user_ids:
            async with maker() as session:
                report = await remove_unavailable(
                    session, client, uid, max_linkedin=SWEEP_LINKEDIN if linkedin_ok else 0, max_other=SWEEP_OTHER)
            linkedin_ok = linkedin_ok and not report["linkedin_limited"]
            result[uid] = {k: report[k] for k in ("checked", "removed")}
    finally:
        if own:
            await client.aclose()
    return result
