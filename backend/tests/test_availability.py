"""Removing jobs whose posting is gone, with fake sites (no network)."""

import httpx
import pytest
from sqlalchemy import select

from app.models import Event, Job, User
from app.services import availability, ingest
from app.services.availability import Verdict

OPEN_LI = '<html><h1 class="top-card-layout__title">Data Engineer</h1><button>Apply</button></html>'
CLOSED_LI = '<html><h1 class="top-card-layout__title">Data Engineer</h1>' \
            '<figure class="closed-job"><figcaption>No longer accepting applications</figcaption></figure></html>'


def handler(req: httpx.Request) -> httpx.Response:
    url = str(req.url)
    routes = {
        "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4000001": (200, OPEN_LI),
        "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4000002": (200, CLOSED_LI),
        "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4000003": (404, ""),
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs/1": (200, "{}"),
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs/2": (404, "{}"),
        "https://api.lever.co/v0/postings/leverco/11111111-1111-1111-1111-111111111111": (404, "{}"),
        "https://api.ashbyhq.com/posting-api/job-board/ashbyco": (200, '{"jobs": [{"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}]}'),
        "https://careers.example.com/open": (200, "<html>job</html>"),
        "https://careers.example.com/closed": (410, ""),
        "https://careers.example.com/broken": (503, ""),
        "https://careers.example.com/blocked": (403, ""),
    }
    status, body = routes.get(url, (404, ""))
    return httpx.Response(status, text=body)


def client(h=handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(h))


def job(url: str, source: str = "link", posting_key: str | None = None, **kw) -> Job:
    return Job(user_id=kw.pop("user_id", 1), source=source, url=url, posting_key=posting_key, title=kw.pop("title", url),
               company="Co", dedup_key=url, status=kw.pop("status", "new"), **kw)


@pytest.mark.parametrize("j,verdict", [
    (job("https://www.linkedin.com/jobs/view/4000001/", "linkedin", "linkedin:4000001"), Verdict.open),
    (job("https://www.linkedin.com/jobs/view/4000002/", "linkedin", "linkedin:4000002"), Verdict.gone),
    (job("https://il.linkedin.com/jobs/view/data-engineer-at-x-4000003?trk=1"), Verdict.gone),
    # Board jobs use the posting key, even when the link is the company's own careers page
    (job("https://acme.com/careers?gh_jid=1", "greenhouse", "greenhouse:acme/1"), Verdict.open),
    (job("https://acme.com/careers?gh_jid=2", "greenhouse", "greenhouse:acme/2"), Verdict.gone),
    (job("https://boards.greenhouse.io/acme/jobs/2"), Verdict.gone),
    (job("https://jobs.lever.co/leverco/11111111-1111-1111-1111-111111111111"), Verdict.gone),
    (job("https://jobs.ashbyhq.com/ashbyco/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"), Verdict.open),
    (job("https://jobs.ashbyhq.com/ashbyco/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"), Verdict.gone),
    (job("https://careers.example.com/open"), Verdict.open),
    (job("https://careers.example.com/closed"), Verdict.gone),
    # Unclear answers never remove a job
    (job("https://careers.example.com/broken"), Verdict.unknown),
    (job("https://careers.example.com/blocked"), Verdict.unknown),
])
async def test_check(j, verdict):
    async with client() as c:
        assert await availability.check(c, j) == verdict


async def test_network_error_is_unknown():
    def fail(req):
        raise httpx.ConnectTimeout("slow")

    async with client(fail) as c:
        assert await availability.check(c, job("https://careers.example.com/closed")) == Verdict.unknown


async def _users(maker) -> tuple[int, int]:
    async with maker() as s:
        a, b = User(email="a@example.com"), User(email="b@example.com")
        s.add_all([a, b])
        await s.commit()
        return a.id, b.id


async def test_removes_only_closed_unhandled_jobs_of_this_user(maker, no_waits):
    a, b = await _users(maker)
    async with maker() as s:
        s.add_all([
            job("https://careers.example.com/open", user_id=a, title="open"),
            job("https://careers.example.com/closed", user_id=a, title="closed new",
                events=[Event(kind="created", text="x")]),
            job("https://www.linkedin.com/jobs/view/4000002/", "linkedin", "linkedin:4000002", user_id=a, title="closed saved",
                status="saved"),
            job("https://careers.example.com/broken", user_id=a, title="broken"),
            # An application in progress stays, even when the posting closed
            job("https://careers.example.com/closed?x", user_id=a, title="applied", status="applied"),
            # Another user's closed job is not touched
            job("https://careers.example.com/closed#b", user_id=b, title="other user"),
        ])
        await s.commit()

    async with maker() as s, client() as c:
        report = await availability.remove_unavailable(s, c, a)
    assert report["removed"] == 2 and report["checked"] == 4
    assert {j["title"] for j in report["removed_jobs"]} == {"closed new", "closed saved"}

    async with maker() as s:
        left = set((await s.scalars(select(Job.title))).all())
        assert left == {"open", "broken", "applied", "other user"}
        assert (await s.scalars(select(Event))).all() == []
        checked = (await s.scalars(select(Job).where(Job.title == "open"))).one()
        assert checked.checked_at is not None


