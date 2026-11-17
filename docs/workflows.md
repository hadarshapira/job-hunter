# Workflows: what happens, step by step

This document follows each feature from the button you press to the rows saved in the database. File names point to where the logic lives (all under `backend/app/` unless shown otherwise).

- [1. Signing in](#1-signing-in)
- [2. Finding jobs automatically](#2-finding-jobs-automatically)
- [3. Adding a job from a link](#3-adding-a-job-from-a-link)
- [4. The match grade](#4-the-match-grade)
- [5. Tracking an application](#5-tracking-an-application)
- [6. Gmail: updating jobs from your email](#6-gmail-updating-jobs-from-your-email)
- [7. What runs on a schedule](#7-what-runs-on-a-schedule)

---

## 1. Signing in

`auth.py`

1. The sign-in screen asks `GET /api/auth/config` which options to show (Google button, sign-up allowed).
2. **Email + password:** `POST /api/auth/signup` or `/login`. Passwords are hashed with Argon2. A wrong email takes as long as a wrong password, so nobody can probe which emails exist.
3. **Google:** the Google button returns a signed ID token, and `POST /api/auth/google` checks it with Google. If an email account already exists, Google is linked to it. If that account's email was never verified, its password is removed, so whoever registered the address first can't keep access.
4. On success the API sets the `jh_session` cookie: signed, HTTP-only, valid 30 days.
5. Every other endpoint gets the user from that cookie (`current_user`). **Every query filters by that user**, so asking for someone else's job id returns 404.
6. More than 10 failed attempts from one IP in 5 minutes → "Too many attempts" for 5 minutes.

## 2. Finding jobs automatically

`services/ingest.py`, `collectors/`, `services/filters.py`, `services/geo.py`

### When it runs
- **Scheduled:** 07:00 and 15:00 Israel time, for all users at once (`worker.py`).
- **Find jobs now** (Jobs page → *New for you*): `POST /api/find-jobs` runs it for you only, in the background. While a search is running you can't start another (a run older than 10 minutes counts as stuck), and there's a 2-minute pause between searches. The page checks `GET /api/find-jobs` every 3 seconds until it finishes. (Not `/api/collect`: ad blockers block that path as Google Analytics.)

### Step by step
1. **Start:** a `collection_runs` row is created for each user. Each user's search settings are loaded, and defaults are created for new users.
2. **Decide which sources to ask:** the sources at least one user has switched on in *Settings → Where to search*.
3. **Collect postings** (shared by all users, so each source is asked once):

   | Source | How | Limits |
   |---|---|---|
   | Greenhouse / Lever / Ashby (`collectors/boards.py`) | Public JSON API of every board in the `companies` table (24 starter companies, plus any a user adds). Only jobs whose location is in Israel are kept. | 6 boards at a time. A failing board is recorded on that company and shown in Settings. |
   | LinkedIn (`collectors/linkedin.py`) | Public guest search for each title phrase, past week, Israel: up to 8 pages, plus 3 pages each filtered to Remote and Hybrid (that's how work mode is known). Then the full job page is read for jobs whose title fits someone's search. | Up to 6 phrases, 1-2 s between requests, at most 80 job pages per run (the rest are read next run). Job pages are cached for 30 days in `posting_cache`. If LinkedIn starts refusing (HTTP 429/999), it stops and keeps what it has. |
   | JSearch (`collectors/jsearch.py`) | Google for Jobs via RapidAPI: "`<phrase>` in Israel", past week | Free plan: 200 requests/month for the whole app. Top 4 phrases only, results cached 20 h (`search_cache`), and it stops when 15 or fewer requests are left. Needs `JSEARCH_API_KEY`. |

4. **Find each job on the map:** the job's city is geocoded with OpenStreetMap Nominatim, unless the job is remote or the location is only a region like "Central District". Results are cached forever in `geo_cache`, and Nominatim is called at most once per second.
5. **Filter for each user** (`_add_for_user`). Each posting passes these checks in order; the first one it fails is counted in the **search report**:

   | Check | Kept when |
   |---|---|
   | Source | the source is on in your settings |
   | Already have | not already in your jobs (same `source:id`) |
   | Title (`filters.title_matches`) | every word of one of your title phrases appears, in any order. "data engineer" matches "Engineer, Data Platform" and "מהנדס/ת דאטה". Word forms count ("engineer" ~ "engineering"), longer words don't ("data" ≠ "database"). No "skip" word may appear, and with *senior only* the title must be senior / lead / staff / principal… |
   | Location (`filters.location_decision`) | remote: you accept remote. On-site / hybrid / unknown: you accept that mode, and the distance from home is within your limit. Unknown distance is kept, so a good job isn't lost. |
   | Duplicate | not the same job from another source: same company + title + city, or same company + title within 10 km (catches "Tel Aviv-Yafo" vs "תל אביב -יפו" and "Wix.com, Inc." vs "Wix") |

6. **Save:** the job is added with status **new**, a "Found on LinkedIn" timeline entry, the distance from home, and its match grade (section 4).
7. **Finish:** the run records how many jobs were added, any source errors, and the per-source report shown under *Last search report*.

### Tuning it (Settings page)
- More jobs: add title phrases, raise the distance limits, switch on more sources, add company boards.
- Fewer bad jobs: add "skip" words (default: junior, intern, student, graduate), or switch on *senior only*.
- Saving settings re-grades all your jobs straight away.

## 3. Adding a job from a link

`api.py: import_job`, `services/importer.py`, `services/ats.py`, `services/sites/`, `services/quality.py`. To fix a site that imports badly, see [parsers.md](parsers.md).

1. **Add** page → paste a link, or on Android **Share → JobHunter** from LinkedIn or Chrome.
2. `POST /api/jobs/import`. If you already have a job with that exact link, it opens that job instead.
3. **Read the page:** the first method that works wins:
   1. **ATS APIs:** Greenhouse (including company pages with `?gh_jid=`), Lever, Ashby
   2. **LinkedIn:** `/jobs/view/<id>`, `?currentJobId=`, `lnkd.in` short links, read from the public guest page
   3. **schema.org JobPosting** data in the page (most job sites)
   4. **Page title + description** as a last resort, marked incomplete
4. **Quality check** (`quality.assess`), on every import:
   - cleans up "| LinkedIn" suffixes, splits "Data Engineer at Wix — Tel Aviv" into title / company / location, and drops site names used as the company
   - lists what's still missing (title, company, location, a description of at least 200 characters). These are saved as `parse_issues` and shown on the job with a **Retry import** button.
5. If the result is complete and has a company, it checks for the same company + title + city among your jobs. Found → that job opens instead.
6. **Save:** status **saved**, source **link**, an "Imported from …" timeline entry, and the match grade.

**Retry import** (`POST /api/jobs/{id}/reimport`) reads the link again with the current parsers. It updates only fields that came back filled, and keeps status, notes and dates.

**Add by hand** (*Add* page → fill in the form): `POST /api/jobs`, source **manual**.

## 4. The match grade

`services/matching.py`, `services/skills.py`, `api_profile.py`

### Your profile
- **Upload CV** (*Settings → Your CV and skills*): PDF, Word (.docx) or text, up to 5 MB (first 10 PDF pages). The text is read (`services/cv.py`), **your skills list is replaced** with the skills found in it, and if you haven't set your years of experience, they're estimated from the CV's date ranges, skipping the education section.
- You can edit the skills and years by hand afterwards. Skill names are matched to the built-in list (`skills.SKILLS`, about 85 skills in groups such as *warehouse* or *orchestration*).
- Without skills or years there's no grade, and the Jobs page asks you to upload a CV.

### How a job is graded
The grade is a weighted average of five parts. A part with nothing to judge is left out, and the others are re-weighted.

| Part | Weight | Score |
|---|---|---|
| **Skills** | 50 | Skills found in the job's title + description. Each is *required*, or *nice to have* if it's under a heading like "Nice to have" / "Advantages" or on a line that says "advantage", "a plus", "preferred". Required = weight 1, nice = 0.35. You have it = full credit; you have a skill in the same group = half credit ("similar"); otherwise none. |
| **Experience** | 15 | The job's main "N+ years" requirement vs your years: enough = 100, 1 short = 70, 2 short = 45, more = 15 |
| **Seniority** | 15 | The title's level (junior 0-3 years, mid-level 2-8, senior 4-14, lead / manager 6+, staff / principal 8+) vs your years. In range = 100. Under = 70 / 45 / 20. Over by up to 3 years = 80, more = 60. |
| **Role** | 10 | Title matches one of your title phrases = 100, shares a word = 60, otherwise 25 |
| **Location** | 10 | Remote = 100. Distance unknown = 70. Within half your limit = 100, falling to 70 at the limit. Outside what you accept = 20. |

The job page shows each part, the skills table (have / similar / missing, required first) and notes, e.g. when the description is too short to judge.

### When grades are recalculated
- a job is added, imported, re-imported, or its title / description / work mode is edited
- you save Settings, your skills / years, or upload a CV (all your jobs at once)
- **Recalculate** on a job page (`POST /api/jobs/{id}/match`)

### AI grade (Claude)
`services/ai_match.py`. The rule-based grade above is instant, but it only counts keywords: it can't tell a data *analyst* role from a data *engineer* role, and "Airflow, Dagster or Prefect" counts as three missing skills. The AI grade reads the job and your CV the way a recruiter would.

Needs: `ANTHROPIC_API_KEY` in `.env`, an uploaded CV, and **Settings → AI match grade** switched on (per user, off by default).

1. **Every 5 minutes** the worker (`ai_grade_pending`) looks for jobs of users who switched it on whose AI grade is missing or out of date. It skips *rejected*, *archived* and *ghosted* jobs, and grades up to 40 per run, 4 at a time.
2. **The prompt:** fixed grading instructions + your CV + your preferences (titles, years, senior only, work modes, home and distances) as the system prompt, which is cached, so the jobs after the first cost less. The job's title, company, location, work mode, distance and description go in the message.
3. **The answer** has a fixed structure: `score` 0-100, `verdict` (strong 85+, good 70-84, stretch 50-69, poor under 50), `summary`, `strengths`, `gaps`, `dealbreakers`. It's stored in `jobs.ai_match`, and **the job's match score becomes the AI score**. The rule-based details stay under *Keyword check* on the job page.
4. **Out of date:** each grade stores a fingerprint of everything in the prompt (CV, preferences, job text, model, prompt version). Change any of them and the job shows its rule-based grade again (`stale`) until the next run re-grades it. Nothing else triggers a paid call, so each job is graded once and again only when its inputs change.
5. **Grade with AI / Ask AI again** on a job page grades it right away (`POST /api/jobs/{id}/ai-match`), even if the switch is off.
6. **Failures:** a network error or rate limit is retried next run. If the model declines, the API retries on a fallback model in the same call. If there's still no usable answer, the error is stored, shown on the job page, and not retried until the job or CV changes. A rejected API key stops the run (worker log: `API key rejected`).

Model and effort: `AI_MODEL` (default `claude-sonnet-5-5`) and `AI_EFFORT` (`medium`) in `.env`. Changing either re-grades everything. Cost: about 1-2 cents per job on Sonnet. The worker log line `ai_match model=… in=… cached=… out=…` shows the tokens of each call.

## 5. Tracking an application

`api.py: _apply_status, update_job, stats`

```
 new ──► saved ──► applied ──► screening ──► interview ──► offer
  │                  │             │              │
  └──► archived      └─────────────┴──────────────┴──► rejected / ghosted
       ("Not for me")
```

1. **New jobs** (*Jobs → New for you*): **★ Save** → *saved*, **✕ Not for me** → *archived*.
2. Change the status from the job page (status picker or next-step buttons) or from the **Tracker**. Each change adds a timeline entry such as `saved → applied`.
3. **Applied** records the date applied and sets a **follow-up** for 7 days later. Due follow-ups show as a banner on the Jobs page and in the Tracker.
4. **Screening / interview / offer / rejected / ghosted / archived** clear the follow-up.
5. Notes (`POST /api/jobs/{id}/notes`) go into the timeline too. You can also edit contact, notes and the follow-up date on the job.
6. **Stats** (`GET /api/stats`): count per status and per source, number applied, and response rate = applied jobs that reached screening / interview / offer / rejected.

## 6. Gmail: updating jobs from your email

`api_gmail.py`, `services/gmail/` (`oauth.py`, `client.py`, `classify.py`, `match.py`, `sync.py`)

### Connecting
1. *Settings → Gmail → **Connect Gmail*** → `GET /api/gmail/connect` sends you to Google, asking for **gmail.modify**. That permission lets the app read mail and change labels; it can't send or delete mail.
2. Google sends you back to `/api/gmail/callback`. The request carries a signed, 15-minute `state` that ties it to your session.
3. The refresh token is **encrypted** (key derived from `SECRET_KEY`) and saved in `gmail_accounts`.
4. The **first check** reads your Inbox from the **last 14 days** (`sync.LOOKBACK`), so a reply that came just before you connected still counts.

### Every check
Every 5 minutes for all users (`worker.py`), or **Check now** (`POST /api/gmail/sync`):

1. **Which mail:** everything in the Inbox from the **last 24 hours** (`sync.RECHECK`), read or unread, not only mail that arrived since the last check. So an email the rules missed once is looked at again by the next check after the rules are fixed. If checks stopped for longer (laptop off) it goes back to the last check. Mail that was already handled, mail you sent yourself, and mail older than the 14-day window are skipped.
2. **Is it a job email?** (`classify.py`, English and Hebrew rules). It must mention an application, position, role or candidacy. Job alerts and "jobs you may like" newsletters are ignored. Then it checks, in this order:
   - **Rejection:** "unfortunately", "not moving forward", "לצערנו"… Sentences like "*if* you're not selected" or "we can't reply to *every* applicant" don't count.
   - **Interview invitation:** "we'd like to schedule a call", a Calendly link, "נשמח לזמן אותך"… "*If* your profile fits *we'll contact you*" doesn't count.
   - **Application received:** "thank you for applying", "we received your application", "קיבלנו את קורות החיים"…
   - None of these → not stored at all.
3. **Which job is it about?** (`match.py`). Each of your jobs gets points: same email thread as a job already linked +10, company in the sender's domain +3, in the sender's name +3, in the subject +3 (or body +2), job title in the text +3 (or most of its words +1). The job wins if it has 3+ points and is clearly ahead. If several jobs at one company are close, the one whose status fits the email wins; a rejection, for example, goes to a job you applied to. Still unclear → **unmatched**.
4. **Act on it:**

   | Email | Status change (only forward, never back) | Gmail |
   |---|---|---|
   | Application received | new / saved → **applied** | moved to your *Application received* label (out of the Inbox) |
   | Interview invitation | new / saved / applied / screening → **interview** | stays in the Inbox |
   | Rejection | anything except offer / rejected → **rejected** | moved to your *Rejection* label |

   The job's timeline gets "Rejection email from …" with a link to the email. A confirmation for a company that isn't in your jobs creates the job (source **email**) and marks it applied. Mail stays unread; the app never marks mail as read.
5. Only job emails are stored (`gmail_messages`): sender, subject, date, kind and what was done. Never the body.

### In Settings → Gmail
- **Gmail label names:** where confirmations and rejections are moved. Defaults are *Job search/Applied* and *Job search/Rejected*; each user can rename them (`PUT /api/gmail/labels`, stored in `user_settings`). "/" nests a label under another; labels are created in Gmail when first needed. Renaming affects only emails moved afterwards.
- **Recent job emails:** what each email did, with **Undo**. Undo puts the status back, moves the email back to the Inbox, and removes a job the email created.
- **Unmatched** emails get a *Which job is this about?* list and **Link to job** (`POST /api/gmail/messages/{id}/assign`).
- **Disconnect:** revokes access at Google, deletes the token, and forgets the list of handled emails, so connecting again starts fresh. Job statuses and timelines stay.
- If Google refuses the stored access (you removed it in your Google account, for example), checks stop and Settings asks you to connect again.

## 7. What runs on a schedule

`worker.py` (arq, Israel time). Each job runs once at a time (`unique=True`).

| When | Task | Time limit |
|---|---|---|
| 07:00 and 15:00 | `collect_all`: job search for all users (section 2) | 30 min |
| every 5 minutes | `gmail_sync_all`: Gmail check for every connected user (section 6) | 4 min |
| every 5 minutes (:02, :07, …) | `ai_grade_pending`: AI grades for new or changed jobs (section 4); nothing without an API key | 10 min |

See what they did: `docker compose logs worker --since 1h`.
