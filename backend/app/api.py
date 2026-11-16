import logging
from datetime import date, datetime, timedelta, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from app.auth import current_user
from app.db import get_session
from app.models import Event, Job, Status, User
from app.schemas import (
    ImportRequest,
    ImportResult,
    JobCreate,
    JobOut,
    JobSummary,
    JobUpdate,
    NoteCreate,
    Stats,
)
from app.services import matching
from app.services.dedup import dedup_key
from app.services.importer import fetch_and_parse

router = APIRouter(prefix="/api")
log = logging.getLogger("jobhunter.import")

RESPONDED = {Status.screening, Status.interview, Status.offer, Status.rejected}
FOLLOW_UP_DAYS = 7


async def _load(session: AsyncSession, user: User, job_id: int) -> Job:
    # Always scoped to the signed-in user: another user's job id returns 404, never their data
    job = await session.scalar(
        select(Job)
        .where(Job.id == job_id, Job.user_id == user.id)
        .options(selectinload(Job.events))
        .execution_options(populate_existing=True)  # reload events in timeline order after changes
    )
    if not job:
        raise HTTPException(404, "Job not found")
    return job


def _apply_status(job: Job, new: Status) -> None:
    if job.status == new:
        return
    old = job.status
    job.status = new
    job.events.append(Event(kind="status", text=f"{old} → {new}"))
    if new == Status.applied and not job.applied_at:
        job.applied_at = datetime.now(timezone.utc)
        if not job.follow_up_on:
            job.follow_up_on = date.today() + timedelta(days=FOLLOW_UP_DAYS)
    if new in RESPONDED | {Status.ghosted, Status.archived}:
        job.follow_up_on = None


def _filtered(stmt, status: list[Status] | None, q: str | None):
    """Status and title/company search filters, shared by the job list and its source counts."""
    if status:
        stmt = stmt.where(Job.status.in_([s.value for s in status]))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(Job.title).like(like) | func.lower(Job.company).like(like))
    return stmt


# The list shows cards only: skip the long description and match details, which can be ~5 KB per job
_SUMMARY_COLUMNS = [getattr(Job, f) for f in JobSummary.model_fields]


