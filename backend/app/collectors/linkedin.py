"""LinkedIn jobs in Israel, through LinkedIn's public (no login) job search.

The guest search returns 10 cards per page (title, company, location, date). Work mode isn't on
the card, so extra searches filtered to Remote and Hybrid tell us which jobs are which. Full
descriptions come from the public job page, fetched only for jobs whose title fits someone's
search and that we haven't read before. Requests are spaced out; if LinkedIn starts refusing
(HTTP 429/999) the run stops politely and keeps what it has.
"""

import asyncio
import logging
import random
import re
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx
from selectolax.lexbor import LexborHTMLParser
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import Posting
from app.models import PostingCache, WorkMode
from app.services.importer import ParsedJob, guess_work_mode
from app.services.sites.linkedin import GUEST_API, parse_linkedin_html

log = logging.getLogger("jobhunter.linkedin")
SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
ISRAEL_GEO_ID = "101620260"
PAST_WEEK = "r604800"
MAX_PAGES = 8          # per title phrase: up to 80 newest jobs
MODE_PAGES = 3         # per title phrase, for each of Remote / Hybrid
MAX_DETAILS = 80       # job pages read per run; the rest are read in the next run
MAX_KEYWORDS = 6
CACHE_DAYS = 30
DELAY = (1.0, 2.0)     # seconds between requests
HEADERS = {"Accept-Language": "en-US,en;q=0.9"}
# Region-level locations are too vague for a distance (Central District spans 60+ km)
_VAGUE = re.compile(r"^(central|center|northern|southern|north|south)\s+district\b|^israel$", re.I)


class Limited(Exception):
    pass


@dataclass
class Card:
    id: str
    title: str
    company: str
    location: str
    url: str
    posted: _date | None


def parse_cards(html: str) -> list[Card]:
    tree = LexborHTMLParser(html)
    cards = []
    for node in tree.css("div[data-entity-urn]"):
        urn = node.attributes.get("data-entity-urn") or ""
        m = re.search(r"jobPosting:(\d+)", urn)
        if not m:
            continue

        def text(sel: str) -> str:
            n = node.css_first(sel)
            return " ".join(n.text().split()) if n else ""

        when = node.css_first("time")
        posted = None
        if when and (dt := when.attributes.get("datetime")):
            try:
                posted = _date.fromisoformat(dt[:10])
            except ValueError:
                pass
        cards.append(Card(
            id=m.group(1),
            title=text(".base-search-card__title"),
            company=text(".base-search-card__subtitle"),
            location=text(".job-search-card__location"),
            url=f"https://www.linkedin.com/jobs/view/{m.group(1)}/",
            posted=posted,
        ))
    return cards


async def _get(client: httpx.AsyncClient, url: str, params: dict | None = None) -> httpx.Response:
    r = await client.get(url, params=params, headers=HEADERS, timeout=30)
    if r.status_code in (429, 999) or (r.status_code == 403 and "linkedin" in url):
        raise Limited(f"LinkedIn is limiting requests (HTTP {r.status_code}); the rest will be fetched next run")
    return r


async def _pause() -> None:
    await asyncio.sleep(random.uniform(*DELAY))


async def search_ids(client: httpx.AsyncClient, keyword: str, pages: int, workplace: str | None = None) -> list[Card]:
    """Newest-first cards for one keyword, paging until results run out or repeat."""
    seen: dict[str, Card] = {}
    for page in range(pages):
        params = {"keywords": keyword, "location": "Israel", "geoId": ISRAEL_GEO_ID, "f_TPR": PAST_WEEK,
                  "start": page * 10}
        if workplace:
            params["f_WT"] = workplace
        if page or workplace:
            await _pause()
        r = await _get(client, SEARCH, params)
        if r.status_code == 400 or r.status_code == 404:
            break  # past the last page
        r.raise_for_status()
        cards = parse_cards(r.text)
        new = [c for c in cards if c.id not in seen]
        for c in new:
            seen[c.id] = c
        if len(cards) < 10 or not new:
            break
    return list(seen.values())


def _vague(location: str) -> bool:
    first = (location or "").split(",")[0].strip()
    return not first or bool(_VAGUE.match(first))


