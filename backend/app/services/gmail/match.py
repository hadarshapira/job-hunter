"""Which of the user's jobs an email is about, and the company/title it names (to add a new job)."""

import re
from dataclasses import dataclass

from app.models import Job, Status
from app.services.dedup import _norm, company_key
from app.services.gmail.classify import CONFIRMATION, INTERVIEW, REJECTION
from app.services.gmail.client import Mail

# Senders that send mail on behalf of many companies: their domain says nothing about the company
ATS_DOMAINS = ("greenhouse.io", "lever.co", "ashbyhq.com", "comeet.co", "comeet.com", "myworkday.com", "workday.com",
               "smartrecruiters.com", "linkedin.com", "indeed.com", "glassdoor.com", "breezy.hr", "workable.com",
               "bamboohr.com", "icims.com", "jobvite.com", "teamtailor.com", "hibob.com", "recruitee.com",
               "gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "taleo.net", "successfactors.com", "personio.de")
_GENERIC_NAME = re.compile(
    r"\b(careers?|jobs?|recruit(ing|ment|er|ers)?|talent( acquisition)?|hiring|team|hr|people|no-?reply|notifications?|"
    r"via|greenhouse|lever|ashby|comeet|workday|linkedin|the)\b|[-|@•]", re.I)

# Statuses an email of each kind most likely refers to, to choose between two jobs at one company
_LIKELY = {
    CONFIRMATION: {Status.new, Status.saved},
    REJECTION: {Status.applied, Status.screening, Status.interview},
    INTERVIEW: {Status.applied, Status.screening},
}

_COMPANY_IN_TEXT = [
    re.compile(r"application was sent to (?P<c>[^\n,.!]{2,60})", re.I),  # LinkedIn Easy Apply
    re.compile(r"(?:applying|application|your interest) (?:to|at|with|in(?: joining)?) (?P<c>[A-Z][\w&.'\- ]{1,50}?)(?:[,.!\n]| for | and | -|$)"),
    re.compile(r"(?:position|role|job) (?:at|with) (?P<c>[A-Z][\w&.'\- ]{1,50}?)(?:[,.!\n]| and | -|$)"),
    re.compile(r"(?:the|our) (?P<c>[A-Z][\w&.'\-]{1,30}(?: [A-Z][\w&.'\-]{1,30})?) (?:team|recruiting team|talent team)\b"),
]
_TITLE_IN_TEXT = [
    re.compile(r"(?:for|to) (?:the|our) (?P<t>[^\n,.!]{3,80}?) (?:position|role|job|opening)\b", re.I),
    re.compile(r"(?:position|role) of (?P<t>[^\n,.!]{3,80}?)(?: at |[,.!\n]|$)", re.I),
    re.compile(r"application for (?:the )?(?P<t>[^\n,.!]{3,80}?)(?: at | with | position| role|[,.!\n]|$)", re.I),
    re.compile(r"(?:למשרת|לתפקיד) (?P<t>[^\n,.!]{3,60})"),
]


@dataclass
class Guess:
    company: str = ""
    title: str = ""


def _contains(haystack: str, needle: str) -> bool:
    return bool(needle) and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None


def _domain_names(domain: str) -> list[str]:
    if not domain or any(domain == d or domain.endswith("." + d) for d in ATS_DOMAINS):
        return []
    parts = domain.split(".")
    # careers.wix.com -> wix ; mail.monday.co.il -> monday
    core = [p for p in parts[:-1] if p not in ("co", "com", "org", "net", "ac", "gov", "mail", "careers", "jobs", "email", "hr", "em", "info", "notifications")]
    return [_norm(p) for p in core]


def score(mail: Mail, job: Job, linked_thread_jobs: set[int]) -> int:
    """How strongly the email points to this job (0 = not at all)."""
    points = 0
    if job.id in linked_thread_jobs:
        points += 10
    key = company_key(job.company)
    if len(key) >= 2:
        subject, body, name = _norm(mail.subject), _norm(mail.text[:4000]), _norm(mail.sender_name)
        first_word = key.split()[0]
        if key in _domain_names(mail.sender_domain) or (len(first_word) >= 4 and first_word in _domain_names(mail.sender_domain)):
            points += 3
        if _contains(name, key):
            points += 3
        if _contains(subject, key):
            points += 3
        elif _contains(body, key):
            points += 2
    if points and job.title:
        title = _norm(job.title)
        text = _norm(f"{mail.subject} {mail.text[:4000]}")
        if _contains(text, title):
            points += 3
        else:
            words = {w for w in title.split() if len(w) > 2 and w not in ("senior", "junior", "and", "the")}
            if words and len(words & set(text.split())) / len(words) >= 0.75:
                points += 1
    return points


def best_job(mail: Mail, kind: str, jobs: list[Job], linked_thread_jobs: set[int]) -> Job | None:
    """The one job the email is clearly about, or None when it's unclear."""
    scored = sorted(((score(mail, j, linked_thread_jobs), j) for j in jobs), key=lambda x: -x[0])
    scored = [(s, j) for s, j in scored if s >= 3]
    if not scored:
        return None
    top = scored[0][0]
    tied = [j for s, j in scored if s == top]
    if len(tied) == 1:
        if len(scored) == 1 or top - scored[1][0] >= 2 or top >= 10:
            return tied[0]
        tied = [j for s, j in scored if s >= top - 1]
    likely = [j for j in tied if j.status in _LIKELY[kind]]
    return likely[0] if len(likely) == 1 else None


def _clean_company(c: str) -> str:
    c = re.sub(r"\s+", " ", c).strip(" -:'\"")
    return "" if len(c) < 2 or len(c) > 60 else c


def guess(mail: Mail) -> Guess:
    """Company and job title named in the email (for adding a job you applied to elsewhere)."""
    g = Guess()
    for text in (mail.subject, mail.text[:3000]):
        for rx in _COMPANY_IN_TEXT:
            if not g.company and (m := rx.search(text)):
                g.company = _clean_company(m.group("c"))
        for rx in _TITLE_IN_TEXT:
            if not g.title and (m := rx.search(text)):
                t = m.group("t").strip(" -:'\"")
                if 2 <= len(t.split()) <= 10 or re.search(r"[֐-׿]", t):
                    g.title = t
    if not g.company and (names := _domain_names(mail.sender_domain)):
        g.company = names[-1].title()  # recruiter@wix.com -> Wix
    personal = mail.sender_domain in ("gmail.com", "outlook.com", "hotmail.com", "yahoo.com")
    if not g.company and not personal:
        # "Wix Careers <no-reply@greenhouse.io>" -> Wix (a person's name from a personal mailbox says nothing)
        name = _clean_company(_GENERIC_NAME.sub(" ", mail.sender_name))
        if name and not re.search(r"\b(no ?reply|support)\b", name, re.I):
            g.company = name
    return g
