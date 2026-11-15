"""Collect postings from all sources and add the matching ones to each user's feed (status "new")."""

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.collectors import Posting
from app.collectors import boards, jsearch, linkedin
from app.models import COLLECT_SOURCES, CollectionRun, Company, Event, Job, Status, User, UserProfile, UserSettings
from app.services import matching
from app.services.dedup import dedup_key, loose_key
from app.services.filters import location_decision, title_matches
from app.services.geo import geocode, haversine_km, in_israel
from app.services.importer import USER_AGENT
from app.services.quality import assess

log = logging.getLogger("jobhunter.ingest")
MAX_JSEARCH_QUERIES = 4  # per day (results cached 20 h), across all users (free plan: 200/month)
SOURCE_LABEL = {"linkedin": "LinkedIn", "jsearch": "JSearch", "greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby"}


async def settings_for(session: AsyncSession, user_id: int) -> UserSettings:
    s = await session.get(UserSettings, user_id)
    if s is None:
        s = UserSettings(user_id=user_id)
        session.add(s)
        await session.flush()
    return s


def enabled_sources(s: UserSettings) -> list[str]:
    return [x for x in COLLECT_SOURCES if x in (s.sources if s.sources is not None else COLLECT_SOURCES)]


def _phrases(all_settings: list[UserSettings], source: str) -> list[str]:
    """Title phrases of every user searching this source, most shared first."""
    counts: dict[str, int] = {}
    order: dict[str, int] = {}
    for s in all_settings:
        if source not in enabled_sources(s):
            continue
        for i, kw in enumerate(s.title_keywords or []):
            q = " ".join(kw.lower().split())
            if q:
                counts[q] = counts.get(q, 0) + 1
                order[q] = min(order.get(q, 99), i)
    return sorted(counts, key=lambda q: (-counts[q], order[q]))


def jsearch_queries(all_settings: list[UserSettings]) -> list[str]:
    """Shared, de-duplicated JSearch queries: every user's title phrases, most popular first."""
    return _phrases(all_settings, "jsearch")[:MAX_JSEARCH_QUERIES]


def _wanted_by_anyone(all_settings: list[UserSettings], source: str):
    users = [s for s in all_settings if source in enabled_sources(s)]
    return lambda title: any(
        title_matches(title, s.title_keywords or [], s.exclude_keywords or [], s.senior_only) for s in users
    )


async def _gather_postings(
    session: AsyncSession, client: httpx.AsyncClient, all_settings: list[UserSettings], errors: list[str],
    boards_wanted: set[str], stats: dict,
):
    queries = jsearch_queries(all_settings)
    postings: dict[str, Posting] = {}

    # Only the job boards (Greenhouse/Lever/Ashby) that at least one user searches
    companies = [c for c in (await session.scalars(select(Company))).all() if c.ats in boards_wanted]
    sem = asyncio.Semaphore(6)

    async def one(c: Company):
        async with sem:
            try:
                result = await boards.fetch_board(client, c)
                c.last_ok_at, c.last_error = datetime.now(timezone.utc), ""
                return result
            except (httpx.HTTPError, ValueError) as e:
                c.last_error = f"{e.__class__.__name__}: {str(e)[:200]}"
                errors.append(f"{c.name}: {c.last_error}")
                return []

    for batch in await asyncio.gather(*(one(c) for c in companies)):
        for p in batch:
            if in_israel(p.job.location):  # boards list jobs worldwide
                postings[p.key] = p

    if "linkedin" in boards_wanted:
        for p in await linkedin.collect(session, client, _phrases(all_settings, "linkedin"),
                                        _wanted_by_anyone(all_settings, "linkedin"), errors, stats):
            postings[p.key] = p

    for q in queries:
        try:
            for p in await jsearch.search(session, client, q):
                if p.external_id and in_israel(p.job.location, p.country):
                    postings[p.key] = p
        except jsearch.QuotaLow as e:
            errors.append(str(e))
            break
        except httpx.HTTPError as e:
            errors.append(f"JSearch '{q}': {e.__class__.__name__}")
    return list(postings.values())


async def _locate(session: AsyncSession, client: httpx.AsyncClient, postings: list[Posting]) -> None:
    for p in postings:
        if p.lat is None and p.job.location and p.job.work_mode != "remote" and not p.job.extra.get("vague_location"):
            hit = await geocode(session, client, p.job.location)
            if hit:
                p.lat, p.lon = hit[0], hit[1]


