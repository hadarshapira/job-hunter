"""AI match grade: Claude reads the user's CV and the job and grades the fit like a recruiter would.

The rule-based grade (matching.py) is instant and always there; this one is slower (seconds,
costs a little per job) and much closer to human judgment. It runs in the worker for every
job of users who switched it on, and on demand from the job page.

A grade is stored on the job (job.ai_match) with a fingerprint of everything that went into
the prompt (CV, preferences, the job text, model, prompt version). When any of those change the
fingerprint no longer matches, the job falls back to the rule-based grade and is graded again on
the next run. So each job costs one call, and again only when its inputs change.
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Literal

import anthropic
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.models import Job, Status, UserProfile, UserSettings

log = logging.getLogger(__name__)

PROMPT_VERSION = 1
SKIP_STATUSES = (Status.rejected, Status.archived, Status.ghosted)  # no point grading these
RUN_LIMIT = 40  # jobs per scheduled run; the rest wait for the next run
PARALLEL = 4

INSTRUCTIONS = """\
You grade how well one job fits one candidate, the way an honest, experienced tech recruiter in \
Israel would. The candidate reads your grade to decide where to spend their time applying, so be \
realistic, not encouraging.

How to judge:
- Start from the core of the role: what this person would do day to day. Keyword overlap means \
little if the core differs from the candidate's direction (for example an analyst, data scientist, \
ML researcher, people-manager-only, backend-generalist or DevOps role for a data engineer).
- Check the must-haves against what the CV shows the candidate actually did, and how deeply. A tool \
named once in a skills list is weaker evidence than years of hands-on work with it.
- Alternatives such as "Airflow, Dagster or Prefect" are one requirement: any one of them is enough.
- Close equivalents count partly (AWS vs GCP, Kafka vs Kinesis, Snowflake vs BigQuery).
- Nice-to-haves move the grade only a little.
- Seniority and scope: years, ownership, leading others, compared with what the job expects. \
Being somewhat more senior than the role is a small minus; clearly less senior is a big one.
- Domain or industry matters only when the job says it does.
- The candidate's notes (if any) are true and come first: follow them about what to count, what \
to ignore and which roles they want. A role they say they don't want is a poor fit whatever the skills.
- Grade only what differs between jobs. Don't repeat the same point (such as a career break) in \
every grade.
- The job already passed the candidate's location filter. Mention location only if it's a real \
problem (for example on-site in another country).

Score bands. Use the whole range:
- 85-100 strong: meets nearly all must-haves in the core of the role. Apply now.
- 70-84 good: right kind of role, one or two gaps that are easy to explain or learn.
- 50-69 stretch: possible, but important must-haves are missing or the role is only partly the \
candidate's direction.
- 0-49 poor: a different role, a big seniority gap, or a missing must-have that is a deal-breaker.

Write in English, plainly. summary: one or two sentences that explain the grade. strengths and \
gaps: up to 5 each, the ones that matter most first, each under 15 words, specific to this job \
and CV (no generic advice). dealbreakers: only true blockers (a hard requirement the candidate \
clearly lacks, the wrong role, a security clearance, relocation); usually empty.
"""


class AIGrade(BaseModel):
    score: int
    verdict: Literal["strong", "good", "stretch", "poor"]
    summary: str
    strengths: list[str]
    gaps: list[str]
    dealbreakers: list[str]


class GradeError(Exception):
    """The grade can't be made for this job (refused, unreadable answer). Stored so it isn't retried."""


def available() -> bool:
    return bool(get_settings().anthropic_api_key)


def ready(profile: UserProfile | None, s: UserSettings | None) -> bool:
    """Can this user's jobs get an AI grade? (Server key set, switched on, CV uploaded.)"""
    return available() and bool(s and s.ai_grading) and bool(profile and profile.cv_text.strip())


def _preferences(profile: UserProfile, s: UserSettings | None) -> str:
    lines = []
    if profile.years_experience is not None:
        lines.append(f"Years of experience (the candidate's own figure): {profile.years_experience}")
    if s:
        lines.append(f"Job titles they're looking for: {', '.join(s.title_keywords)}")
        if s.senior_only:
            lines.append("Wants senior-level roles only")
        lines.append(f"Work modes they accept: {', '.join(s.work_modes)}")
        if s.home_label:
            lines.append(f"Lives in {s.home_label}; on-site up to {s.max_km_onsite} km, hybrid up to {s.max_km_hybrid} km")
    return "\n".join(lines)


def _system(profile: UserProfile, s: UserSettings | None) -> str:
    # Same text for every job of the user, so it's cached between calls (cheaper and faster).
    notes = (profile.ai_notes or "").strip()
    return (
        f"{INSTRUCTIONS}\n<candidate_cv>\n{profile.cv_text.strip()}\n</candidate_cv>\n\n"
        f"<candidate_preferences>\n{_preferences(profile, s)}\n</candidate_preferences>"
        + (f"\n\n<candidate_notes>\n{notes}\n</candidate_notes>" if notes else "")
    )


