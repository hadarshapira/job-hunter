"""Collect postings from all sources and add the matching ones to each user's feed (status "new")."""

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.collectors import Posting
from app.collectors import boards, jsearch
from app.models import CollectionRun, Company, Event, Job, Status, User, UserSettings
from app.services.dedup import dedup_key, loose_key
from app.services.filters import location_decision, title_matches
from app.services.geo import geocode, haversine_km, in_israel
from app.services.importer import USER_AGENT
from app.services.quality import assess

log = logging.getLogger("jobhunter.ingest")
MAX_JSEARCH_QUERIES = 3  # per run, across all users (free plan: 200/month)
SOURCE_LABEL = {"jsearch": "JSearch", "greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby"}


async def settings_for(session: AsyncSession, user_id: int) -> UserSettings:
    s = await session.get(UserSettings, user_id)
    if s is None:
        s = UserSettings(user_id=user_id)
        session.add(s)
        await session.flush()
    return s


def jsearch_queries(all_settings: list[UserSettings]) -> list[str]:
    """Shared, de-duplicated queries: each user's main (first) title phrase, most popular first.
    The other phrases still filter everything collected; they just don't each cost a JSearch request."""
    counts: dict[str, int] = {}
    for s in all_settings:
        for kw in (s.title_keywords or [])[:1]:
            q = ("senior " if s.senior_only and "senior" not in kw.lower() else "") + kw.strip().lower()
            counts[q] = counts.get(q, 0) + 1
    return sorted(counts, key=lambda q: -counts[q])[:MAX_JSEARCH_QUERIES]


async def _gather_postings(session: AsyncSession, client: httpx.AsyncClient, queries: list[str], errors: list[str]):
    postings: dict[str, Posting] = {}

    companies = (await session.scalars(select(Company))).all()
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
        if p.lat is None and p.job.location and p.job.work_mode != "remote":
            hit = await geocode(session, client, p.job.location)
            if hit:
                p.lat, p.lon = hit[0], hit[1]


async def _add_for_user(session: AsyncSession, user_id: int, s: UserSettings, postings: list[Posting]) -> int:
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

    added = 0
    for p in postings:
        if p.key in existing_keys:
            continue
        if not title_matches(p.job.title, s.title_keywords or [], s.exclude_keywords or [], s.senior_only):
            continue
        distance = (
            haversine_km(s.home_lat, s.home_lon, p.lat, p.lon)
            if s.home_lat is not None and p.lat is not None
            else None
        )
        decision = location_decision(s, p.job.work_mode, distance)
        if not decision.ok:
            continue
        job, problems = assess(p.job)
        if is_duplicate(job, p.lat, p.lon):
            continue  # same job already in the feed or saved from another source/link
        key = dedup_key(job.title, job.company, job.location)
        session.add(
            Job(
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
        )
        existing_keys.add(p.key)
        existing_dedup.add(key)
        nearby.setdefault(loose_key(job.title, job.company), []).append((p.lat, p.lon))
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

            postings = await _gather_postings(session, client, jsearch_queries(all_settings), errors)
            await _locate(session, client, postings)
            await session.commit()

            for s in all_settings:
                added = await _add_for_user(session, s.user_id, s, postings)
                run = runs[s.user_id]
                run.added, run.seen, run.errors = added, len(postings), "\n".join(errors)
                run.finished_at = datetime.now(timezone.utc)
                result[s.user_id] = added
            await session.commit()
    finally:
        if own:
            await client.aclose()
    log.info("collect users=%s postings=%d added=%s errors=%d", user_ids or "all", len(postings), result, len(errors))
    return {"added": result, "postings": len(postings), "errors": errors}
