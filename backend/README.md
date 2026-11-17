# Backend (FastAPI)

Python 3.12, FastAPI, async SQLAlchemy 2 on Postgres, Alembic migrations, arq worker on Redis. What the features do from a user's point of view is in [../docs/workflows.md](../docs/workflows.md); how to run and deploy is in [../docs/operations.md](../docs/operations.md).

## Code map

```
app/
├── main.py              FastAPI app: includes the routers below
├── worker.py            Scheduled tasks (arq): job search 07:00/15:00, Gmail every 10 min, AI grades every 5 min
├── config.py            Settings from .env (pydantic-settings)
├── db.py                Database engine and session
├── models.py            All tables (SQLAlchemy models)
├── schemas.py           Request/response shapes for the job, auth and stats endpoints
│
├── auth.py              /api/auth/*: sign-up, login, Google sign-in, session cookie, current_user
├── api.py               /api/jobs*, /api/stats: list, add, import, edit, notes, delete
├── api_discovery.py     /api/settings, /api/companies, /api/collect: search settings and "Find jobs now"
├── api_profile.py       /api/profile*: CV upload, skills, years; /api/jobs/{id}/match
├── api_gmail.py         /api/gmail/*: connect, check now, recent emails, assign, undo, disconnect
│
├── collectors/          Where jobs are found (each returns Posting objects)
│   ├── __init__.py        Posting = ParsedJob + source + id + url (+ coordinates)
│   ├── boards.py          Greenhouse / Lever / Ashby company boards (public JSON APIs)
│   ├── linkedin.py        LinkedIn public guest search + job pages, polite and cached
│   └── jsearch.py         JSearch (RapidAPI), quota-aware, shared cache
│
├── services/
│   ├── ingest.py          The job search: collect → locate → filter per user → save
│   ├── filters.py         Title matching and location/work-mode decision
│   ├── dedup.py           Keys that recognise the same job from different sources
│   ├── geo.py             Nominatim geocoding (cached), "is it in Israel?", distance
│   ├── importer.py        ParsedJob, HTML → text, JSON-LD parsing, fetch_and_parse() for links
│   ├── ats.py             Greenhouse / Lever / Ashby: job links and JSON → ParsedJob
│   ├── sites/             One module per site without structured data (now: linkedin.py)
│   ├── quality.py         Clean-up + issue list run on every imported/collected job
│   ├── skills.py          Skills taxonomy and text matching, years of experience
│   ├── matching.py        The 0-100 match grade (rule-based)
│   ├── ai_match.py        The AI grade: Claude reads CV + job; replaces the score while current
│   ├── cv.py              Text out of PDF / DOCX / TXT
│   └── gmail/
│       ├── oauth.py         Google OAuth: links, tokens, encryption of the stored token
│       ├── client.py        Minimal Gmail API client and message parsing
│       ├── classify.py      Is it a confirmation / rejection / interview email? (EN + HE rules)
│       ├── match.py         Which job an email is about; company/title guess
│       └── sync.py          The Gmail check: read new mail, act on jobs, label, undo
│
└── tools/diagnose.py    CLI: how a job link imports (see docs/parsers.md)

migrations/versions/     0001…0009, one file per database change
tests/                   pytest; conftest.py gives an in-memory DB and a signed-in client
```

## How a request flows

```
Browser ─► nginx (web) ─► /api/... ─► router function
                                        ├─ current_user (auth.py): reads the jh_session cookie → User, or 401
                                        ├─ get_session (db.py): one AsyncSession per request
                                        ├─ services/...: the actual work
                                        └─ session.commit() → response model (schemas.py / local BaseModel)
```

Long work never blocks a request: **Find jobs now** returns 202 at once and runs in a FastAPI background task. The scheduled runs are in the worker container.

## Rules (also in ../CLAUDE.md)

1. **Every query on user data filters by the signed-in user.** Load jobs with `api._load(session, user, job_id)`, which returns 404 for anyone else's job. Add a cross-user test for every new endpoint (examples: `test_users_cannot_see_each_others_jobs` in `test_auth.py`, `test_other_users_cannot_see_or_touch_your_emails` in `test_gmail.py`).
2. **Every database change needs a migration** in `migrations/versions/`.
3. **Every imported or collected job goes through `quality.assess()`.**
4. **Status changes go through `api._apply_status()`**, so the timeline entry, the applied date and the follow-up are always set the same way. The Gmail sync uses it too.
5. **Re-grade after anything that affects the grade:** `matching.apply_one()` for one job, `matching.rescore_all()` after a profile or settings change.
6. **Network calls never crash a run:** collectors and extractors catch `httpx.HTTPError`, record it (run errors, company `last_error`, Gmail `last_error`) and continue.
7. Secrets only in `.env`. Don't use PowerShell `Set-Content` on source files; it breaks Hebrew text.

## Common changes

### Add an endpoint
1. Add it to the router that fits (`api.py` for jobs, etc.), with `user: User = Depends(current_user)` and `session: AsyncSession = Depends(get_session)`.
2. Filter by `user.id`. Return a Pydantic model.
3. Test it in `tests/`, including the cross-user case. Add the call to `frontend/src/api.ts`.

### Add a job source (collector)
1. `collectors/<name>.py` with an async function returning `list[Posting]`, built from `ParsedJob`. Use `Posting(job, source="<name>", external_id=…, url=…)`.
2. Call it from `ingest._gather_postings` when `"<name>" in boards_wanted`. Catch its network errors into `errors`.
3. Add `"<name>"` to `COLLECT_SOURCES` (`models.py`), a label in `ingest.SOURCE_LABEL`, and an entry in `SOURCES` (`frontend/src/api.ts`).
4. If existing users should get it switched on, write a migration that adds it to `user_settings.sources` (see `0007_linkedin.py`).
5. Tests with fake responses (see `test_linkedin_collect.py`, `test_discovery.py`).

### Fix or add a job-link site
Follow [../docs/parsers.md](../docs/parsers.md).

### Add a skill
Add a `_s("Name", "group", r"alias", …)` line to `SKILLS` in `services/skills.py`. Aliases are regexes matched case-insensitively. A plain alias must stand alone as a word; start an alias with `\b` or `(` to write the boundaries yourself. Skills in the same group count as "similar". Add a case to `tests/test_matching.py`. Saving Settings re-grades your jobs with the new skill.

### Change how emails are recognised
`services/gmail/classify.py`: add English and Hebrew patterns to `_REJECTION`, `_INVITE` or `_CONFIRMATION`. Add the real-life sentence (with made-up names) to the `test_classify` table in `tests/test_gmail.py`, plus a "must not match" case, since false positives change job statuses.

### Add a database column
1. Add it to the model in `models.py`.
2. `migrations/versions/0010_<what>.py` with `revision = "0010"`, `down_revision = "0009"`, using `op.add_column` / `op.drop_column`.
3. Rebuild: the API applies it on start.

## Performance notes

- **Match grades:** `skills.job_skills()` is the expensive part (~85 regexes over a long description). Each skill's aliases share one compiled boundary check, and results are cached per description text (`lru_cache`, per process). Re-grading 64 jobs takes ~1.9 s the first time and ~0.2 s after that (was 2.7 s every time).
- **Job list:** `GET /api/jobs` loads only the card columns (`load_only`), not descriptions or match details.
- **External sources:** JSearch results (20 h), LinkedIn job pages (30 days) and geocoding (forever) are cached in Postgres and shared by all users, to stay within free quotas and be polite to LinkedIn and OpenStreetMap.
