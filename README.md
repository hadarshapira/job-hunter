# JobHunter

A job-search assistant for Senior Data Engineer roles in Israel. It's one installable web app (PWA) for phone and desktop Chrome. It finds jobs, grades how well each fits your CV, tracks your applications, and reads your Gmail to update each job when a company replies.

Several people can use it: everyone signs in with email + password or Google, and all data is kept separate per user.

## What it does today

| Area | What happens |
|---|---|
| **Find jobs** | Twice a day (07:00 and 15:00, Israel time), and whenever you press **Find jobs now**: it searches LinkedIn, Greenhouse / Lever / Ashby company boards and JSearch (Google for Jobs). Then it keeps only the jobs that fit your titles, work mode and distance from home. |
| **Add a job yourself** | Paste any job link (or **Share → JobHunter** on Android). Greenhouse, Lever, Ashby and LinkedIn links are read through their structured data; other sites through schema.org data, or the page title as a fallback. |
| **Match grade** | Every job gets a 0-100 grade against your CV: skills 50%, experience 15%, seniority 15%, role 10%, location 10%. It also shows a table of skills you have, similar ones, and missing ones. With an Anthropic API key, **Claude grades each job against your full CV** instead, like a recruiter, with the reasons (strengths, gaps, deal-breakers). |
| **Tracker** | New → Saved → Applied → Screening → Interview → Offer / Rejected / Ghosted / Archived, with notes, a timeline and follow-up reminders (7 days after applying). |
| **Gmail** | Every 5 minutes it reads all Inbox mail from the last 24 hours (read or unread). "We got your application" → **Applied**, rejection → **Rejected** (moved to Gmail labels you name in Settings, by default **Job search/Applied** and **Job search/Rejected**), interview invitation → **Interview** (stays in the Inbox). Every action can be undone. |
| **Stats** | Pipeline counts, jobs by source, response rate. |

Not built yet: push alerts, tailored CV / cover letters, AllJobs / Drushim, cloud hosting.

## Quick start

```powershell
copy .env.example .env          # then fill in the values (see docs/operations.md → "Settings in .env")
docker compose up -d --build --wait
```

- App: http://localhost:8088. In Chrome, click the install icon in the address bar.
- API docs (Swagger): http://localhost:8000/docs
- Phone: through Tailscale HTTPS. See [docs/operations.md](docs/operations.md#phone-access-tailscale).

## Documentation

| Document | Read it when you want to… |
|---|---|
| [docs/workflows.md](docs/workflows.md) | understand what happens, step by step: job search, link import, match grade, tracker, Gmail |
| [docs/operations.md](docs/operations.md) | run, update, back up, test, set up Google / Tailscale, or fix something that broke |
| [docs/parsers.md](docs/parsers.md) | fix a job site whose links import badly |
| [backend/README.md](backend/README.md) | find your way around the Python code, add an endpoint, source or database column |
| [frontend/README.md](frontend/README.md) | find your way around the app screens and how they talk to the API |
| [CLAUDE.md](CLAUDE.md) | the short rule list for AI coding sessions |

## How it fits together

```
 Phone / desktop Chrome (PWA)
          │  HTTPS via Tailscale (tailnet only)            Google, LinkedIn, Greenhouse/Lever/Ashby,
          ▼                                                 JSearch, OpenStreetMap, Gmail API
 ┌─────────────────┐   /api/*    ┌──────────────┐                   ▲
 │ web  (nginx)    │ ──────────► │ api (FastAPI)│ ──────────────────┤
 │ React app files │             └──────┬───────┘                   │
 └─────────────────┘                    │                           │
                                 ┌──────▼───────┐   ┌───────────────┴──┐
                                 │ db (Postgres)│ ◄─│ worker (arq)     │  07:00 / 15:00: find jobs
                                 └──────────────┘   │ + redis (queue)  │  every 5 min: Gmail 
                                                    └──────────────────┘
```

All five parts run as Docker containers, defined in `docker-compose.yml`:

| Container | Job | Port on this PC |
|---|---|---|
| `web` | nginx: serves the React app and forwards `/api/*` to `api`. Also serves the public home + privacy pages Google requires. | 8088 (app), 127.0.0.1:8089 (public pages) |
| `api` | FastAPI: every request from the app. Runs database migrations on start. | 127.0.0.1:8000 |
| `worker` | arq: the scheduled job search and Gmail checks | – |
| `db` | Postgres 17 (pgvector image) | 127.0.0.1:5433 |
| `redis` | the worker's schedule and locks | 127.0.0.1:6380 |

## Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2 (async) + Alembic, Postgres 17, Redis + arq, httpx, selectolax, Anthropic SDK (Claude)
- **Frontend:** React 18 + TypeScript, Vite + vite-plugin-pwa, TanStack Query, Tailwind CSS 4
- **Hosting:** Docker Compose on this PC, Tailscale for phone access

## Tests

```powershell
docker compose build api -q; docker compose run --rm --no-deps api pytest -q
```

They use an in-memory SQLite database and fake Google / LinkedIn responses, so nothing real is called.
