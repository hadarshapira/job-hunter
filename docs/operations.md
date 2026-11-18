# Operations: run, update, back up, fix

All commands run in PowerShell from the project folder (where you cloned the repo). Everything runs in Docker Desktop.

- [Settings in .env](#settings-in-env)
- [Start, stop, status](#start-stop-status)
- [Deploying a change](#deploying-a-change)
- [Tests](#tests)
- [Database changes (migrations)](#database-changes-migrations)
- [Backups](#backups)
- [Phone access (Tailscale)](#phone-access-tailscale)
- [Google setup (sign-in and Gmail)](#google-setup-sign-in-and-gmail)
- [Keeping it running](#keeping-it-running)
- [Logs and troubleshooting](#logs-and-troubleshooting)

---

## Settings in .env

Secrets live only in `.env`, which git ignores, so never commit it. Start from `.env.example`. After changing `.env`, run `docker compose up -d --wait` so the containers read it again.

| Setting | What it's for | If empty |
|---|---|---|
| `SECRET_KEY` | Signs session cookies and is the key for the encrypted Gmail tokens. Long and random. | Unsafe dev default. **Changing it logs everyone out and breaks stored Gmail connections** (users must connect again). |
| `DB_PASSWORD` | Postgres password, used by `db`, `api` and `worker` | `jobhunter` |
| `GOOGLE_CLIENT_ID` | Google Sign-In and Gmail (OAuth "Web application" client) | No Google button, no Gmail |
| `GOOGLE_CLIENT_SECRET` | The same client's secret, needed for Gmail | Gmail section hidden |
| `PUBLIC_URL` | The address Google sends Gmail sign-in back to, e.g. `https://myhost.ts.net` | Taken from the request's host (works through Tailscale) |
| `JSEARCH_API_KEY` | RapidAPI key for JSearch (Google for Jobs) | JSearch skipped; LinkedIn + company boards only |
| `ANTHROPIC_API_KEY` | Claude API key (console.anthropic.com) for the AI match grade | Only the rule-based grade |
| `CONTACT_EMAIL` | Contact address on the public home + privacy pages (Google's OAuth review needs one). Read when `web` is built: `docker compose up -d --build web` | "the owner of this copy" |
| `SIGNUP_ENABLED` | `false` stops new accounts | `true` |
| `COOKIE_SECURE` | `true` once served only over HTTPS | `false` |

Advanced (rarely changed, defaults in `backend/app/config.py`): `JSEARCH_CACHE_HOURS` (20), `JSEARCH_MIN_QUOTA` (15), `SESSION_DAYS` (30), `AI_MODEL` (`claude-sonnet-5-5`), `AI_EFFORT` (`medium`).

## Start, stop, status

```powershell
docker compose up -d --wait          # start everything (waits until the API is healthy)
docker compose ps                     # what's running
docker compose stop                   # stop (data is kept)
docker compose restart worker         # restart one part
```

Data lives in the Docker volume `job-hunter_dbdata`. `docker compose down` keeps it. **`docker compose down -v` deletes the database.**

## Deploying a change

With [Worktrunk](https://worktrunk.dev) (`winget install max-sixty.worktrunk`), each change gets its own folder and branch:

```powershell
wt switch -c my-change      # new worktree in ..\job-hunter.my-change, .env copied in (.worktreeinclude)
# ...edit, commit...
wt merge                    # runs the tests (isolated Docker project jh-my-change), merges into main, redeploys
wt remove                   # if the worktree is still there: delete it and its test images
git push
```

The hooks are in `.config/wt.toml`; Worktrunk asks once to approve them. Don't run a plain `docker compose up` inside a worktree: the compose project is named `job-hunter`, so it would replace the live app with that branch.

Without Worktrunk, after editing code:

```powershell
docker compose build api -q; docker compose run --rm --no-deps api pytest -q   # 1. tests must pass
docker compose up -d --build --wait                                            # 2. rebuild and restart
git add <files>; git commit -m "…"; git push                                   # 3. save it
```

- The code is copied into the images, not mounted. **A change does nothing until you rebuild.** `docker compose exec api …` runs the *old* code until then.
- The API runs `alembic upgrade head` each time it starts, so new migrations apply automatically.
- Only `web` changed (frontend)? `docker compose up -d --build web`. The TypeScript check runs inside that build and fails it on type errors.
- **The phone app updates itself:** when it opens or comes back to the screen (and every 30 minutes while open), it checks for a new version and reloads into it (`frontend/src/main.tsx`). If it ever looks stuck on an old version, close the app completely and open it again.

## Tests

```powershell
docker compose build api -q; docker compose run --rm --no-deps api pytest -q          # all (~20 s)
docker compose run --rm --no-deps api pytest -q tests/test_gmail.py                     # one file
docker compose run --rm --no-deps api pytest -q -k reconnect                            # by name
```

The tests use in-memory SQLite and fake HTTP responses (`backend/tests/conftest.py`), so they need no network and never touch your real data. Frontend type check: `docker compose build web`.

## Database changes (migrations)

1. Change the model in `backend/app/models.py`.
2. Add the next migration file in `backend/migrations/versions/`, numbered after the last one, e.g. `0010_<what>.py` with `down_revision = "0009"`. Copy the style of an existing file.
3. Rebuild (`docker compose up -d --build --wait`). The API applies it on start.

```powershell
# which migration the database is on
docker compose exec db psql -U jobhunter -d jobhunter -c "select version_num from alembic_version"
# undo the last migration (then deploy the older code)
docker compose exec api alembic downgrade -1
```

## Backups

There's no automatic backup yet. Take one before risky changes, and now and then:

```powershell
# back up: writes jobhunter-<date>.dump in the current folder
docker compose exec -T db pg_dump -U jobhunter -d jobhunter -Fc -f /tmp/backup.dump
docker compose cp db:/tmp/backup.dump "jobhunter-$(Get-Date -Format yyyy-MM-dd).dump"

# restore (replaces the current data!)
docker compose stop api worker
docker compose cp "jobhunter-2026-11-16.dump" db:/tmp/restore.dump
docker compose exec -T db pg_restore -U jobhunter -d jobhunter --clean --if-exists /tmp/restore.dump
docker compose start api worker
```

The dump is written inside the container and copied out because PowerShell's `>` saves output as text, which would corrupt the binary file. Keep backups outside the project folder, or at least out of git: they contain everyone's data.

## Phone access (Tailscale)

The phone reaches the app through Tailscale, a private network between your own devices with real HTTPS. HTTPS is required to install the app and for Google sign-in.

| Address | Who can open it | Serves |
|---|---|---|
| `https://<pc-name>.<tailnet>.ts.net` | only your Tailscale devices | the app (`localhost:8088`) |
| `https://<pc-name>.<tailnet>.ts.net:8443` | anyone (Tailscale **Funnel**) | only the public home + privacy pages Google requires (`localhost:8089`) |

Setup (once, in an administrator PowerShell on the PC):

```powershell
tailscale serve --bg 8088                      # the app, tailnet only
tailscale funnel --bg --https=8443 8089        # public home + privacy pages
tailscale serve status                         # check
```

- Tailscale runs in **unattended mode** under the PC's main Windows user, so it keeps working when that user isn't signed in and other Windows users can't take it over (tray icon → Preferences → *Run unattended*).
- On the phone: install Tailscale, sign in to the same account, open the `ts.net` address in Chrome → menu → **Install app**.
- The app itself is never on Funnel. Only the two static pages are public (`frontend/nginx.conf`, second `server` block).

## Google setup (sign-in and Gmail)

In Google Cloud Console, in one project:

1. **OAuth consent screen:** app name, support email, home page `https://<pc>.ts.net:8443/` and privacy policy `https://<pc>.ts.net:8443/privacy` (the public pages). Scopes: `openid`, `email`, `profile`, `…/auth/gmail.modify`. Publishing status: **In production**, otherwise tokens expire after 7 days.
2. **Gmail API:** enable it (APIs & Services → Library).
3. **Credentials → OAuth client ID → Web application:**
   - Authorized JavaScript origins (Google sign-in button): `https://<pc>.ts.net`, `http://localhost:8088`
   - Authorized redirect URIs (Gmail): `https://<pc>.ts.net/api/gmail/callback`, `http://localhost:8088/api/gmail/callback`
4. Put the client ID and secret in `.env` (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`) and run `docker compose up -d --wait`.

The redirect URI the app sends must match one of those **exactly**. It's `PUBLIC_URL` + `/api/gmail/callback` when `PUBLIC_URL` is set, otherwise built from the address you opened the app at (`api_gmail._redirect_uri`).

## Keeping it running

The scheduled search and Gmail checks only run while the PC is on:

- Windows power settings: **never sleep when plugged in**.
- Docker Desktop: **Start when you sign in**. All containers have `restart: unless-stopped`, so they come back by themselves after a reboot.

## Logs and troubleshooting

```powershell
docker compose logs api --since 30m             # requests, import problems
docker compose logs worker --since 2h           # scheduled search and Gmail checks
docker compose logs api | Select-String import_quality    # links that imported badly
```

| Problem | Check / fix |
|---|---|
| App says "Can't reach the JobHunter server" | `docker compose ps`: are `api` and `web` up? Is Docker Desktop running? `docker compose up -d --wait` |
| Phone can't open the app | Tailscale on in the phone and on the PC? `tailscale serve status` on the PC |
| Code change has no effect | You didn't rebuild: `docker compose up -d --build --wait` |
| "Find jobs now" finds nothing new | Open *Last search report* under the button: it shows per source how many were found and why they were left out (title / distance / duplicate). Widen titles or distance in Settings. |
| LinkedIn error "limiting requests" | Normal now and then. It stops politely and continues next run. Don't run searches back to back. |
| "JSearch quota low" | The free 200 requests/month are almost used. It resumes next month. Company boards and LinkedIn still work. |
| A company board shows an error in Settings | The company moved to another ATS or renamed its board. Remove it and add the new careers link. |
| A job link imports badly | Follow [parsers.md](parsers.md): `docker compose exec api python -m app.tools.diagnose "<url>"` |
| Gmail: "access was removed or expired" | Settings → Gmail → **Connect again**. Also happens if `SECRET_KEY` changed. |
| Gmail didn't update a job | *Settings → Gmail → Recent job emails*. Not listed = it wasn't recognised as a job email. Listed as unmatched = link it to the job by hand. |
| AI grades don't appear | Settings → AI match grade on? CV uploaded? `docker compose logs worker --since 30m | Select-String ai_match`. "API key rejected" = wrong or revoked key, or no credit left on the Anthropic account. |
| Gmail "redirect_uri_mismatch" from Google | The address isn't registered: add it under Authorized redirect URIs (see Google setup) |

Look at the data directly:

```powershell
docker compose exec db psql -U jobhunter -d jobhunter
#   select id, title, company, status, match_score from jobs where user_id = 1 order by updated_at desc limit 20;
#   select started_at, added, errors from collection_runs order by started_at desc limit 5;
#   select kind, action, subject from gmail_messages order by created_at desc limit 10;
```
