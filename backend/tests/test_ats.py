import json

import httpx

from app.models import WorkMode
from app.services.ats import greenhouse_ref
from app.services.importer import fetch_and_parse

GH_JOB = {
    "title": "Senior Data Engineer",
    "company_name": "Riskified",
    "location": {"name": "Tel Aviv-Yafo, Tel Aviv District, Israel"},
    "content": "&lt;p&gt;Build &lt;b&gt;Spark&lt;/b&gt; pipelines. Hybrid work.&lt;/p&gt;",
    "first_published": "2026-10-20T10:00:00-04:00",
}
LEVER_JOB = {
    "text": "Data Engineer",
    "categories": {"location": "Herzliya, Israel"},
    "workplaceType": "onsite",
    "descriptionPlain": "Kafka and Airflow.",
    "lists": [{"text": "Requirements", "content": "<li>5+ years</li><li>Python</li>"}],
    "additionalPlain": "",
    "createdAt": 1793000000000,
}
ASHBY_BOARD = {
    "jobs": [
        {"id": "11111111-2222-3333-4444-555555555555", "title": "Staff Data Engineer", "location": "Israel",
         "workplaceType": "Remote", "descriptionPlain": "dbt + Snowflake", "publishedAt": "2026-11-01T00:00:00Z"}
    ]
}


def make_client() -> httpx.AsyncClient:
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url.startswith("https://boards-api.greenhouse.io/v1/boards/riskified/jobs/123"):
            return httpx.Response(200, json=GH_JOB)
        if url.startswith("https://api.lever.co/v0/postings/acme/"):
            return httpx.Response(200, json=LEVER_JOB)
        if url.startswith("https://api.ashbyhq.com/posting-api/job-board/dataco"):
            return httpx.Response(200, json=ASHBY_BOARD)
        return httpx.Response(404, text="nope")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_greenhouse_refs():
    assert greenhouse_ref("https://job-boards.greenhouse.io/riskified/jobs/123") == ("riskified", "123")
    assert greenhouse_ref("https://boards.greenhouse.io/riskified/jobs/123?t=x") == ("riskified", "123")
    assert greenhouse_ref("https://www.riskified.com/careers/job/?gh_jid=123") == ("riskified", "123")
    assert greenhouse_ref("https://example.com/jobs/1") is None


async def test_greenhouse_company_page():
    async with make_client() as c:
        job = await fetch_and_parse("https://www.riskified.com/careers/job-description/?gh_jid=123", c)
    assert job.complete and job.company == "Riskified"
    assert job.title == "Senior Data Engineer"
    assert "Spark" in job.description and job.work_mode == WorkMode.hybrid
    assert job.posted_at.isoformat() == "2026-10-20"


async def test_lever():
    async with make_client() as c:
        job = await fetch_and_parse("https://jobs.lever.co/acme/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", c)
    assert job.title == "Data Engineer" and job.company == "Acme"
    assert job.work_mode == WorkMode.onsite
    assert "• Python" in job.description


async def test_ashby():
    async with make_client() as c:
        job = await fetch_and_parse("https://jobs.ashbyhq.com/dataco/11111111-2222-3333-4444-555555555555", c)
    assert job.title == "Staff Data Engineer" and job.work_mode == WorkMode.remote


async def test_unknown_ats_falls_back_to_html():
    async with make_client() as c:
        try:
            await fetch_and_parse("https://example.com/job/1", c)
        except httpx.HTTPStatusError as e:
            assert e.response.status_code == 404
