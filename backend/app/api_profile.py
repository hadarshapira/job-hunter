"""The user's profile (CV, skills, years) and job match grades."""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import _load
from app.auth import current_user
from app.db import get_session
from app.models import User, UserProfile
from app.schemas import JobOut
from app.services import matching
from app.services import skills as sk
from app.services.cv import CVError, extract_text

router = APIRouter(prefix="/api")
MAX_CV_BYTES = 5 * 1024 * 1024


class ProfileIn(BaseModel):
    skills: list[str] = Field(default_factory=list, max_length=150)
    years_experience: int | None = Field(default=None, ge=0, le=50)


class ProfileOut(ProfileIn):
    cv_filename: str = ""
    cv_uploaded_at: datetime | None = None
    cv_years_guess: int | None = None  # what the CV's date ranges suggest
    known_skills: list[str] = []  # taxonomy, for suggestions in the editor
    rescored: int | None = None


async def _profile(session: AsyncSession, user_id: int) -> UserProfile:
    p = await session.get(UserProfile, user_id)
    if p is None:
        p = UserProfile(user_id=user_id, skills=[])
        session.add(p)
        await session.flush()
    return p


def _out(p: UserProfile, rescored: int | None = None) -> ProfileOut:
    return ProfileOut(
        skills=p.skills or [],
        years_experience=p.years_experience,
        cv_filename=p.cv_filename,
        cv_uploaded_at=p.cv_uploaded_at,
        cv_years_guess=sk.cv_years(p.cv_text, date.today().year) if p.cv_text else None,
        known_skills=[s.name for s in sk.SKILLS],
        rescored=rescored,
    )


def _clean_skills(items: list[str]) -> list[str]:
    seen, out = set(), []
    for raw in items:
        name = sk.canonical(raw)[:60]
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


@router.get("/profile", response_model=ProfileOut)
async def get_profile(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    p = await _profile(session, user.id)
    await session.commit()
    return _out(p)


@router.put("/profile", response_model=ProfileOut)
async def put_profile(body: ProfileIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    p = await _profile(session, user.id)
    p.skills = _clean_skills(body.skills)
    p.years_experience = body.years_experience
    n = await matching.rescore_all(session, user.id)
    await session.commit()
    return _out(p, n)


@router.post("/profile/cv", response_model=ProfileOut)
async def upload_cv(
    file: UploadFile = File(...), user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    """Read a CV, replace the skills list with the skills found in it, and suggest years of experience."""
    data = await file.read(MAX_CV_BYTES + 1)
    if len(data) > MAX_CV_BYTES:
        raise HTTPException(413, "That file is over 5 MB.")
    try:
        text = extract_text(file.filename or "", data)
    except CVError as exc:
        raise HTTPException(422, str(exc))
    p = await _profile(session, user.id)
    p.cv_text, p.cv_filename = text, (file.filename or "cv")[:255]
    p.cv_uploaded_at = datetime.now(timezone.utc)
    p.skills = sk.find_skills(text)
    if p.years_experience is None:
        p.years_experience = sk.cv_years(text, date.today().year)
    n = await matching.rescore_all(session, user.id)
    await session.commit()
    return _out(p, n)


@router.post("/jobs/{job_id}/match", response_model=JobOut)
async def rematch_job(job_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Recalculate one job's match grade."""
    job = await _load(session, user, job_id)
    await matching.apply_one(session, job)
    await session.commit()
    return await _load(session, user, job_id)
