"""Company job boards through the free public APIs of Greenhouse, Lever and Ashby. No limits, no keys."""

import re
from urllib.parse import urlparse

import httpx

from app.collectors import Posting
from app.models import Company
from app.services.ats import ashby_job, greenhouse_job, lever_job


async def fetch_board(client: httpx.AsyncClient, company: Company) -> list[Posting]:
    if company.ats == "greenhouse":
        r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{company.slug}/jobs", params={"content": "true"})
        r.raise_for_status()
        out = []
        for d in r.json().get("jobs", []):
            job = greenhouse_job(d, company.slug)
            job.company = company.name or job.company
            out.append(Posting(job, "greenhouse", f"{company.slug}/{d['id']}", d.get("absolute_url")))
        return out
    if company.ats == "lever":
        r = await client.get(f"https://api.lever.co/v0/postings/{company.slug}", params={"mode": "json"})
        r.raise_for_status()
        out = []
        for d in r.json():
            job = lever_job(d, company.slug)
            job.company = company.name or job.company
            out.append(Posting(job, "lever", f"{company.slug}/{d['id']}", d.get("hostedUrl")))
        return out
    if company.ats == "ashby":
        r = await client.get(
            f"https://api.ashbyhq.com/posting-api/job-board/{company.slug}", params={"includeCompensation": "true"}
        )
        r.raise_for_status()
        out = []
        for d in r.json().get("jobs", []):
            job = ashby_job(d, company.slug)
            job.company = company.name or job.company
            out.append(Posting(job, "ashby", f"{company.slug}/{d['id']}", d.get("jobUrl")))
        return out
    raise ValueError(f"Unknown ATS {company.ats}")


def board_from_url(text: str) -> tuple[str, str] | None:
    """Recognize a board from what a user pastes: a careers URL or 'greenhouse:slug'."""
    text = text.strip()
    if m := re.fullmatch(r"(greenhouse|lever|ashby):([\w.-]+)", text, re.I):
        return m.group(1).lower(), m.group(2).lower()
    u = urlparse(text if "://" in text else f"https://{text}")
    host, parts = u.netloc.lower(), [p for p in u.path.split("/") if p]
    if "greenhouse.io" in host:
        if "for" in u.query:
            m = re.search(r"for=([\w-]+)", u.query)
            return ("greenhouse", m.group(1).lower()) if m else None
        if parts and parts[0] not in ("embed", "v1"):
            return "greenhouse", parts[0].lower()
    if host == "jobs.lever.co" and parts:
        return "lever", parts[0].lower()
    if host == "jobs.ashbyhq.com" and parts:
        return "ashby", parts[0].lower()
    return None
