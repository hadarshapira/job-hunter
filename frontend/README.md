# Frontend (React PWA)

React 18 + TypeScript, built with Vite, styled with Tailwind CSS 4, data through TanStack Query. It's installed as an app (PWA) on phone and desktop Chrome. In production it's built into static files served by nginx (the `web` container), which also forwards `/api/*` to the API.

## Files

```
src/
├── main.tsx            Start-up: React Query client, router, service-worker registration + auto-update
├── App.tsx             Sign-in gate, layout (desktop sidebar / phone bottom bar) and routes
├── api.ts              Every API call, the TypeScript types, status / source labels, date helpers
├── components.tsx      Shared pieces: JobCard, StatusPill, MatchBadge, PageTitle, Empty
├── index.css           Colours (light + dark) and the small set of CSS classes (btn-primary, card, input…)
└── pages/
    ├── Login.tsx         Email/password sign-in and sign-up, Google button
    ├── Jobs.tsx          Feed: New for you / My jobs / Not for me / All, search, sort, source chips,
    │                     "Find jobs now" with live progress and the search report
    ├── JobDetail.tsx     One job: status, follow-up, contact, notes, timeline, match card, retry import
    ├── Tracker.tsx       Applications grouped by stage, with the next step for each
    ├── AddJob.tsx        Paste a link (or receive one from Android "Share") or fill in a job by hand
    ├── Stats.tsx         Pipeline and source counts, response rate, log out
    └── Settings.tsx      Where to search, home + distance, titles, skip words, company boards,
                          CV and skills, Gmail
public/                 Icons and static files copied as is
public-site/            The two public pages for Google's OAuth review (home + privacy), served on :8081
scripts/make_icons.py   Generates the PNG app icons from code (standard library only)
nginx.conf              Caching rules, /api proxy, public-site server
vite.config.ts          PWA manifest (name, colours, Android share target) and offline caching
```

## Routes

| Path | Page | Phone tab |
|---|---|---|
| `/` | Jobs | Jobs |
| `/tracker` | Tracker | Tracker |
| `/add` | Add a job (`?url=…` imports at once; Android Share lands here) | Add |
| `/stats` | Stats | Stats |
| `/settings` | Settings (`?gmail=connected` etc. shows the result of connecting Gmail) | Settings |
| `/jobs/:id` | Job details | – |

## How data is loaded

- **All server calls go through `req()` in `api.ts`.** It sends the session cookie, turns error responses into `Error(detail)`, and throws `AuthError` on 401. `App.tsx` shows the sign-in page whenever `/api/auth/me` fails that way.
- **TanStack Query** caches every response (`main.tsx`: fresh for 15 s, 2 retries, never retry a 401).
- **Query keys:** everything that lists jobs starts with `'jobs'` (`['jobs', filter, query, sort, source]`, `['jobs', 'sources', …]`, `['jobs', 'tracker']`). After a change, `invalidateQueries({ queryKey: ['jobs'] })` refreshes every list and count at once. A single job is `['job', id]`. Others: `'stats'`, `'settings'`, `'profile'`, `'companies'`, `'collect'`, `'gmail'`, `'gmail-messages'`, `'me'`.
- **Find jobs now** (`Jobs.tsx → FindJobsButton`) polls `GET /api/collect` every 3 s while a search runs, and refreshes the jobs and stats when it finishes. It gives up waiting after 8 minutes.

## Installing and updating (PWA)

- `vite-plugin-pwa` builds the service worker. The app opens offline with the last data it loaded (API calls are *network first*, falling back to the cache after 5 s).
- **Updates:** `main.tsx` checks for a new version when the app opens, whenever it comes back to the screen, and every 30 minutes. A new version takes over and reloads the page by itself (`skipWaiting` + `clientsClaim`). nginx never caches `index.html` or `sw.js`, and files under `/assets/` have a content hash in their name and are cached for a year.
- **Android Share → JobHunter:** the manifest's `share_target` opens `/add?url=…&text=…`. `AddJob.tsx` takes the link from `url`, or from `text` when apps put it there, and imports it straight away.

## Styling

- Colours are CSS variables in `index.css` (`--bg`, `--primary`, `--st-applied`…), with a dark set under `prefers-color-scheme: dark`. **Change colours only there**, plus the phone bar colour (`theme-color`) in `index.html` and `vite.config.ts`.
- Shared classes: `btn-primary`, `btn-ghost`, `card`, `input`, `pill`. Everything else is Tailwind utility classes.
- Layout is mobile first: a bottom tab bar on phones, a sidebar from the `md` breakpoint.

## Developing

The normal way is the Docker build: `docker compose up -d --build web`. It runs `tsc --noEmit` (type check) and `vite build`, and fails on type errors.

For fast edits with hot reload, run this outside Docker (needs Node 22, API running in Docker on port 8000):

```powershell
cd frontend
npm install
npm run dev          # http://localhost:5173, /api is proxied to localhost:8000
```

Google sign-in won't work on port 5173 unless `http://localhost:5173` is added to the OAuth client's JavaScript origins; email + password works.

## Adding a page or API call
1. Types and the call in `api.ts` (`export const api = { … }`).
2. A page in `pages/`, using `useQuery` / `useMutation`. Invalidate the keys whose data changed.
3. A `<Route>` in `App.tsx`, and an entry in `NAV` if it needs a tab (there are 5 on the phone bar; think twice before adding a sixth).
