"""Find jobs whose posting is gone (closed, filled, deleted) and remove them from the user's list.

Runs on "Find jobs now". Only jobs the user hasn't acted on yet are checked (status new or saved):
applications in progress keep their history even when the posting closes.

A job is removed only when the site clearly says it's gone. Anything unclear (timeouts, blocks,
rate limits, server errors, login walls) keeps the job, so a flaky site never empties the list.
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
from app.services.sites.linkedin import GUEST_API, linkedin_job_id

log = logging.getLogger("jobhunter.availability")
CHECK_STATUSES = (Status.new, Status.saved)
MAX_LINKEDIN = 40   # LinkedIn pages checked per run (slowly); the rest are checked in later runs
MAX_OTHER = 150     # other links checked per run
LINKEDIN_DELAY = (1.0, 2.0)
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


async def _check_linkedin(client: httpx.AsyncClient, job_id: str) -> Verdict:
    r = await client.get(GUEST_API.format(id=job_id), headers={"Accept-Language": "en-US,en;q=0.9"})
    if r.status_code in (429, 999, 403):
        raise LinkedInLimited(f"HTTP {r.status_code}")
    if r.status_code in GONE_HTTP:
        return Verdict.gone
    if r.status_code != 200:
        return Verdict.unknown
    return Verdict.gone if _LINKEDIN_CLOSED.search(r.text) else Verdict.open


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


async def remove_unavailable(session: AsyncSession, client: httpx.AsyncClient, user_id: int) -> dict:
    """Check this user's unhandled jobs and delete the ones whose posting is gone. Returns a small report."""
    jobs = (await session.scalars(
        select(Job)
        .where(Job.user_id == user_id, Job.status.in_(CHECK_STATUSES), Job.url.is_not(None), Job.url != "")
        .order_by(Job.checked_at.is_not(None), Job.checked_at, Job.id)  # never / longest ago checked first
    )).all()
    linkedin_jobs = [j for j in jobs if not _board_ref(j) and linkedin_job_id(j.url)][:MAX_LINKEDIN]
    other_jobs = [j for j in jobs if _board_ref(j) or not linkedin_job_id(j.url)][:MAX_OTHER]

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
    for i, job in enumerate(linkedin_jobs):  # one at a time, spaced out, like the LinkedIn collector
        if i:
            await asyncio.sleep(random.uniform(*LINKEDIN_DELAY))
        try:
            await one(job)
        except LinkedInLimited:
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