async def _add_for_user(
    session: AsyncSession, user_id: int, s: UserSettings, postings: list[Posting], funnel: dict | None = None
) -> int:
    """Add the postings that fit this user's settings. `funnel` collects counts per source and skip reason."""
    funnel = funnel if funnel is not None else {}

    def note(source: str, what: str) -> None:
        funnel.setdefault(source, {}).setdefault(what, 0)
        funnel[source][what] += 1

    existing_keys = set(
        (await session.scalars(select(Job.posting_key).where(Job.user_id == user_id, Job.posting_key.is_not(None)))).all()
    )
    existing_dedup: set[str] = set()
    # company|title -> coordinates of jobs already in the feed, to catch the same job with the city
    # spelled differently ("Tel Aviv-Yafo" vs "תל אביב -יפו") or a company suffix ("Wix.com, Inc.")
    nearby: dict[str, list[tuple[float | None, float | None]]] = {}
    for row in (await session.execute(
        select(Job.dedup_key, Job.title, Job.company, Job.lat, Job.lon).where(Job.user_id == user_id)
    )).all():
        existing_dedup.add(row.dedup_key)
        nearby.setdefault(loose_key(row.title, row.company), []).append((row.lat, row.lon))

    def is_duplicate(job, lat, lon) -> bool:
        if dedup_key(job.title, job.company, job.location) in existing_dedup:
            return True
        for olat, olon in nearby.get(loose_key(job.title, job.company), []):
            if lat is None or olat is None or haversine_km(lat, lon, olat, olon) <= 10:
                return True
        return False

    profile = await session.get(UserProfile, user_id)
    sources = set(enabled_sources(s))
    added = 0
    for p in postings:
        if p.source not in sources:
            continue
        note(p.source, "found")
        if p.key in existing_keys:
            note(p.source, "already_have")
            continue
        if not title_matches(p.job.title, s.title_keywords or [], s.exclude_keywords or [], s.senior_only):
            note(p.source, "title")
            continue
        distance = (
            haversine_km(s.home_lat, s.home_lon, p.lat, p.lon)
            if s.home_lat is not None and p.lat is not None
            else None
        )
        decision = location_decision(s, p.job.work_mode, distance)
        if not decision.ok:
            note(p.source, "location")
            continue
        job, problems = assess(p.job)
        if is_duplicate(job, p.lat, p.lon):
            note(p.source, "duplicate")
            continue  # same job already in the feed or saved from another source/link
        key = dedup_key(job.title, job.company, job.location)
        new_job = Job(
            user_id=user_id,
            source=p.source,
            posting_key=p.key,
            url=p.url,
            title=job.title,
            company=job.company,
            location=job.location,
            work_mode=job.work_mode,
            description=job.description,
            salary=job.salary,
            posted_at=job.posted_at,
            dedup_key=key,
            parse_issues="\n".join(problems),
            lat=p.lat,
            lon=p.lon,
            distance_km=round(distance, 1) if distance is not None else None,
            status=Status.new,
            events=[Event(kind="created", text=f"Found on {SOURCE_LABEL.get(p.source, p.source)}"
                          + (f" (via {job.extra['publisher']})" if job.extra.get("publisher") else ""))],
        )
        matching.apply(new_job, profile, s)
        session.add(new_job)
        existing_keys.add(p.key)
        existing_dedup.add(key)
        nearby.setdefault(loose_key(job.title, job.company), []).append((p.lat, p.lon))
        note(p.source, "added")
        added += 1
    return added


async def collect(maker: async_sessionmaker, user_ids: list[int] | None = None, *, client: httpx.AsyncClient | None = None) -> dict:
    """Run one collection. user_ids=None means all users (the scheduled run)."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    errors: list[str] = []
    result: dict = {}
    try:
        async with maker() as session:
            ids = user_ids or list((await session.scalars(select(User.id))).all())
            runs = {uid: CollectionRun(user_id=uid) for uid in ids}
            session.add_all(runs.values())
            all_settings = [await settings_for(session, uid) for uid in ids]
            await session.commit()

            wanted = {src for s in all_settings for src in enabled_sources(s)}
            shared: dict = {}
            postings = await _gather_postings(session, client, all_settings, errors, wanted, shared)
            await _locate(session, client, postings)
            await session.commit()

            for s in all_settings:
                funnel: dict = {}
                added = await _add_for_user(session, s.user_id, s, postings, funnel)
                run = runs[s.user_id]
                run.stats = {"sources": funnel, "linkedin": shared}
                run.added, run.seen, run.errors = added, len(postings), "\n".join(errors)
                run.finished_at = datetime.now(timezone.utc)
                result[s.user_id] = added
            await session.commit()
    finally:
        if own:
            await client.aclose()
    log.info("collect users=%s postings=%d added=%s errors=%d", user_ids or "all", len(postings), result, len(errors))
    return {"added": result, "postings": len(postings), "errors": errors}
