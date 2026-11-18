# JobHunter: notes for Claude

Multi-user job-search PWA. Backend: FastAPI + Postgres (`backend/`). Frontend: React/TS PWA (`frontend/`). Everything runs in Docker.

Docs: `README.md` (overview), `docs/workflows.md` (what each feature does, step by step), `docs/operations.md` (run, deploy, backup, troubleshoot), `backend/README.md` and `frontend/README.md` (code maps, how to add things), `docs/parsers.md` (job-link import). Keep them up to date when behaviour changes.

## Commands
- Run tests: `docker compose build api -q && docker compose run --rm --no-deps api pytest -q`
- Rebuild and restart: `docker compose up -d --build --wait`
- Diagnose a job link: `docker compose exec api python -m app.tools.diagnose "<url>"`
- Frontend type-check and build happen inside `docker compose build web`.

## Rules
- **Worktrees:** make every change in its own worktree with [Worktrunk](https://worktrunk.dev): `wt switch -c <branch>` (hooks in `.config/wt.toml` copy `.env` in), then `wt merge` (runs the tests, merges into main, redeploys) and `wt remove`. Never run a plain `docker compose up` from a worktree: the compose project is named `job-hunter`, so it would replace the live app. In a worktree, use `docker compose -p jh-<branch> ...`.
- **Job import problems:** follow `docs/parsers.md`. Every import ends in `quality.assess()`; site-specific code goes in `app/services/sites/` with a synthetic fixture and tests; generic fixes go in `quality.py` so all sites benefit; afterwards, repair existing jobs with re-import.
- **Data isolation:** every query on jobs/events must filter by the signed-in user (`current_user`). Add a cross-user test for any new endpoint.
- **Database changes** need an Alembic migration in `backend/migrations/versions/`.
- **Windows encoding:** don't rewrite source files with PowerShell `Get-Content`/`Set-Content` (it corrupts UTF-8 such as Hebrew). Use the Edit tool.
- **Secrets** live only in `.env`, which is git-ignored. Never commit it.
