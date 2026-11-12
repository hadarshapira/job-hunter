# JobHunter

A personal job-search assistant for Senior Data Engineer roles: one installable web app (PWA) for phone and desktop Chrome.

**Status:** Phase 1 (foundation) in progress. The backend API and tests are done; the web app comes next.

## What it will do
- Collect jobs from JSearch, company career pages (Greenhouse, Lever, Ashby, Comeet), AllJobs/Drushim, and pasted links
- Filter by work mode (on-site / hybrid / remote) and distance from home
- Score jobs against your CV using local AI (Ollama)
- Track applications: Saved → Applied → Screening → Interview → Offer / Rejected / Ghosted
- Write a tailored CV and cover letter for each job (you review; it never auto-applies)
- Follow your Gmail (read-only) for replies to each application
- Push alerts and interview prep

## Stack
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2 + Alembic, Postgres 17 + pgvector, Redis
- **Frontend:** React + TypeScript, Vite PWA, Tailwind
- **AI:** Ollama (local), with an optional switch to the Claude API

## Run locally
```powershell
copy .env.example .env      # then set APP_PASSWORD and SECRET_KEY
docker compose up --build
```
- API: http://localhost:8000/docs
- App: http://localhost:8088 (once the frontend is added)

## Tests
```powershell
docker compose run --rm api pytest -q
```

## Roadmap
1. Foundation: API, tracker, link import, PWA shell
2. Discovery: job collectors, dedup, location filters
3. Matching: CV → profile, scoring, alerts
4. Gmail tracking
5. Tailored CV / cover letter, interview prep
6. Israeli job-site scrapers
7. Phone access (Tailscale) and cloud deploy
