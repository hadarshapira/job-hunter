# Job import: how links are parsed, and how to fix a site that breaks

## Pipeline (`backend/app/services/importer.py: fetch_and_parse`)
1. **Site extractors** (`app/services/sites/__init__.py`), tried in order:
   - `ats`: Greenhouse (including company pages with `?gh_jid=`), Lever, Ashby, through their public JSON APIs
   - `linkedin`: LinkedIn job links (`/jobs/view/<id>`, `?currentJobId=`, `lnkd.in`), read from the public guest job page
2. **Generic HTML**: schema.org `JobPosting` JSON-LD.
3. **Metadata fallback**: `og:title` / `<title>` / description, marked incomplete.
4. **Quality check** (`app/services/quality.py`), run on every result:
   - cleans `| LinkedIn`-style suffixes, turns "X at Company — City" and "Company hiring X in City" titles into separate fields, and drops site names used as the company
   - lists remaining issues: no title, no company, no location, description under 200 chars
   - issues are saved on the job (`parse_issues`), shown with a **Retry import** button, and logged as `import_quality host=… extractor=… issues=…`

## Rules
1. **Never save junk silently.** Every import path ends in `quality.assess()`. If a new generic problem appears (another site name, another title pattern), add it to `quality.py` with a test, so every site benefits.
2. **Prefer official/public structured sources over HTML scraping:** an ATS JSON API, then embedded JSON-LD, then the site's stable HTML classes, then page metadata.
3. **One site = one extractor module** in `app/services/sites/` (or `ats.py` for ATS APIs), registered in `sites/__init__.py`. It returns `None` when the URL isn't its site or fetching fails, so the pipeline falls through to the next step. It never raises for network errors.
4. **Every extractor has tests with a synthetic fixture** in `backend/tests/fixtures/`, shaped like the real page but with made-up content. Don't commit real third-party pages. Cover: link formats (URL → id), the parsed fields, and the fallback when the primary request fails.
5. **User-initiated only for sites without a public API** (like LinkedIn): one request per link the user shares or pastes, with no crawling or bulk collection.
6. **Fixes apply to old jobs too:** after deploying a fix, affected jobs are repaired with **Retry import** (`POST /api/jobs/{id}/reimport`), which keeps status, notes and dates.

## When a link imports badly
1. Find the problem:
   - `docker compose logs api | grep import_quality`
   - or run `docker compose exec api python -m app.tools.diagnose "<url>" --save sample`
2. Look at the saved page (`docker compose cp api:/tmp/sample.html .`) for JSON-LD, an API the page calls, or stable class names.
3. Add or fix the extractor (rule 3), create a synthetic fixture and tests (rule 4), and run `docker compose run --rm --no-deps api pytest -q`.
4. Rebuild (`docker compose up -d --build api`), check with `diagnose` again, then **Retry import** the affected jobs.
