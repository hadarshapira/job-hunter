import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select

from app import api_discovery
from app.collectors import boards, jsearch
from app.models import Company, GeoCache, Job, SearchCache, User, UserSettings
from app.services import geo, ingest
from app.services.filters import location_decision, title_matches
from tests.conftest import new_client, signup

TLV, HAIFA, RAMAT_GAN, BEER_SHEVA = (32.0853, 34.7818), (32.7940, 34.9896), (32.0684, 34.8248), (31.2518, 34.7913)
PLACES = {"tel aviv, israel": TLV, "tel aviv-yafo, israel": TLV, "haifa, israel": HAIFA,
          "ramat gan, israel": RAMAT_GAN, "beer sheva, israel": BEER_SHEVA}


# ---------- filters ----------

@pytest.mark.parametrize(
    "title,ok",
    [
        ("Senior Data Engineer", True),
        ("Engineer, Data Platform", True),           # word order doesn't matter
        ("Big Data Engineer (Spark)", True),
        ("Junior Data Engineer", False),             # excluded word
        ("Data Engineering Intern", False),
        ("Senior Backend Engineer", False),          # no matching phrase
        ("Data Analyst", False),
    ],
)
def test_title_matches(title, ok):
    assert title_matches(title, ["data engineer", "data platform", "big data"], ["junior", "intern"], False) is ok


def test_senior_only():
    assert title_matches("Staff Data Engineer", ["data engineer"], [], True)
    assert title_matches("Data Engineer Team Lead", ["data engineer"], [], True)
    assert not title_matches("Data Engineer", ["data engineer"], [], True)


def make_settings(**kw) -> UserSettings:
    base = dict(user_id=1, work_modes=["onsite", "hybrid", "remote"], max_km_onsite=25, max_km_hybrid=40,
                home_lat=TLV[0], home_lon=TLV[1], title_keywords=["data engineer"], exclude_keywords=[], senior_only=False)
    return UserSettings(**{**base, **kw})


def test_location_rules():
    s = make_settings()
    assert location_decision(s, "onsite", 10).ok
    assert not location_decision(s, "onsite", 30).ok           # over on-site limit
    assert location_decision(s, "hybrid", 30).ok               # hybrid limit is higher
    assert location_decision(s, "remote", 300).ok              # remote: distance doesn't matter
    assert location_decision(s, "unknown", 35).ok              # unknown uses the larger limit
    assert location_decision(s, "onsite", None).reason == "distance unknown"
    only_remote = make_settings(work_modes=["remote"])
    assert not location_decision(only_remote, "hybrid", 5).ok
    assert not location_decision(only_remote, "unknown", 5).ok
    no_home = make_settings(home_lat=None, home_lon=None)
    assert location_decision(no_home, "onsite", 100).ok        # no home set yet: don't filter by distance


# ---------- geo ----------

def test_places():
    assert geo.normalize_place("Tel Aviv-Yafo, Tel Aviv District, Israel; New York") == "tel aviv-yafo, israel"
    assert geo.normalize_place("Herzliya (Hybrid)") == "herzliya, israel"
    assert geo.in_israel("Tel Aviv, Israel") and geo.in_israel("Herzliya") and geo.in_israel("anything", "IL")
    assert not geo.in_israel("New York, NY") and not geo.in_israel("Remote - EMEA")
    assert 75 < geo.haversine_km(*TLV, *HAIFA) < 90