@router.get("/jobs", response_model=list[JobSummary])
async def list_jobs(
    status: list[Status] | None = Query(None),
    q: str | None = None,
    sort: Literal["recent", "match"] = "recent",
    source: list[str] | None = Query(None),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    order = [Job.updated_at.desc()]
    if sort == "match":
        order.insert(0, Job.match_score.desc().nulls_last())
    stmt = select(Job).options(load_only(*_SUMMARY_COLUMNS)).where(Job.user_id == user.id).order_by(*order)
    stmt = _filtered(stmt, status, q)
    if source:
        stmt = stmt.where(Job.source.in_(source))
    return (await session.scalars(stmt.limit(500))).all()


@router.get("/jobs/sources", response_model=dict[str, int])
async def job_sources(
    status: list[Status] | None = Query(None),
    q: str | None = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """How many of the user's jobs came from each source (same status/search filters as the list)."""
    stmt = select(Job.source, func.count()).where(Job.user_id == user.id).group_by(Job.source)
    return dict((await session.execute(_filtered(stmt, status, q))).all())


@router.post("/jobs", response_model=JobOut, status_code=201)
async def create_job(body: JobCreate, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    data = body.model_dump(exclude={"status"})
    job = Job(
        **data,
        user_id=user.id,
        source="manual",
        dedup_key=dedup_key(body.title, body.company, body.location),
        status=Status.saved,
        events=[Event(kind="created", text="Added manually")],
    )
    _apply_status(job, body.status)
    await matching.apply_one(session, job)
    session.add(job)
    await session.commit()
    return await _load(session, user, job.id)


@router.post("/jobs/import", response_model=ImportResult)
async def import_job(body: ImportRequest, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    url = str(body.url)
    existing = await session.scalar(select(Job.id).where(Job.user_id == user.id, Job.url == url))
    if existing:
        return ImportResult(job=await _load(session, user, existing), duplicate=True)
    try:
        parsed = await fetch_and_parse(url)
    except httpx.HTTPError as exc:
        raise HTTPException(422, f"Could not fetch that page: {exc.__class__.__name__}")

    key = dedup_key(parsed.title, parsed.company, parsed.location)
    if parsed.complete and parsed.company:
        dup = await session.scalar(select(Job.id).where(Job.user_id == user.id, Job.dedup_key == key))
        if dup:
            return ImportResult(job=await _load(session, user, dup), duplicate=True)

    job = Job(
        user_id=user.id,
        source="link",
        url=url,
        title=parsed.title,
        company=parsed.company,
        location=parsed.location,
        work_mode=parsed.work_mode,
        description=parsed.description,
        salary=parsed.salary,
        posted_at=parsed.posted_at,
        dedup_key=key,
        parse_issues="\n".join(parsed.issues),
        status=Status.saved,
        events=[Event(kind="created", text=f"Imported from {httpx.URL(url).host}")],
    )
    await matching.apply_one(session, job)
    session.add(job)
    await session.commit()
    _log_issues(url, parsed)
    return ImportResult(job=await _load(session, user, job.id), complete=parsed.complete)


def _log_issues(url: str, parsed) -> None:
    if parsed.issues:
        log.warning(
            "import_quality host=%s extractor=%s issues=%s",
            httpx.URL(url).host, parsed.extra.get("extractor"), "; ".join(parsed.issues),
        )


@router.post("/jobs/{job_id}/reimport", response_model=ImportResult)
async def reimport_job(job_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Re-read a job's link with the current parsers. Tracker data (status, notes, dates) is kept."""
    job = await _load(session, user, job_id)
    if not job.url:
        raise HTTPException(400, "This job has no link to re-import from")
    try:
        parsed = await fetch_and_parse(job.url)
    except httpx.HTTPError as exc:
        raise HTTPException(422, f"Could not fetch that page: {exc.__class__.__name__}")
    changed = []
    for field in ("title", "company", "location", "description", "salary", "posted_at"):
        new = getattr(parsed, field)
        if new and new != getattr(job, field):
            setattr(job, field, new)
            changed.append(field)
    if parsed.work_mode != "unknown" and parsed.work_mode != job.work_mode:
        job.work_mode = parsed.work_mode
        changed.append("work_mode")
    job.parse_issues = "\n".join(parsed.issues)
    job.dedup_key = dedup_key(job.title, job.company, job.location)
    await matching.apply_one(session, job)
    job.events.append(Event(kind="note", text="Re-imported: " + (", ".join(changed) + " updated" if changed else "no changes")))
    job.updated_at = datetime.now(timezone.utc)
    await session.commit()
    _log_issues(job.url, parsed)
    return ImportResult(job=await _load(session, user, job_id), complete=parsed.complete)


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await _load(session, user, job_id)


@router.patch("/jobs/{job_id}", response_model=JobOut)
async def update_job(
    job_id: int, body: JobUpdate, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    job = await _load(session, user, job_id)
    changes = body.model_dump(exclude_unset=True)
    new_status = changes.pop("status", None)
    for key, value in changes.items():
        setattr(job, key, value)
    if {"title", "company", "location"} & changes.keys():
        job.dedup_key = dedup_key(job.title, job.company, job.location)
    if new_status:
        _apply_status(job, Status(new_status))
    if {"title", "description", "work_mode"} & changes.keys():
        await matching.apply_one(session, job)
    job.updated_at = datetime.now(timezone.utc)
    await session.commit()
    return await _load(session, user, job_id)


@router.post("/jobs/{job_id}/notes", response_model=JobOut)
async def add_note(
    job_id: int, body: NoteCreate, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    job = await _load(session, user, job_id)
    job.events.append(Event(kind="note", text=body.text.strip()))
    job.updated_at = datetime.now(timezone.utc)
    await session.commit()
    return await _load(session, user, job_id)


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(job_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    job = await _load(session, user, job_id)
    await session.delete(job)
    await session.commit()


@router.get("/stats", response_model=Stats)
async def stats(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    mine = Job.user_id == user.id
    by_status = dict((await session.execute(select(Job.status, func.count()).where(mine).group_by(Job.status))).all())
    by_source = dict((await session.execute(select(Job.source, func.count()).where(mine).group_by(Job.source))).all())
    applied_total = await session.scalar(select(func.count()).where(mine, Job.applied_at.is_not(None))) or 0
    responded = await session.scalar(
        select(func.count()).where(mine, Job.applied_at.is_not(None), Job.status.in_([s.value for s in RESPONDED]))
    ) or 0
    due = await session.scalar(
        select(func.count()).where(mine, Job.follow_up_on.is_not(None), Job.follow_up_on <= date.today())
    ) or 0
    return Stats(
        new=by_status.get(Status.new, 0),
        by_status=by_status,
        by_source=by_source,
        applied_total=applied_total,
        responded=responded,
        response_rate=round(responded / applied_total, 3) if applied_total else 0.0,
        follow_ups_due=due,
    )
