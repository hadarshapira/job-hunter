"""LinkedIn job links.

Used only for links the user shares or pastes (one request per import, no crawling).
LinkedIn's public "guest" job page is plain HTML with stable class names, but no JSON-LD.
"""

import re
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
from selectolax.lexbor import LexborHTMLParser

from app.services.importer import ParsedJob, guess_work_mode, html_to_text

GUEST_API = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
_VIEW = re.compile(r"/jobs/view/(?:[^/]*-)?(\d{6,})")
_AGO = re.compile(r"(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago", re.I)
_DAYS = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}


def linkedin_job_id(url: str) -> str | None:
    u = urlparse(url)
    if not u.netloc.lower().endswith("linkedin.com"):
        return None
    if m := _VIEW.search(u.path):
        return m.group(1)
    qs = parse_qs(u.query)
    for key in ("currentJobId", "jobId"):  # search results / recommendations links
        if key in qs and qs[key][0].isdigit():
            return qs[key][0]
    return None


def _posted(text: str, today: date | None = None) -> date | None:
    m = _AGO.search(text or "")
    if not m:
        return None
    return (today or date.today()) - timedelta(days=int(m.group(1)) * _DAYS[m.group(2).lower()])


def parse_linkedin_html(html: str) -> ParsedJob | None:
    tree = LexborHTMLParser(html)

    def text(sel: str) -> str:
        node = tree.css_first(sel)
        return node.text(strip=True) if node else ""

    title = text(".top-card-layout__title") or text(".topcard__title")
    if not title:
        return None
    company = text(".topcard__org-name-link") or text(".topcard__flavor")
    location = ""
    for node in tree.css(".topcard__flavor--bullet"):
        if "applicant" not in (node.attributes.get("class") or "") and not node.css_first(".num-applicants__caption"):
            location = node.text(strip=True)
            break

    desc_node = tree.css_first(".show-more-less-html__markup") or tree.css_first(".description__text")
    description = html_to_text(desc_node.html or "") if desc_node else ""
    description = re.sub(r"^\s*Description\s*", "", description).replace("﻿", "")

    criteria = {}
    for item in tree.css(".description__job-criteria-item"):
        key, val = item.css_first(".description__job-criteria-subheader"), item.css_first(".description__job-criteria-text")
        if key and val:
            criteria[key.text(strip=True)] = val.text(strip=True)
    details = [f"{k}: {v}" for k, v in criteria.items() if v and v != "Not Applicable"]
    if details:
        description = description + "\n\n" + "\n".join(details)

    salary = text(".compensation__salary") or None
    return ParsedJob(
        title=title,
        company=company,
        location=location,
        work_mode=guess_work_mode(title, location, description),
        description=description.strip(),
        salary=salary,
        posted_at=_posted(text(".posted-time-ago__text")),
        extra={"criteria": criteria},
    )


async def _resolve_short_link(url: str, client: httpx.AsyncClient) -> str:
    """lnkd.in short links redirect (sometimes via an interstitial page) to the real job URL."""
    r = await client.get(url)
    if linkedin_job_id(str(r.url)):
        return str(r.url)
    m = re.search(r"https://(?:www\.)?linkedin\.com/jobs/view/[^\s\"'<>]+", r.text)
    return m.group(0) if m else url


async def extract_linkedin(url: str, client: httpx.AsyncClient) -> ParsedJob | None:
    try:
        if urlparse(url).netloc.lower() == "lnkd.in":
            url = await _resolve_short_link(url, client)
        job_id = linkedin_job_id(url)
        if not job_id:
            return None
        r = await client.get(GUEST_API.format(id=job_id), headers={"Accept-Language": "en-US,en;q=0.9"})
        if r.status_code != 200:
            r = await client.get(f"https://www.linkedin.com/jobs/view/{job_id}/", headers={"Accept-Language": "en-US,en;q=0.9"})
        return parse_linkedin_html(r.text) if r.status_code == 200 else None
    except httpx.HTTPError:
        return None
