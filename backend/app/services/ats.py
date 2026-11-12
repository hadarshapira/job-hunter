"""Resolve job links from common applicant-tracking systems through their free public APIs.

Their job pages are rendered with JavaScript, so scraping the HTML gives almost nothing.
Supported: Greenhouse (incl. company sites with ?gh_jid=), Lever, Ashby.
"""

import re
from datetime import date
from html import unescape
from urllib.parse import parse_qs, urlparse

import httpx

from app.models import WorkMode
from app.services.importer import ParsedJob, guess_work_mode, html_to_text

_GH = re.compile(r"^/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)")
_LEVER = re.compile(r"^/([\w.-]+)/([0-9a-f-]{36})")
_ASHBY = re.compile(r"^/([\w.%-]+)/([0-9a-f-]{36})")


def _date(value) -> date | None:
    if isinstance(value, (int, float)):  # Lever uses epoch milliseconds
        from datetime import datetime, timezone

        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _mode(workplace: str | None, *texts: str) -> WorkMode:
    w = (workplace or "").lower().replace("-", "").replace("_", "")
    if w in ("remote",):
        return WorkMode.remote
    if w == "hybrid":
        return WorkMode.hybrid
    if w in ("onsite", "inoffice"):
        return WorkMode.onsite
    return guess_work_mode(*texts)


def greenhouse_ref(url: str) -> tuple[str, str] | None:
    u = urlparse(url)
    host = u.netloc.lower()
    qs = parse_qs(u.query)
    if "greenhouse.io" in host:
        if "for" in qs and "token" in qs:  # embed links
            return qs["for"][0], qs["token"][0]
        m = _GH.match(u.path)
        if m:
            return m.group(1), m.group(2)
    if "gh_jid" in qs:
        # Company careers page with an embedded Greenhouse board: guess the board from the domain
        parts = host.removeprefix("www.").split(".")
        board = parts[-2] if len(parts) >= 2 else parts[0]
        return board, qs["gh_jid"][0]
    return None


async def _greenhouse(client: httpx.AsyncClient, board: str, job_id: str) -> ParsedJob | None:
    r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}")
    if r.status_code != 200:
        return None
    d = r.json()
    description = html_to_text(unescape(d.get("content", "")))
    location = (d.get("location") or {}).get("name", "")
    return ParsedJob(
        title=d.get("title", "").strip(),
        company=d.get("company_name") or board.title(),
        location=location,
        work_mode=_mode(None, d.get("title", ""), location, description),
        description=description,
        posted_at=_date(d.get("first_published") or d.get("updated_at")),
    )


async def _lever(client: httpx.AsyncClient, company: str, job_id: str) -> ParsedJob | None:
    r = await client.get(f"https://api.lever.co/v0/postings/{company}/{job_id}")
    if r.status_code != 200:
        return None
    d = r.json()
    parts = [d.get("descriptionPlain", "")]
    for section in d.get("lists", []):
        items = html_to_text(section.get("content", ""))
        parts.append(f"{section.get('text', '')}\n{items}")
    parts.append(d.get("additionalPlain", ""))
    description = "\n\n".join(p.strip() for p in parts if p and p.strip())
    cats = d.get("categories") or {}
    location = cats.get("location", "")
    salary = None
    if sr := d.get("salaryRange"):
        salary = f"{sr.get('min')}-{sr.get('max')} {sr.get('currency', '')} {sr.get('interval', '')}".strip()
    return ParsedJob(
        title=d.get("text", "").strip(),
        company=company.replace("-", " ").title(),
        location=location,
        work_mode=_mode(d.get("workplaceType"), location, description),
        description=description,
        salary=salary,
        posted_at=_date(d.get("createdAt")),
    )


async def _ashby(client: httpx.AsyncClient, org: str, job_id: str) -> ParsedJob | None:
    r = await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{org}", params={"includeCompensation": "true"})
    if r.status_code != 200:
        return None
    job = next((j for j in r.json().get("jobs", []) if j.get("id") == job_id), None)
    if not job:
        return None
    description = job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml", ""))
    workplace = job.get("workplaceType") or ("Remote" if job.get("isRemote") else None)
    comp = (job.get("compensation") or {}).get("compensationTierSummary")
    return ParsedJob(
        title=job.get("title", "").strip(),
        company=org.replace("-", " ").title(),
        location=job.get("location", ""),
        work_mode=_mode(workplace, job.get("location", ""), description),
        description=description,
        salary=comp,
        posted_at=_date(job.get("publishedAt")),
    )


async def resolve_ats(url: str, client: httpx.AsyncClient) -> ParsedJob | None:
    """Return a complete ParsedJob if the URL belongs to a supported ATS, else None."""
    u = urlparse(url)
    host = u.netloc.lower()
    try:
        if ref := greenhouse_ref(url):
            return await _greenhouse(client, *ref)
        if host == "jobs.lever.co" and (m := _LEVER.match(u.path)):
            return await _lever(client, m.group(1), m.group(2))
        if host == "jobs.ashbyhq.com" and (m := _ASHBY.match(u.path)):
            return await _ashby(client, m.group(1), m.group(2))
    except (httpx.HTTPError, ValueError):
        return None
    return None
