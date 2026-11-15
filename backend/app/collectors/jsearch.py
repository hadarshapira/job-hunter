"""JSearch (RapidAPI): Google for Jobs data, which includes LinkedIn, Indeed, Glassdoor and company sites.

Free plan: 200 requests/month for the whole app, so results are cached per query and shared by
all users (SearchCache), and requests stop when the remaining quota gets low.
"""

import logging
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import Posting
from app.config import get_settings
from app.models import SearchCache, WorkMode
from app.services.importer import ParsedJob, guess_work_mode

log = logging.getLogger("jobhunter.jsearch")
URL = "https://jsearch.p.rapidapi.com/search-v2"  # "/search" was retired
HOST = "jsearch.p.rapidapi.com"


class QuotaLow(Exception):
    pass


def _salary(j: dict) -> str | None:
    if j.get("job_salary_string"):
        return j["job_salary_string"]
    lo, hi = j.get("job_min_salary"), j.get("job_max_salary")
    if lo or hi:
        amount = f"{lo:,.0f}-{hi:,.0f}" if lo and hi else f"{lo or hi:,.0f}"
        return f"{amount} {j.get('job_salary_period') or ''}".strip()
    return None


def to_posting(j: dict) -> Posting:
    from app.services.geo import in_israel_bbox, mentions_israel

    city, country = j.get("job_city") or "", j.get("job_country") or ""
    lat, lon = j.get("job_latitude"), j.get("job_longitude")
    # Known JSearch quirk: Israeli jobs often come back with job_country "US" (and Hebrew city names)
    if country.upper() != "IL" and (mentions_israel(city) or mentions_israel(j.get("job_location") or "")):
        country = "IL"
    if country.upper() == "IL":
        location = f"{city}, Israel" if city else "Israel"
        if not in_israel_bbox(lat, lon):
            lat = lon = None  # coordinates for the wrong country; geocode the city instead
    else:
        location = ", ".join(p for p in (city, country) if p) or j.get("job_location") or ""
    description = j.get("job_description") or ""
    mode = WorkMode.remote if j.get("job_is_remote") else guess_work_mode(j.get("job_title", ""), location, description)
    posted = None
    if ts := j.get("job_posted_at_timestamp"):
        posted = datetime.fromtimestamp(ts, tz=timezone.utc).date()
    elif dt := j.get("job_posted_at_datetime_utc"):
        posted = date.fromisoformat(dt[:10])
    return Posting(
        job=ParsedJob(
            title=(j.get("job_title") or "").strip(),
            company=(j.get("employer_name") or "").strip(),
            location=location,
            work_mode=mode,
            description=description,
            salary=_salary(j),
            posted_at=posted,
            extra={"publisher": j.get("job_publisher")},
        ),
        source="jsearch",
        external_id=j.get("job_id") or j.get("job_uid") or "",
        url=j.get("job_apply_link") or j.get("job_google_link"),
        lat=lat,
        lon=lon,
        country=country or None,
    )


async def search(session: AsyncSession, client: httpx.AsyncClient, query: str, *, force: bool = False) -> list[Posting]:
    """Postings for "<query> in Israel" from the past week, using the shared cache when fresh."""
    settings = get_settings()
    key = query.strip().lower()
    cached = await session.get(SearchCache, key)
    now = datetime.now(timezone.utc)
    if cached and not force:
        age = now - cached.fetched_at.replace(tzinfo=cached.fetched_at.tzinfo or timezone.utc)
        if age < timedelta(hours=settings.jsearch_cache_hours):
            return [to_posting(j) for j in cached.results]
    if not settings.jsearch_api_key:
        return []
    remaining = await quota_remaining(session)
    if remaining is not None and remaining <= settings.jsearch_min_quota:
        raise QuotaLow(f"JSearch quota low ({remaining} left this month); using company boards only")

    r = await client.get(
        URL,
        params={"query": f"{query} in Israel", "country": "il", "date_posted": "week", "page": 1, "num_pages": 1},
        headers={"x-rapidapi-key": settings.jsearch_api_key, "x-rapidapi-host": HOST},
        timeout=40,
    )
    r.raise_for_status()
    data = r.json().get("data") or {}
    jobs = data.get("jobs", []) if isinstance(data, dict) else data
    left = r.headers.get("x-ratelimit-requests-remaining")
    if cached is None:
        cached = SearchCache(query=key)
        session.add(cached)
    cached.results, cached.fetched_at = jobs, now
    cached.quota_remaining = int(left) if left and left.isdigit() else None
    await session.flush()
    log.info("jsearch query=%r jobs=%d quota_left=%s", query, len(jobs), left)
    return [to_posting(j) for j in jobs]


async def quota_remaining(session: AsyncSession) -> int | None:
    from sqlalchemy import select

    row = await session.scalar(
        select(SearchCache).where(SearchCache.quota_remaining.is_not(None)).order_by(SearchCache.fetched_at.desc())
    )
    return row.quota_remaining if row else None
