"""Settings, company boards and job collection endpoints."""

from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.collectors import boards
from app.collectors.jsearch import quota_remaining
from app.config import get_settings
from app.db import SessionLocal, get_session
from app.models import COLLECT_SOURCES, CollectionRun, Company, GeoCache, User
from app.services import ai_match, ingest, matching
from app.services.geo import USER_AGENT, geocode, normalize_place

router = APIRouter(prefix="/api")
MODES = {"onsite", "hybrid", "remote"}


class SettingsIn(BaseModel):
    home_label: str = Field(default="", max_length=300)
    work_modes: list[str] = Field(default_factory=lambda: ["onsite", "hybrid", "remote"])
    max_km_onsite: int = Field(default=25, ge=1, le=300)
    max_km_hybrid: int = Field(default=40, ge=1, le=300)
    title_keywords: list[str] = Field(default_factory=list, max_length=15)
    exclude_keywords: list[str] = Field(default_factory=list, max_length=30)
    senior_only: bool = False
    sources: list[str] = Field(default_factory=lambda: list(COLLECT_SOURCES))
    ai_grading: bool = False


class SettingsOut(SettingsIn):
    home_found: str | None = None  # what the home text was matched to on the map
    home_lat: float | None = None
    home_lon: float | None = None
    ai_available: bool = False  # the server has an Anthropic API key


def _clean_list(items: list[str]) -> list[str]:
    seen, out = set(), []
    for i in items:
        v = " ".join(i.split())[:80]
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


async def _out(session: AsyncSession, s) -> SettingsOut:
    label = None  # the place name the map matched the home text to, e.g. "Ramat Gan, Tel Aviv District, Israel"
    if s.home_label and s.home_lat is not None:
        cached = await session.get(GeoCache, normalize_place(s.home_label))
        label = cached.label if cached else s.home_label
    return SettingsOut(
        home_label=s.home_label, work_modes=s.work_modes, max_km_onsite=s.max_km_onsite, max_km_hybrid=s.max_km_hybrid,
        title_keywords=s.title_keywords, exclude_keywords=s.exclude_keywords, senior_only=s.senior_only,
        sources=ingest.enabled_sources(s), ai_grading=s.ai_grading, ai_available=ai_match.available(),
        home_found=label, home_lat=s.home_lat, home_lon=s.home_lon,
    )


