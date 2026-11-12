from datetime import date
from pathlib import Path

import httpx
import pytest

from app import api as api_module
from app.models import WorkMode
from app.services.importer import ParsedJob, fetch_and_parse
from app.services.quality import assess
from app.services.sites.linkedin import _posted, linkedin_job_id, parse_linkedin_html

FIXTURE = (Path(__file__).parent / "fixtures" / "linkedin_guest_job.html").read_text(encoding="utf-8")
# What LinkedIn's full page gave us before the LinkedIn extractor existed (metadata only)
PREVIEW_PAGE = """<html><head>
<title>ExampleCo hiring Senior Data Engineer in Tel Aviv-Yafo, Tel Aviv District, Israel | LinkedIn</title>
<meta property="og:title" content="Senior Data Engineer at ExampleCo — Tel Aviv-Yafo, Tel Aviv District, Israel | LinkedIn">
<meta property="og:site_name" content="LinkedIn Jobs">
<meta name="description" content="Apply for Senior Data Engineer at ExampleCo in Tel Aviv. Full-time Mid-Senior level role.">
</head></html>"""


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.linkedin.com/jobs/view/4488761918/", "4488761918"),
        ("https://il.linkedin.com/jobs/view/senior-data-engineer-at-exampleco-4488761918?trk=x", "4488761918"),
        ("https://www.linkedin.com/jobs/search/?currentJobId=4488761918&keywords=data", "4488761918"),
        ("https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4488761918", "4488761918"),
        ("https://www.linkedin.com/company/exampleco", None),
        ("https://example.com/jobs/view/4488761918", None),
    ],
)
def test_job_id_from_any_linkedin_link(url, expected):
    assert linkedin_job_id(url) == expected


def test_parse_guest_page():
    job = parse_linkedin_html(FIXTURE)
    assert job.title == "Senior Data Engineer"
    assert job.company == "ExampleCo"
    assert job.location == "Tel Aviv-Yafo, Tel Aviv District, Israel"
    assert job.work_mode == WorkMode.hybrid
    assert job.description.startswith("About ExampleCo")
    assert "﻿" not in job.description
    assert "• Own our dbt models on Snowflake" in job.description
    assert "Seniority level: Mid-Senior level" in job.description
    assert "Not Applicable" not in job.description
    assert job.extra["criteria"]["Employment type"] == "Full-time"


def test_posted_relative_dates():
    today = date(2026, 11, 12)
    assert _posted("4 days ago", today) == date(2026, 11, 8)
    assert _posted("2 weeks ago", today) == date(2026, 10, 29)
    assert _posted("5 hours ago", today) == today
    assert _posted("", today) is None


def client_for(pages: dict[str, tuple[int, str]]) -> httpx.AsyncClient:
    def handler(req: httpx.Request) -> httpx.Response:
        for prefix, (code, body) in pages.items():
            if str(req.url).startswith(prefix):
                return httpx.Response(code, text=body)
        return httpx.Response(404, text="")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_shared_link_uses_guest_page():
    async with client_for({"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4488761918": (200, FIXTURE)}) as c:
        job = await fetch_and_parse("https://www.linkedin.com/jobs/view/4488761918/", c)
    assert job.complete and not job.issues
    assert job.company == "ExampleCo" and job.extra["extractor"] == "linkedin"


async def test_falls_back_to_full_page_when_guest_api_fails():
    pages = {
        "https://www.linkedin.com/jobs-guest/": (429, ""),
        "https://www.linkedin.com/jobs/view/4488761918/": (200, FIXTURE),
    }
    async with client_for(pages) as c:
        job = await fetch_and_parse("https://www.linkedin.com/jobs/view/4488761918", c)
    assert job.title == "Senior Data Engineer" and job.company == "ExampleCo"


async def test_lnkd_in_short_link():
    pages = {
        "https://lnkd.in/abc": (200, '<a href="https://www.linkedin.com/jobs/view/4488761918">continue</a>'),
        "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4488761918": (200, FIXTURE),
    }
    async with client_for(pages) as c:
        job = await fetch_and_parse("https://lnkd.in/abc", c)
    assert job.company == "ExampleCo"


# --- Quality rules that protect every site, not only LinkedIn ---

def test_quality_cleans_preview_title_and_site_company():
    from app.services.importer import parse_job_html

    job, problems = assess(parse_job_html(PREVIEW_PAGE))
    assert job.title == "Senior Data Engineer"
    assert job.company == "ExampleCo"
    assert job.location == "Tel Aviv-Yafo, Tel Aviv District, Israel"
    assert problems == ["Description missing or too short"]
    assert not job.complete


@pytest.mark.parametrize(
    "raw,title,company",
    [
        ("Data Engineer - Glassdoor", "Data Engineer", ""),
        ("Senior Data Engineer | Indeed.com", "Senior Data Engineer", ""),
        ("Acme is hiring a Staff Data Engineer in Haifa", "Staff Data Engineer", "Acme"),
        ("Senior Data Engineer at Wix.com", "Senior Data Engineer", "Wix.com"),
    ],
)
def test_quality_title_patterns(raw, title, company):
    job, _ = assess(ParsedJob(title=raw, company="LinkedIn", description="x" * 300))
    assert (job.title, job.company) == (title, company)


def test_quality_finds_work_mode_late_in_long_description():
    desc = "About us. " + "We build data platforms. " * 300 + "• Hybrid work model (4 days in office, 1 WFH day)"
    job, _ = assess(ParsedJob(title="Senior Data Engineer", company="DoorLoop", location="Tel Aviv", description=desc))
    assert job.work_mode == WorkMode.hybrid


def test_quality_keeps_real_company_and_good_jobs_complete():
    job, problems = assess(ParsedJob(title="Data Engineer", company="Wix", location="Tel Aviv", description="x" * 300))
    assert job.complete and problems == []
    job, problems = assess(ParsedJob(title="Data Engineer", company="Wix", description="x" * 300))
    assert job.complete and problems == ["Location not found"]  # remote roles often have no city


async def test_reimport_updates_job_and_keeps_tracking(authed, monkeypatch):
    calls = {"n": 0}

    async def fake_fetch(url):
        calls["n"] += 1
        if calls["n"] == 1:  # first import: preview-only page
            from app.services.importer import parse_job_html

            job, job.issues = assess(parse_job_html(PREVIEW_PAGE))
            return job
        job, job.issues = assess(parse_linkedin_html(FIXTURE))
        return job

    monkeypatch.setattr(api_module, "fetch_and_parse", fake_fetch)
    first = (await authed.post("/api/jobs/import", json={"url": "https://www.linkedin.com/jobs/view/4488761918/"})).json()
    assert not first["complete"] and "Description" in first["job"]["parse_issues"]
    job_id = first["job"]["id"]
    await authed.patch(f"/api/jobs/{job_id}", json={"status": "applied", "notes": "keep me"})

    again = (await authed.post(f"/api/jobs/{job_id}/reimport")).json()
    job = again["job"]
    assert again["complete"] and job["parse_issues"] == ""
    assert job["description"].startswith("About ExampleCo") and job["work_mode"] == "hybrid"
    assert job["status"] == "applied" and job["notes"] == "keep me"
    assert job["events"][0]["text"].startswith("Re-imported:")  # newest first