async def test_geocode_is_cached(maker):
    calls = []

    def handler(req: httpx.Request):
        calls.append(req.url.params["q"])
        assert "countrycodes" in str(req.url) and req.headers["user-agent"].startswith("JobHunter")
        return httpx.Response(200, json=[{"lat": "32.0684", "lon": "34.8248", "display_name": "Ramat Gan, Israel"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client, maker() as s:
        first = await geo.geocode(s, client, "Ramat Gan")
        second = await geo.geocode(s, client, "ramat gan, Israel")
    assert first == second and first[2] == "Ramat Gan, Israel"
    assert calls == ["ramat gan, israel"]


# ---------- collectors ----------

GH_BOARD = {"jobs": [
    {"id": 1, "title": "Senior Data Engineer", "location": {"name": "Tel Aviv, Israel"}, "absolute_url": "https://gh/1",
     "content": "&lt;p&gt;" + "Spark pipelines. " * 20 + "&lt;/p&gt;", "first_published": "2026-11-10T00:00:00Z"},
    {"id": 2, "title": "Data Engineer", "location": {"name": "Haifa, Israel"}, "absolute_url": "https://gh/2",
     "content": "On-site role. " * 20},
    {"id": 3, "title": "Senior Data Engineer", "location": {"name": "New York, NY"}, "absolute_url": "https://gh/3",
     "content": "US role. " * 30},
    {"id": 4, "title": "Product Manager", "location": {"name": "Tel Aviv, Israel"}, "absolute_url": "https://gh/4",
     "content": "Not data. " * 30},
]}
LEVER_BOARD = [{"id": "aaa", "text": "Data Platform Engineer", "categories": {"location": "Ramat Gan, Israel"},
                "workplaceType": "hybrid", "descriptionPlain": "Kafka and Airflow. " * 20, "lists": [],
                "hostedUrl": "https://lever/aaa", "createdAt": 1793000000000}]
ASHBY_BOARD = {"jobs": [{"id": "bbb", "title": "Senior Data Engineer", "location": "Beer Sheva, Israel",
                         "workplaceType": "Remote", "descriptionPlain": "Remote in Israel. " * 20, "jobUrl": "https://ashby/bbb"}]}
JSEARCH = {"status": "OK", "data": {"jobs": [
    {"job_id": "js1", "job_title": "Senior Data Engineer", "employer_name": "Similarweb", "job_city": "Tel Aviv-Yafo",
     "job_country": "IL", "job_description": "Build data pipelines. " * 20, "job_apply_link": "https://li/1",
     "job_latitude": TLV[0], "job_longitude": TLV[1], "job_is_remote": False, "job_publisher": "LinkedIn",
     "job_posted_at_timestamp": 1794700000},
    {"job_id": "js2", "job_title": "Senior Data Engineer", "employer_name": "Acme", "job_city": "Haifa",
     "job_country": "IL", "job_description": "Hybrid role in Haifa. " * 20, "job_apply_link": "https://li/2",
     "job_latitude": HAIFA[0], "job_longitude": HAIFA[1], "job_publisher": "Indeed"},
]}}


class FakeWeb:
    """Mock for every outside service the collectors call."""

    def __init__(self):
        self.jsearch_calls = 0
        self.nominatim_calls = 0

    def handler(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if "boards-api.greenhouse.io/v1/boards/acme/jobs" in url:
            return httpx.Response(200, json=GH_BOARD)
        if "api.lever.co/v0/postings/leverco" in url:
            return httpx.Response(200, json=LEVER_BOARD)
        if "api.ashbyhq.com/posting-api/job-board/ashbyco" in url:
            return httpx.Response(200, json=ASHBY_BOARD)
        if "jsearch.p.rapidapi.com/search-v2" in url:
            self.jsearch_calls += 1
            assert req.headers["x-rapidapi-key"] == "test-key"
            return httpx.Response(200, json=JSEARCH, headers={"x-ratelimit-requests-remaining": "150"})
        if "nominatim" in url:
            self.nominatim_calls += 1
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


@pytest.fixture
def jsearch_key(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "jsearch_api_key", "test-key")


def test_board_from_url():
    assert boards.board_from_url("https://job-boards.greenhouse.io/riskified") == ("greenhouse", "riskified")
    assert boards.board_from_url("https://boards.greenhouse.io/embed/job_board?for=wizinc") == ("greenhouse", "wizinc")
    assert boards.board_from_url("jobs.lever.co/walkme/123") == ("lever", "walkme")
    assert boards.board_from_url("https://jobs.ashbyhq.com/moonactive") == ("ashby", "moonactive")
    assert boards.board_from_url("ashby:honeybook") == ("ashby", "honeybook")
    assert boards.board_from_url("https://example.com/careers") is None


@pytest.mark.parametrize(
    "city,country,lat,expect_loc,expect_lat",
    [
        ("Tel Aviv-Yafo", "US", 32.08, "Tel Aviv-Yafo, Israel", 32.08),  # wrong country code, right coordinates
        ("Herzliya", "US", 38.9, "Herzliya, Israel", None),               # wrong coordinates: dropped, geocode instead
        ("פתח תקווה", "IL", 32.09, "פתח תקווה, Israel", 32.09),           # Hebrew city
        ("Austin", "US", 30.27, "Austin, US", 30.27),                      # really abroad
    ],
)
def test_jsearch_country_quirk(city, country, lat, expect_loc, expect_lat):
    p = jsearch.to_posting({"job_id": "x", "job_title": "Data Engineer", "job_city": city, "job_country": country,
                            "job_latitude": lat, "job_longitude": 34.8 if lat < 34 else -97.7})
    assert p.job.location == expect_loc and p.lat == expect_lat
    assert geo.in_israel(p.job.location, p.country) is (country == "IL" or "Israel" in expect_loc)


def test_jsearch_mapping():
    p = jsearch.to_posting(JSEARCH["data"]["jobs"][0])
    assert p.key == "jsearch:js1" and p.job.company == "Similarweb" and p.country == "IL"
    assert p.lat == TLV[0] and p.url == "https://li/1" and p.job.extra["publisher"] == "LinkedIn"


async def test_jsearch_cache_and_quota(maker, jsearch_key):
    web = FakeWeb()
    async with web.client() as c, maker() as s:
        assert len(await jsearch.search(s, c, "data engineer")) == 2
        assert len(await jsearch.search(s, c, "Data Engineer")) == 2  # cached, same query
        assert web.jsearch_calls == 1
        assert await jsearch.quota_remaining(s) == 150

        row = await s.get(SearchCache, "data engineer")
        row.fetched_at = datetime.now(timezone.utc) - timedelta(hours=21)  # stale
        await jsearch.search(s, c, "data engineer")
        assert web.jsearch_calls == 2

        row.quota_remaining, row.fetched_at = 10, datetime.now(timezone.utc) - timedelta(hours=21)
        with pytest.raises(jsearch.QuotaLow):
            await jsearch.search(s, c, "data engineer")
        assert web.jsearch_calls == 2


# ---------- full collection ----------

async def seed(maker, home=TLV, **settings):
    async with maker() as s:
        u = User(email=f"user{settings.pop('n', 1)}@example.com", name="")
        s.add(u)
        await s.flush()
        s.add(UserSettings(user_id=u.id, home_label="Tel Aviv", home_lat=home[0] if home else None,
                           home_lon=home[1] if home else None, **settings))
        await s.commit()
        return u.id


async def add_companies(maker):
    async with maker() as s:
        s.add_all([Company(ats="greenhouse", slug="acme", name="Acme"), Company(ats="lever", slug="leverco", name="LeverCo"),
                   Company(ats="ashby", slug="ashbyco", name="AshbyCo"), Company(ats="greenhouse", slug="gone", name="Gone")])
        await s.commit()


async def titles_for(maker, uid):
    async with maker() as s:
        rows = (await s.execute(select(Job.company, Job.title, Job.distance_km, Job.status).where(Job.user_id == uid))).all()
    return {(r.company, r.title): (r.distance_km, r.status) for r in rows}


async def test_collect_filters_per_user_and_never_duplicates(maker, fast_geo, jsearch_key):
    await add_companies(maker)
    near = await seed(maker, n=1, max_km_onsite=25, max_km_hybrid=40)                      # Tel Aviv, close jobs only
    remote_only = await seed(maker, n=2, work_modes=["remote"])
    web = FakeWeb()

    async with web.client() as c:
        result = await ingest.collect(maker, client=c)

    jobs = await titles_for(maker, near)
    assert set(jobs) == {
        ("Acme", "Senior Data Engineer"),         # Tel Aviv, 0 km
        ("LeverCo", "Data Platform Engineer"),    # Ramat Gan ~4 km, hybrid
        ("AshbyCo", "Senior Data Engineer"),      # Beer Sheva, but remote
        ("Similarweb", "Senior Data Engineer"),   # JSearch, Tel Aviv
    }, "Haifa jobs (80+ km), the New York job and the PM job must be filtered out"
    assert jobs[("LeverCo", "Data Platform Engineer")][0] < 10
    assert all(status == "new" for _, status in jobs.values())
    assert set(await titles_for(maker, remote_only)) == {("AshbyCo", "Senior Data Engineer")}
    assert "Gone" in " ".join(result["errors"])  # broken board reported, others still collected
    assert web.jsearch_calls == 4  # shared queries for both users: their top 4 title phrases

    # Second run: nothing new, cache reused, geocoding cached
    geo_calls = web.nominatim_calls
    async with web.client() as c:
        again = await ingest.collect(maker, client=c)
    assert again["added"] == {near: 0, remote_only: 0}
    assert web.jsearch_calls == 4 and web.nominatim_calls == geo_calls
    async with maker() as s:
        assert await s.scalar(select(func.count()).select_from(GeoCache)) >= 3


async def test_collect_skips_jobs_already_saved_from_a_link(maker, fast_geo, jsearch_key):
    await add_companies(maker)
    uid = await seed(maker)
    async with maker() as s:
        from app.services.dedup import dedup_key

        s.add(Job(user_id=uid, title="Senior Data Engineer", company="Similarweb", location="Tel Aviv-Yafo, IL",
                  dedup_key=dedup_key("Senior Data Engineer", "Similarweb", "Tel Aviv-Yafo, IL"), status="applied"))
        await s.commit()
    async with FakeWeb().client() as c:
        await ingest.collect(maker, client=c)
    jobs = await titles_for(maker, uid)
    assert jobs[("Similarweb", "Senior Data Engineer")][1] == "applied"  # kept, not duplicated as "new"


def test_company_names_normalize():
    from app.services.dedup import company_key, loose_key

    assert company_key("Wix.com, Inc.") == company_key("Wix") == "wix"
    assert company_key("CaliAlfa (Previously Alfabet)") == "calialfa"
    assert company_key("Check Point Software Technologies Ltd.") == "check point software"
    assert loose_key("Data Engineer - AI Core Data", "Wix.com, Inc.") == loose_key("Data Engineer – AI Core Data", "Wix")


async def test_same_job_with_city_in_hebrew_is_merged(maker, fast_geo, jsearch_key, monkeypatch):
    dup = [
        {"job_id": "w1", "job_title": "Data Engineer - AI Core Data", "employer_name": "Wix", "job_city": "Tel Aviv-Yafo",
         "job_country": "US", "job_description": "x " * 200, "job_latitude": 32.08, "job_longitude": 34.78},
        {"job_id": "w2", "job_title": "Data Engineer - AI Core Data", "employer_name": "Wix.com, Inc.",
         "job_city": "תל אביב -יפו", "job_country": "IL", "job_description": "x " * 200,
         "job_latitude": 32.09, "job_longitude": 34.79},
        {"job_id": "w3", "job_title": "Data Engineer - AI Core Data", "employer_name": "Wix", "job_city": "Haifa",
         "job_country": "IL", "job_description": "x " * 200, "job_latitude": HAIFA[0], "job_longitude": HAIFA[1]},
    ]
    monkeypatch.setitem(JSEARCH["data"], "jobs", dup)
    uid = await seed(maker, home=None)  # no distance limit, so the Haifa office is kept
    async with FakeWeb().client() as c:
        await ingest.collect(maker, client=c)
    async with maker() as s:
        rows = (await s.execute(select(Job.location).where(Job.user_id == uid, Job.company.like("Wix%")))).scalars().all()
    assert sorted(rows) == ["Haifa, Israel", "Tel Aviv-Yafo, Israel"]  # Tel Aviv twice -> once; Haifa is a different office


async def test_without_home_distance_is_not_applied(maker, fast_geo, jsearch_key):
    await add_companies(maker)
    uid = await seed(maker, home=None)
    async with FakeWeb().client() as c:
        await ingest.collect(maker, client=c)
    jobs = await titles_for(maker, uid)
    assert ("Acme", "Data Engineer") in jobs and jobs[("Acme", "Data Engineer")][0] is None  # Haifa kept


# ---------- API ----------

async def test_settings_api(authed, monkeypatch):
    async def fake_geocode(session, client, place):
        return (RAMAT_GAN[0], RAMAT_GAN[1], "Ramat Gan, Tel Aviv District, Israel") if "ramat" in place.lower() else None

    monkeypatch.setattr(api_discovery, "geocode", fake_geocode)
    s = (await authed.get("/api/settings")).json()
    assert s["work_modes"] == ["onsite", "hybrid", "remote"] and "data engineer" in s["title_keywords"]

    body = {**s, "home_label": "Ramat Gan", "work_modes": ["hybrid", "remote", "bogus"], "max_km_hybrid": 30,
            "title_keywords": ["Data Engineer", "data engineer", " Big  Data "], "senior_only": True}
    out = (await authed.put("/api/settings", json=body)).json()
    assert out["home_lat"] == RAMAT_GAN[0] and out["work_modes"] == ["hybrid", "remote"]
    assert out["title_keywords"] == ["Data Engineer", "Big Data"] and out["senior_only"]

    bad = await authed.put("/api/settings", json={**body, "home_label": "Atlantis"})
    assert bad.status_code == 422 and "Couldn't find" in bad.json()["detail"]
    assert (await authed.put("/api/settings", json={**body, "work_modes": []})).status_code == 422


async def test_settings_are_private(maker):
    async with new_client() as a, new_client() as b:
        await signup(a, "a@example.com")
        await signup(b, "b@example.com")
        s = (await a.get("/api/settings")).json()
        await a.put("/api/settings", json={**s, "title_keywords": ["analytics engineer"]})
        assert (await b.get("/api/settings")).json()["title_keywords"] != ["analytics engineer"]


async def test_companies_api(maker, monkeypatch):
    async def fake_fetch(client, company):
        if company.slug == "broken":
            raise httpx.HTTPStatusError("404", request=httpx.Request("GET", "x"), response=httpx.Response(404))
        return []

    monkeypatch.setattr(boards, "fetch_board", fake_fetch)
    async with new_client() as a, new_client() as b:
        await signup(a, "a@example.com")
        await signup(b, "b@example.com")
        r = await a.post("/api/companies", json={"board": "https://jobs.lever.co/newco", "name": "NewCo"})
        assert r.status_code == 201 and r.json()["mine"]
        cid = r.json()["id"]
        assert (await a.post("/api/companies", json={"board": "lever:newco"})).status_code == 409
        assert (await a.post("/api/companies", json={"board": "https://example.com/jobs"})).status_code == 422
        assert (await a.post("/api/companies", json={"board": "greenhouse:broken"})).status_code == 422

        listed = (await b.get("/api/companies")).json()
        assert any(c["name"] == "NewCo" and not c["mine"] for c in listed)  # shared list
        assert (await b.delete(f"/api/companies/{cid}")).status_code == 404   # only the adder can remove
        assert (await a.delete(f"/api/companies/{cid}")).status_code == 204


async def test_collect_endpoint(authed, monkeypatch):
    started = []

    async def fake_run(user_id):
        started.append(user_id)

    monkeypatch.setattr(api_discovery, "_run_for", fake_run)
    status = (await authed.get("/api/collect")).json()
    assert status["running"] is False and status["last_started"] is None
    assert (await authed.post("/api/collect")).json() == {"started": True}
    assert len(started) == 1


async def test_collect_uses_only_chosen_sources(maker, fast_geo, jsearch_key):
    await add_companies(maker)
    lever_only = await seed(maker, n=1, sources=["lever"])
    web = FakeWeb()
    async with web.client() as c:
        await ingest.collect(maker, client=c)
    assert set(await titles_for(maker, lever_only)) == {("LeverCo", "Data Platform Engineer")}
    assert web.jsearch_calls == 0  # nobody wants web search, so no quota is spent


async def test_sources_setting_api(authed):
    s = (await authed.get("/api/settings")).json()
    assert s["sources"] == ["linkedin", "jsearch", "greenhouse", "lever", "ashby"]
    out = (await authed.put("/api/settings", json={**s, "sources": ["ashby", "greenhouse", "bogus"]})).json()
    assert out["sources"] == ["greenhouse", "ashby"]
    assert (await authed.put("/api/settings", json={**s, "sources": []})).status_code == 422


async def test_source_filter_and_counts(authed, maker):
    me = (await authed.get("/api/auth/me")).json()["id"]
    async with maker() as s:
        for i, src in enumerate(["greenhouse", "greenhouse", "jsearch", "lever"]):
            s.add(Job(user_id=me, title=f"Data Engineer {i}", source=src, dedup_key=f"k{i}", status="new"))
        await s.commit()
    await authed.post("/api/jobs", json={"title": "Saved by hand"})
    assert (await authed.get("/api/jobs/sources")).json() == {"greenhouse": 2, "jsearch": 1, "lever": 1, "manual": 1}
    assert (await authed.get("/api/jobs/sources?status=new")).json() == {"greenhouse": 2, "jsearch": 1, "lever": 1}
    got = (await authed.get("/api/jobs?source=greenhouse&source=lever")).json()
    assert len(got) == 3 and {j["source"] for j in got} == {"greenhouse", "lever"}

    async with new_client() as other:
        await signup(other, "eve@example.com")
        assert (await other.get("/api/jobs/sources")).json() == {}
