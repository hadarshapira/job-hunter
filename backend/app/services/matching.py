"""Match grade (0-100) for a job against the user's profile.

Rule-based and fast (milliseconds per job), so every job is graded as soon as it's added.
The grade is a weighted mix of five parts; a part with nothing to judge (e.g. the job states
no years) is left out and the others are re-weighted.
"""

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, UserProfile, UserSettings
from app.services import skills as sk
from app.services.filters import location_decision, title_matches

VERSION = 1
WEIGHTS = {"skills": 50, "experience": 15, "seniority": 15, "role": 10, "location": 10}
NICE_WEIGHT = 0.35  # a nice-to-have skill counts this much compared with a required one
SIMILAR_CREDIT = 0.5

# Title level -> (min, max) years that usually fit it
_LEVELS = [
    ("junior", re.compile(r"\b(junior|jr\.?|entry|graduate|intern)\b", re.I), (0, 3)),
    ("staff / principal", re.compile(r"\b(staff|principal|architect|distinguished)\b", re.I), (8, 40)),
    ("lead / manager", re.compile(r"\b(lead|head|manager|director|vp)\b", re.I), (6, 40)),
    ("senior", re.compile(r"\b(senior|sr\.?|expert)\b", re.I), (4, 14)),
]


def title_level(title: str) -> tuple[str, tuple[int, int]]:
    for name, rx, span in _LEVELS:
        if rx.search(title or ""):
            return name, span
    return "mid-level", (2, 8)


def _skills_part(job_needs: dict[str, str], mine: list[str]) -> tuple[dict | None, list[dict]]:
    have = {s.lower() for s in mine}
    my_groups: dict[str, list[str]] = {}
    for s in mine:
        if g := sk.group_of(s):
            my_groups.setdefault(g, []).append(s)

    rows, got, total = [], 0.0, 0.0
    for name, need in job_needs.items():
        w = 1.0 if need == "required" else NICE_WEIGHT
        total += w
        if name.lower() in have:
            status, via, credit = "have", None, 1.0
        elif (g := sk.group_of(name)) and my_groups.get(g):
            status, via, credit = "similar", ", ".join(my_groups[g][:2]), SIMILAR_CREDIT
        else:
            status, via, credit = "missing", None, 0.0
        got += w * credit
        rows.append({"skill": name, "need": need, "status": status, "via": via})

    order = {"required": 0, "nice": 1}
    status_order = {"missing": 0, "similar": 1, "have": 2}
    rows.sort(key=lambda r: (order[r["need"]], status_order[r["status"]], r["skill"]))
    if not total:
        return None, rows
    req = [r for r in rows if r["need"] == "required"]
    detail = (
        f"{sum(r['status'] == 'have' for r in req)} of {len(req)} required skills"
        + (f", {sum(r['status'] == 'similar' for r in req)} similar" if any(r["status"] == "similar" for r in req) else "")
        if req else f"{sum(r['status'] == 'have' for r in rows)} of {len(rows)} nice-to-have skills"
    )
    return {"score": round(100 * got / total), "detail": detail}, rows


def _experience_part(required: int | None, mine: int | None) -> dict | None:
    if required is None:
        return None
    if mine is None:
        return {"score": None, "detail": f"Asks for {required}+ years. Add your years in Settings."}
    gap = required - mine
    score = 100 if gap <= 0 else {1: 70, 2: 45}.get(gap, 15)
    return {"score": score, "detail": f"Asks for {required}+ years, you have {mine}"}


def _seniority_part(title: str, mine: int | None) -> dict | None:
    if mine is None:
        return None
    level, (lo, hi) = title_level(title)
    if lo <= mine <= hi:
        score = 100
    elif mine < lo:
        score = {1: 70, 2: 45}.get(lo - mine, 20)
    else:
        score = 80 if mine - hi <= 3 else 60  # more senior than the role: still possible
    return {"score": score, "detail": f"{level.capitalize()} role (usually {lo}-{hi if hi < 40 else '+'} years)".replace("-+", "+")}


