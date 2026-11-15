"""LinkedIn search collector, with synthetic LinkedIn HTML (no network)."""

import httpx
import pytest
from sqlalchemy import select

from app.collectors import linkedin
from app.models import Job
from app.services import geo, ingest
from app.services.filters import title_matches
from tests.test_discovery import PLACES, TLV, seed


def card(job_id: str, title: str, company: str, location: str, posted: str = "2026-11-14") -> str:
    return f"""<li><div class="base-card base-search-card job-search-card" data-entity-urn="urn:li:jobPosting:{job_id}">
      <a class="base-card__full-link" href="https://il.linkedin.com/jobs/view/x-{job_id}?trk=1"></a>
      <div class="base-search-card__info">
        <h3 class="base-search-card__title"> {title} </h3>
        <h4 class="base-search-card__subtitle"><a>{company}</a></h4>
        <div class="base-search-card__metadata">
          <span class="job-search-card__location">{location}</span>
          <time class="job-search-card__listdate" datetime="{posted}">1 day ago</time>
        </div></div></div></li>"""


def job_page(title: str, company: str, location: str, text: str) -> str:
    return f"""<html><body>
      <h1 class="top-card-layout__title">{title}</h1>
      <a class="topcard__org-name-link">{company}</a>
      <span class="topcard__flavor topcard__flavor--bullet">{location}</span>
      <div class="show-more-less-html__markup"><p>{text}</p></div>
    </body></html>"""


CARDS = {
    "111": ("Senior Data Engineer", "Wix", "Tel Aviv-Yafo, Tel Aviv District, Israel"),
    "222": ("Product Manager", "Wix", "Tel Aviv-Yafo, Tel Aviv District, Israel"),
    "333": ("מהנדס/ת דאטה", "Bank Hapoalim", "Central District, Israel"),
    "444": ("Data Engineering Team Lead", "Monday", "Haifa, Haifa District, Israel"),
}


class FakeLinkedIn:
    def __init__(self, limit_after: int | None = None):
        self.search_calls = 0
        self.detail_calls = 0
        self.limit_after = limit_after

    def handler(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if "seeMoreJobPostings/search" in url:
            self.search_calls += 1
            if self.limit_after is not None and self.search_calls > self.limit_after:
                return httpx.Response(429)
            p = req.url.params
            assert p["location"] == "Israel" and p["f_TPR"] == "r604800"
            if p.get("start") != "0":
                return httpx.Response(200, text="")
            ids = {None: ["111", "222", "333", "444"], "3": ["111"], "2": ["333"]}[p.get("f_WT")]
            return httpx.Response(200, text="".join(card(i, *CARDS[i]) for i in ids))
        if "jobs-guest/jobs/api/jobPosting/" in url:
            self.detail_calls += 1
            job_id = url.rstrip("/").rsplit("/", 1)[-1]
            title, company, location = CARDS[job_id]
            return httpx.Response(200, text=job_page(title, company, location, "Python, Spark and Airflow. " * 20))
        if "nominatim" in url:
            q = req.url.params["q"]
            if q in PLACES:
                lat, lon = PLACES[q]
                return httpx.Response(200, json=[{"lat": str(lat), "lon": str(lon), "display_name": q.title()}])
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def fast_geo(monkeypatch):
    monkeypatch.setattr(geo, "_last_call", 0.0)

    async def no_sleep(_):
        return None

    monkeypatch.setattr(geo.asyncio, "sleep", no_sleep)


def test_parse_cards():
    cards = linkedin.parse_cards(card("111", *CARDS["111"]) + card("333", *CARDS["333"]))
    assert [c.id for c in cards] == ["111", "333"]
    assert cards[0].title == "Senior Data Engineer" and cards[0].company == "Wix"
    assert cards[0].location.startswith("Tel Aviv") and cards[0].posted.isoformat() == "2026-11-14"
    assert cards[1].url == "https://www.linkedin.com/jobs/view/333/"


@pytest.mark.parametrize("title,ok", [
    ("Data Engineering Team Lead", True),     # "engineer" also matches "engineering"
    ("Senior Data Engineers", True),
    ("מהנדס/ת דאטה", True),                    # Hebrew title
    ("מהנדס נתונים בכיר", True),
    ("Database Administrator", False),         # "data" doesn't match "database"
    ("Data Engineering Internship", False),    # "intern" also excludes "internship"
    ("Internal Data Platform Engineer", True), # ...but not "internal"
])
def test_wider_title_matching(title, ok):
    assert title_matches(title, ["data engineer", "data platform"], ["intern"], False) is ok


async def test_linkedin_collection(maker, fast_geo):
    uid = await seed(maker, n=1, sources=["linkedin"], work_modes=["hybrid", "remote"], max_km_hybrid=60)
    web = FakeLinkedIn()
    async with web.client() as c:
        await ingest.collect(maker, client=c)

    async with maker() as s:
        jobs = {j.title: j for j in (await s.scalars(select(Job).where(Job.user_id == uid))).all()}
    # Product Manager: wrong title, never read. Team Lead in Haifa: work mode unknown, ~80 km > 60 km limit.
    assert set(jobs) == {"Senior Data Engineer", "מהנדס/ת דאטה"}
    assert web.detail_calls == 3  # only titles someone searches for
    wix = jobs["Senior Data Engineer"]
    assert wix.source == "linkedin" and wix.work_mode == "hybrid"  # from LinkedIn's Hybrid filter
    assert wix.url == "https://www.linkedin.com/jobs/view/111/" and "Airflow" in wix.description
    assert wix.distance_km is not None and wix.distance_km < 5
    bank = jobs["מהנדס/ת דאטה"]
    assert bank.work_mode == "remote" and bank.lat is None  # "Central District" is too vague for a distance

    async with maker() as s:
        from app.models import CollectionRun
        run = await s.scalar(select(CollectionRun).where(CollectionRun.user_id == uid))
    li = run.stats["sources"]["linkedin"]
    assert li["found"] == 3 and li["added"] == 2 and li["location"] == 1
    assert run.stats["linkedin"]["linkedin_title_skip"] == 1

    # Second run: nothing new, and no job page is read again
    async with web.client() as c:
        again = await ingest.collect(maker, client=c)
    assert again["added"] == {uid: 0} and web.detail_calls == 3


async def test_linkedin_rate_limit_keeps_what_it_has(maker, fast_geo):
    uid = await seed(maker, n=1, sources=["linkedin"])
    web = FakeLinkedIn(limit_after=1)
    async with web.client() as c:
        result = await ingest.collect(maker, client=c)
    assert any("LinkedIn is limiting" in e for e in result["errors"])
    async with maker() as s:
        titles = set((await s.scalars(select(Job.title).where(Job.user_id == uid))).all())
    assert "Senior Data Engineer" in titles  # first page was kept
