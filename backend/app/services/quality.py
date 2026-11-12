"""Checks and cleanups applied to every imported job, whatever site it came from.

When a site changes its pages or sends only a preview, these checks catch it, so the job is
flagged instead of silently saved with junk (e.g. company = "LinkedIn Jobs", title with "| LinkedIn").
"""

import re

from app.models import WorkMode
from app.services.importer import ParsedJob, guess_work_mode

# Job sites and boards: never a real employer name
SITE_NAMES = {
    "linkedin", "linkedin jobs", "indeed", "glassdoor", "google", "google jobs", "alljobs", "drushim",
    "jobmaster", "greenhouse", "lever", "ashby", "comeet", "workday", "wellfound", "angellist",
    "monster", "ziprecruiter", "smartrecruiters", "jobs", "careers",
}
# " | LinkedIn", " - Glassdoor", " – Indeed.com" at the end of page titles
_SITE_SUFFIX = re.compile(
    r"\s*[|\-–—]\s*(?:" + "|".join(sorted((re.escape(s) for s in SITE_NAMES), key=len, reverse=True)) + r")(?:\.com)?(?: jobs)?\s*$",
    re.I,
)
# "Senior Data Engineer at DoorLoop — Tel Aviv, Israel" (preview/og:title style)
_TITLE_AT = re.compile(r"^(?P<title>.+?)\s+at\s+(?P<company>[^—–|]+?)(?:\s*[—–|]\s*(?P<location>.+))?$", re.I)
_HIRING = re.compile(r"^(?P<company>.+?)\s+(?:is\s+)?hiring\s+(?:an?\s+)?(?P<title>.+?)(?:\s+in\s+(?P<location>.+))?$", re.I)

MIN_DESCRIPTION = 200


def _is_site_name(name: str) -> bool:
    n = re.sub(r"\.com$", "", (name or "").strip().lower())
    return n in SITE_NAMES or n.endswith(" careers") and n[:-8] in SITE_NAMES


def clean(job: ParsedJob) -> ParsedJob:
    """Fix the common, safe-to-fix problems in place."""
    job.title = _SITE_SUFFIX.sub("", job.title.strip())
    if _is_site_name(job.company):
        job.company = ""
    if not job.company:
        for pattern in (_TITLE_AT, _HIRING):
            if m := pattern.match(job.title):
                job.title = m.group("title").strip()
                job.company = m.group("company").strip()
                if not job.location and m.group("location"):
                    job.location = m.group("location").strip()
                break
    job.title = re.sub(r"\s+", " ", job.title)
    # Work mode is often mentioned only near the end of a long description ("Hybrid, 3 days in office")
    if job.work_mode == WorkMode.unknown:
        job.work_mode = guess_work_mode(job.title, job.location, job.description)
    return job


def issues(job: ParsedJob) -> list[str]:
    """Human-readable problems that remain after cleaning. Empty list = looks good."""
    found = []
    if not job.title or job.title.lower().startswith("imported job"):
        found.append("Job title not found")
    if not job.company:
        found.append("Company not found")
    if not job.location:
        found.append("Location not found")
    if len(job.description) < MIN_DESCRIPTION:
        found.append("Description missing or too short")
    return found


def assess(job: ParsedJob) -> tuple[ParsedJob, list[str]]:
    job = clean(job)
    problems = issues(job)
    # Missing location alone is common (remote roles) and doesn't make the import "incomplete"
    job.complete = job.complete and not [p for p in problems if not p.startswith("Location")]
    return job, problems