def _role_part(title: str, s: UserSettings | None) -> dict | None:
    if not s or not s.title_keywords:
        return None
    if title_matches(title, s.title_keywords, [], False):
        return {"score": 100, "detail": "Title matches what you're looking for"}
    words = set(re.findall(r"\w+", title.lower()))
    if any(w in words for kw in s.title_keywords for w in kw.lower().split() if len(w) > 3):
        return {"score": 60, "detail": "Title is close to what you're looking for"}
    return {"score": 25, "detail": "Title isn't one you're looking for"}


def _location_part(job: Job, s: UserSettings | None) -> dict | None:
    if not s:
        return None
    d = location_decision(s, job.work_mode, job.distance_km)
    mode = {"remote": "Remote", "hybrid": "Hybrid", "onsite": "On-site"}.get(job.work_mode, "Work mode unknown")
    if not d.ok:
        return {"score": 20, "detail": f"{mode}: {d.reason}"}
    if job.work_mode == "remote":
        return {"score": 100, "detail": "Remote"}
    if job.distance_km is None or s.home_lat is None:
        return {"score": 70, "detail": f"{mode}, distance unknown"}
    limit = s.max_km_onsite if job.work_mode == "onsite" else s.max_km_hybrid
    ratio = job.distance_km / max(limit, 1)
    # Full marks up to half your max distance, then down to 70 at the limit (never below 60 here,
    # since jobs past the limit were already handled above)
    score = 100 if ratio <= 0.5 else round(100 - 60 * (ratio - 0.5))
    return {"score": max(score, 60), "detail": f"{mode}, {round(job.distance_km)} km from home"}


def score_job(job: Job, profile: UserProfile | None, s: UserSettings | None) -> dict | None:
    """Full match result for a job, or None when the user has no profile yet."""
    if not profile or not (profile.skills or profile.years_experience):
        return None
    needs = sk.job_skills(f"{job.title}\n{job.description}")
    skills_part, rows = _skills_part(needs, profile.skills or [])
    years_req = sk.required_years(job.description)
    parts = {
        "skills": skills_part,
        "experience": _experience_part(years_req, profile.years_experience),
        "seniority": _seniority_part(job.title, profile.years_experience),
        "role": _role_part(job.title, s),
        "location": _location_part(job, s),
    }
    labels = {"skills": "Skills", "experience": "Experience", "seniority": "Seniority", "role": "Role", "location": "Location"}
    scored = {k: p for k, p in parts.items() if p and p["score"] is not None}
    total_w = sum(WEIGHTS[k] for k in scored)
    score = round(sum(WEIGHTS[k] * p["score"] for k, p in scored.items()) / total_w) if total_w else None
    notes = []
    if skills_part is None:
        notes.append("The job description names no skills we recognise, so the grade leans on title, experience and location.")
    if len((job.description or "").strip()) < 200:
        notes.append("The job description is short or missing; the grade is a rough guess.")
    return {
        "version": VERSION,
        "score": score,
        "parts": [
            {"key": k, "label": labels[k], "weight": WEIGHTS[k], **p}
            for k, p in parts.items() if p
        ],
        "skills": rows,
        "required_years": years_req,
        "your_years": profile.years_experience,
        "notes": notes,
    }


def apply(job: Job, profile: UserProfile | None, s: UserSettings | None) -> None:
    result = score_job(job, profile, s)
    job.match = result
    job.match_score = result["score"] if result else None
    job.match_at = datetime.now(timezone.utc) if result else None


async def context(session: AsyncSession, user_id: int) -> tuple[UserProfile | None, UserSettings | None]:
    return await session.get(UserProfile, user_id), await session.get(UserSettings, user_id)


async def apply_one(session: AsyncSession, job: Job) -> None:
    apply(job, *await context(session, job.user_id))


async def rescore_all(session: AsyncSession, user_id: int) -> int:
    """Re-grade every job of one user (after the profile or settings change). Returns how many."""
    profile, s = await context(session, user_id)
    jobs = (await session.scalars(select(Job).where(Job.user_id == user_id))).all()
    for job in jobs:
        apply(job, profile, s)
    return len(jobs)