async def collect(
    session: AsyncSession,
    client: httpx.AsyncClient,
    keywords: list[str],
    wanted: Callable[[str], bool],
    errors: list[str],
    stats: dict,
) -> list[Posting]:
    """LinkedIn postings for the given title phrases. `wanted(title)` decides which jobs are worth reading."""
    cards: dict[str, Card] = {}
    mode: dict[str, str] = {}
    try:
        for kw in keywords[:MAX_KEYWORDS]:
            for c in await search_ids(client, kw, MAX_PAGES):
                cards.setdefault(c.id, c)
            for wt, m in (("2", WorkMode.remote), ("3", WorkMode.hybrid)):
                for c in await search_ids(client, kw, MODE_PAGES, workplace=wt):
                    cards.setdefault(c.id, c)
                    mode[c.id] = m
    except Limited as e:
        errors.append(str(e))
    except httpx.HTTPError as e:
        errors.append(f"LinkedIn search: {e.__class__.__name__}")
    stats["linkedin_found"] = len(cards)

    candidates = [c for c in cards.values() if wanted(c.title)]
    stats["linkedin_title_skip"] = len(cards) - len(candidates)

    # Reuse job pages already read (for any user) instead of fetching them again
    now = datetime.now(timezone.utc)
    await session.execute(delete(PostingCache).where(PostingCache.fetched_at < now - timedelta(days=CACHE_DAYS)))
    keys = [f"linkedin:{c.id}" for c in candidates]
    known: dict[str, dict] = {}
    if keys:
        known = {row.key: row.data for row in (await session.scalars(select(PostingCache).where(PostingCache.key.in_(keys)))).all()}

    postings, fetched, deferred = [], 0, 0
    limited = False
    for c in candidates:
        key = f"linkedin:{c.id}"
        if key in known:
            d = known[key]
            parsed = ParsedJob(title=d.get("title", ""), company=d.get("company", ""), location=d.get("location", ""),
                               work_mode=d.get("work_mode") or WorkMode.unknown, description=d.get("description", ""),
                               salary=d.get("salary"),
                               posted_at=_date.fromisoformat(d["posted_at"]) if d.get("posted_at") else None)
        elif limited or fetched >= MAX_DETAILS:
            deferred += 1
            continue
        else:
            parsed = None
            try:
                await _pause()
                r = await _get(client, GUEST_API.format(id=c.id))
                fetched += 1
                if r.status_code == 200:
                    parsed = parse_linkedin_html(r.text)
            except Limited as e:
                errors.append(str(e))
                limited = True
                deferred += 1
                continue
            except httpx.HTTPError:
                pass
            if parsed is not None:
                session.add(PostingCache(key=key, fetched_at=now, data={
                    "title": parsed.title, "company": parsed.company, "location": parsed.location,
                    "work_mode": str(parsed.work_mode), "description": parsed.description, "salary": parsed.salary,
                    "posted_at": parsed.posted_at.isoformat() if parsed.posted_at else None,
                }))
            if parsed is None:  # page unreadable: keep the card so the job isn't lost
                parsed = ParsedJob(title=c.title, company=c.company, location=c.location, work_mode=WorkMode.unknown,
                                   description="", posted_at=c.posted)
        parsed.title = parsed.title or c.title
        parsed.company = parsed.company or c.company
        parsed.location = parsed.location or c.location
        parsed.posted_at = parsed.posted_at or c.posted
        # Work mode: LinkedIn's own Remote/Hybrid filter beats guessing from the text
        if c.id in mode:
            parsed.work_mode = mode[c.id]
        elif parsed.work_mode == WorkMode.unknown:
            parsed.work_mode = guess_work_mode(parsed.title, parsed.location, parsed.description)
        if not parsed.location.lower().endswith("israel"):
            parsed.location = f"{parsed.location}, Israel" if parsed.location else "Israel"
        parsed.extra = {**(parsed.extra or {}), "vague_location": _vague(parsed.location)}
        postings.append(Posting(job=parsed, source="linkedin", external_id=c.id, url=c.url, country="IL"))
    stats["linkedin_read"] = fetched
    if deferred:
        stats["linkedin_deferred"] = deferred
    log.info("linkedin keywords=%s cards=%d candidates=%d fetched=%d deferred=%d",
             keywords[:MAX_KEYWORDS], len(cards), len(candidates), fetched, deferred)
    return postings