@router.get("/settings", response_model=SettingsOut)
async def get_user_settings(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    s = await ingest.settings_for(session, user.id)
    await session.commit()
    return await _out(session, s)


@router.put("/settings", response_model=SettingsOut)
async def put_user_settings(body: SettingsIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    modes = [m for m in body.work_modes if m in MODES]
    if not modes:
        raise HTTPException(422, "Choose at least one work mode")
    sources = [x for x in COLLECT_SOURCES if x in body.sources]
    if not sources:
        raise HTTPException(422, "Choose at least one place to search")
    titles = _clean_list(body.title_keywords)
    if not titles:
        raise HTTPException(422, "Add at least one job title to search for")
    s = await ingest.settings_for(session, user.id)
    home = " ".join(body.home_label.split())
    if home != s.home_label or (home and s.home_lat is None):
        s.home_label, s.home_lat, s.home_lon = home, None, None
        if home:
            async with httpx.AsyncClient(timeout=20, headers={"User-Agent": USER_AGENT}) as client:
                hit = await geocode(session, client, home)
            if not hit:
                raise HTTPException(422, f"Couldn't find '{home}' on the map. Try a city name, e.g. 'Ramat Gan'.")
            s.home_lat, s.home_lon = hit[0], hit[1]
    s.work_modes, s.max_km_onsite, s.max_km_hybrid = modes, body.max_km_onsite, body.max_km_hybrid
    s.title_keywords, s.exclude_keywords, s.senior_only = titles, _clean_list(body.exclude_keywords), body.senior_only
    s.sources = sources
    s.ai_grading = body.ai_grading
    await matching.rescore_all(session, user.id)
    await session.commit()
    return await _out(session, s)


class CompanyOut(BaseModel):
    id: int
    ats: str
    slug: str
    name: str
    mine: bool
    ok: bool
    last_error: str


class CompanyIn(BaseModel):
    board: str = Field(min_length=3, max_length=300)  # careers URL or "greenhouse:slug"
    name: str = Field(default="", max_length=200)


@router.get("/companies", response_model=list[CompanyOut])
async def list_companies(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.scalars(select(Company).order_by(Company.name))).all()
    return [
        CompanyOut(id=c.id, ats=c.ats, slug=c.slug, name=c.name, mine=c.added_by == user.id,
                   ok=not c.last_error, last_error=c.last_error)
        for c in rows
    ]


@router.post("/companies", response_model=CompanyOut, status_code=201)
async def add_company(body: CompanyIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    ref = boards.board_from_url(body.board)
    if not ref:
        raise HTTPException(422, "Paste a Greenhouse, Lever or Ashby careers link (e.g. https://jobs.lever.co/company)")
    ats, slug = ref
    if existing := await session.scalar(select(Company).where(Company.ats == ats, Company.slug == slug)):
        raise HTTPException(409, f"{existing.name} is already on the list")
    company = Company(ats=ats, slug=slug, name=body.name.strip() or slug.replace("-", " ").title(), added_by=user.id)
    try:
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": USER_AGENT}) as client:
            postings = await boards.fetch_board(client, company)
    except httpx.HTTPError:
        raise HTTPException(422, f"Couldn't read the {ats.title()} board '{slug}'. Check the link.")
    if not body.name and postings:
        company.name = postings[0].job.company or company.name
    company.last_ok_at = datetime.now(timezone.utc)
    session.add(company)
    await session.commit()
    return CompanyOut(id=company.id, ats=ats, slug=slug, name=company.name, mine=True, ok=True, last_error="")


@router.delete("/companies/{company_id}", status_code=204)
async def delete_company(company_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    company = await session.get(Company, company_id)
    if not company or company.added_by != user.id:
        raise HTTPException(404, "Company not found (you can only remove companies you added)")
    await session.delete(company)
    await session.commit()


class CollectStatus(BaseModel):
    running: bool
    last_started: datetime | None
    last_finished: datetime | None
    last_added: int | None
    last_errors: list[str]
    jsearch_enabled: bool
    jsearch_quota_left: int | None
    last_stats: dict | None = None  # per source: found / added / skipped and why


@router.get("/collect", response_model=CollectStatus)
async def collect_status(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    run = await session.scalar(
        select(CollectionRun).where(CollectionRun.user_id == user.id).order_by(CollectionRun.started_at.desc())
    )
    running = bool(run and run.finished_at is None and _age(run.started_at) < timedelta(minutes=10))
    return CollectStatus(
        running=running,
        last_started=run.started_at if run else None,
        last_finished=run.finished_at if run else None,
        last_added=run.added if run and run.finished_at else None,
        last_errors=[e for e in (run.errors.split("\n") if run and run.errors else []) if e],
        jsearch_enabled=bool(get_settings().jsearch_api_key),
        jsearch_quota_left=await quota_remaining(session),
        last_stats=run.stats if run and run.finished_at else None,
    )


def _age(ts: datetime) -> timedelta:
    return datetime.now(timezone.utc) - (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc))


async def _run_for(user_id: int) -> None:
    await ingest.collect(SessionLocal, [user_id])


@router.post("/collect", status_code=202)
async def collect_now(
    background: BackgroundTasks, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    """Find jobs now for the current user. Company boards are fetched fresh; JSearch uses its shared cache."""
    run = await session.scalar(
        select(CollectionRun).where(CollectionRun.user_id == user.id).order_by(CollectionRun.started_at.desc())
    )
    if run and run.finished_at is None and _age(run.started_at) < timedelta(minutes=10):
        return {"started": False, "detail": "Already searching"}
    if run and _age(run.started_at) < timedelta(minutes=2):
        raise HTTPException(429, "You just searched. Try again in a couple of minutes.")
    background.add_task(_run_for, user.id)
    return {"started": True}