def _job_text(job: Job) -> str:
    mode = {"remote": "Remote", "hybrid": "Hybrid", "onsite": "On-site"}.get(job.work_mode, "not stated")
    where = job.location or "not stated"
    if job.distance_km is not None:
        where += f" ({round(job.distance_km)} km from the candidate's home)"
    return (
        f"Grade this job for the candidate.\n\n<job>\nTitle: {job.title}\nCompany: {job.company or 'not stated'}\n"
        f"Location: {where}\nWork mode: {mode}\n\n{job.description.strip() or '(no description)'}\n</job>"
    )


def fingerprint(job: Job, profile: UserProfile, s: UserSettings | None) -> str:
    cfg = get_settings()
    parts = [PROMPT_VERSION, cfg.ai_model, cfg.ai_effort, _system(profile, s), _job_text(job)]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:24]


def is_current(job: Job, profile: UserProfile | None, s: UserSettings | None) -> bool:
    """Does the job's stored AI grade still match the CV, preferences and job text?"""
    a = job.ai_match
    return bool(a and profile and a.get("score") is not None and a.get("key") == fingerprint(job, profile, s))


_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=get_settings().anthropic_api_key, timeout=120, max_retries=3)
    return _client


async def _call(system: str, user_text: str) -> AIGrade:
    """One request to Claude. Raises GradeError when no usable grade comes back."""
    cfg = get_settings()
    resp = await _get_client().beta.messages.parse(
        model=cfg.ai_model,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user_text}],
        output_format=AIGrade,
        output_config={"effort": cfg.ai_effort},
        cache_control={"type": "ephemeral"},
        # If the model declines, the API retries on a fallback model inside the same call
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if resp.stop_reason == "refusal":
        raise GradeError("The AI declined to grade this job.")
    if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
        raise GradeError("The AI's answer couldn't be read.")
    u = resp.usage
    log.info("ai_match model=%s in=%s cache_write=%s cached=%s out=%s", resp.model, u.input_tokens,
             u.cache_creation_input_tokens, u.cache_read_input_tokens, u.output_tokens)
    return resp.parsed_output


async def grade(job: Job, profile: UserProfile, s: UserSettings | None) -> dict:
    """Grade one job and return what's stored in job.ai_match. API errors (network, rate limit,
    bad key) are raised; a refused or unreadable answer is stored as an error instead."""
    key = fingerprint(job, profile, s)
    now = datetime.now(timezone.utc).isoformat()
    try:
        g = await _call(_system(profile, s), _job_text(job))
    except GradeError as exc:
        return {"key": key, "score": None, "error": str(exc), "graded_at": now}
    return {
        "key": key,
        "score": max(0, min(100, g.score)),
        "verdict": g.verdict,
        "summary": g.summary.strip(),
        "strengths": g.strengths[:6],
        "gaps": g.gaps[:6],
        "dealbreakers": g.dealbreakers[:4],
        "model": get_settings().ai_model,
        "graded_at": now,
    }


def store(job: Job, result: dict) -> None:
    job.ai_match = {**result, "stale": False}
    if result.get("score") is not None:
        job.match_score = result["score"]


async def grade_pending(maker: async_sessionmaker, limit: int = RUN_LIMIT) -> dict:
    """Grade jobs whose AI grade is missing or out of date, for every user who has it switched on."""
    if not available():
        return {"graded": 0}
    graded = failed = 0
    async with maker() as session:
        settings = (await session.scalars(select(UserSettings).where(UserSettings.ai_grading.is_(True)))).all()
        for s in settings:
            profile = await session.get(UserProfile, s.user_id)
            if not ready(profile, s):
                continue
            jobs = (await session.scalars(
                select(Job).where(Job.user_id == s.user_id, Job.status.not_in(SKIP_STATUSES))
                .order_by(Job.created_at.desc())
            )).all()
            todo = [j for j in jobs if (j.ai_match or {}).get("key") != fingerprint(j, profile, s)][: limit - graded]
            if not todo:
                continue
            sem = asyncio.Semaphore(PARALLEL)

            async def one(job: Job):
                async with sem:
                    return await grade(job, profile, s)

            results = await asyncio.gather(*(one(j) for j in todo), return_exceptions=True)
            for job, r in zip(todo, results):
                if isinstance(r, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
                    log.error("ai_match: the Anthropic API key was rejected: %s", r)
                    await session.commit()
                    return {"graded": graded, "failed": failed + 1, "error": "API key rejected"}
                if isinstance(r, BaseException):
                    log.warning("ai_match job=%s failed: %r", job.id, r)
                    failed += 1  # network / rate limit: try again next run
                    continue
                store(job, r)
                graded += 1
            await session.commit()
            if graded >= limit:
                break
    if graded or failed:
        log.info("ai_match graded=%d failed=%d", graded, failed)
    return {"graded": graded, "failed": failed}