@pytest.fixture
def no_waits(monkeypatch):
    monkeypatch.setattr(availability, "LINKEDIN_DELAY", (0, 0))
    monkeypatch.setattr(availability, "LIMIT_WAIT", (0, 0))


def li_job(i: int, **kw) -> Job:
    return job(f"https://www.linkedin.com/jobs/view/{i}/", "linkedin", f"linkedin:{i}", **kw)


async def test_linkedin_limit_stops_after_several_refused_jobs(maker, no_waits):
    a, _ = await _users(maker)
    calls = []

    def limited(req):
        calls.append(str(req.url))
        return httpx.Response(429) if "linkedin" in str(req.url) else handler(req)

    async with maker() as s:
        s.add_all([li_job(4000010 + i, user_id=a) for i in range(5)])
        await s.commit()
    async with maker() as s, client(limited) as c:
        report = await availability.remove_unavailable(s, c, a)
    # Each refused job: guest API + job page, twice. Stops after MAX_LIMITED jobs in a row.
    assert report["removed"] == 0 and report["linkedin_limited"] and report["checked"] == 0
    assert len(calls) == 4 * availability.MAX_LIMITED


async def test_linkedin_job_page_used_when_guest_api_refuses(maker, no_waits):
    """The real case: guest API says 429, the public job page says "Page not found" (404) for a closed job."""
    a, _ = await _users(maker)

    def guest_limited(req):
        url = str(req.url)
        if "jobs-guest" in url:
            return httpx.Response(429)
        if url == "https://www.linkedin.com/jobs/view/4000021/":
            return httpx.Response(404, text="<title>LinkedIn</title> Page not found")
        if url == "https://www.linkedin.com/jobs/view/4000022/":
            return httpx.Response(200, text=CLOSED_LI)
        return httpx.Response(200, text=OPEN_LI)

    async with maker() as s:
        s.add_all([li_job(4000021, user_id=a, title="deleted"), li_job(4000022, user_id=a, title="closed"),
                   li_job(4000023, user_id=a, title="open")])
        await s.commit()
    async with maker() as s, client(guest_limited) as c:
        report = await availability.remove_unavailable(s, c, a)
    assert {j["title"] for j in report["removed_jobs"]} == {"deleted", "closed"}
    assert report["checked"] == 3 and not report["linkedin_limited"]


async def test_linkedin_retries_after_a_pause(maker, no_waits):
    a, _ = await _users(maker)
    calls = []

    def first_refused(req):
        calls.append(str(req.url))
        return httpx.Response(429) if len(calls) <= 2 else httpx.Response(200, text=CLOSED_LI)

    async with maker() as s:
        s.add(li_job(4000031, user_id=a))
        await s.commit()
    async with maker() as s, client(first_refused) as c:
        report = await availability.remove_unavailable(s, c, a)
    assert report["removed"] == 1 and len(calls) == 3


async def test_sweep_checks_every_user_a_few_at_a_time(maker, no_waits, monkeypatch):
    monkeypatch.setattr(availability, "SWEEP_LINKEDIN", 1)
    a, b = await _users(maker)
    async with maker() as s:
        s.add_all([li_job(4000002, user_id=a, title="a closed"), li_job(4000001, user_id=a, title="a open"),
                   job("https://careers.example.com/closed", user_id=b, title="b closed")])
        await s.commit()
    async with client() as c:
        result = await availability.sweep(maker, c)
    assert result[a] == {"checked": 1, "removed": 1} and result[b] == {"checked": 1, "removed": 1}
    async with maker() as s:
        assert set((await s.scalars(select(Job.title))).all()) == {"a open"}


async def test_find_jobs_now_removes_closed_jobs(maker, monkeypatch):
    """collect(remove_closed=True) runs the check and reports it in the run's stats."""
    a, _ = await _users(maker)
    async with maker() as s:
        s.add(job("https://careers.example.com/closed", user_id=a, title="closed"))
        s.add(job("https://careers.example.com/open", user_id=a, title="open"))
        await s.commit()

    async def no_postings(*args, **kw):
        return []

    monkeypatch.setattr(ingest, "_gather_postings", no_postings)
    async with client() as c:
        await ingest.collect(maker, [a], client=c, remove_closed=True)
    async with maker() as s:
        assert set((await s.scalars(select(Job.title))).all()) == {"open"}
        from app.models import CollectionRun
        run = (await s.scalars(select(CollectionRun))).one()
        assert run.stats["closed"]["removed"] == 1

    # The scheduled run doesn't check links
    async with maker() as s:
        s.add(job("https://careers.example.com/closed", user_id=a, title="closed again"))
        await s.commit()
    async with client() as c:
        await ingest.collect(maker, [a], client=c)
    async with maker() as s:
        assert "closed again" in set((await s.scalars(select(Job.title))).all())
