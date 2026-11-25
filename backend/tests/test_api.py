from app import api as api_module
from app.services.importer import ParsedJob


async def test_requires_login(client):
    assert (await client.get("/api/jobs")).status_code == 401
    assert (await client.get("/api/stats")).status_code == 401


async def test_create_and_track_job(authed):
    r = await authed.post("/api/jobs", json={"title": "Senior Data Engineer", "company": "Acme", "location": "Tel Aviv"})
    assert r.status_code == 201
    job = r.json()
    assert job["status"] == "saved"
    assert job["events"][0]["kind"] == "created"

    r = await authed.patch(f"/api/jobs/{job['id']}", json={"status": "applied"})
    job = r.json()
    assert job["status"] == "applied"
    assert job["applied_at"] and job["follow_up_on"]
    assert any(e["kind"] == "status" for e in job["events"])

    r = await authed.post(f"/api/jobs/{job['id']}/notes", json={"text": "Talked to recruiter"})
    assert any(e["text"] == "Talked to recruiter" for e in r.json()["events"])

    r = await authed.patch(f"/api/jobs/{job['id']}", json={"status": "interview"})
    assert r.json()["follow_up_on"] is None

    stats = (await authed.get("/api/stats")).json()
    assert stats["applied_total"] == 1 and stats["responded"] == 1
    assert stats["by_status"] == {"interview": 1}

    listed = (await authed.get("/api/jobs", params={"status": "interview"})).json()
    assert len(listed) == 1
    assert (await authed.get("/api/jobs", params={"q": "acme"})).json()[0]["id"] == job["id"]


async def test_import_and_dedup(authed, monkeypatch):
    async def fake_fetch(url):
        return ParsedJob(title="Senior Data Engineer", company="Acme", location="Tel Aviv, IL", description="Spark")

    monkeypatch.setattr(api_module, "fetch_and_parse", fake_fetch)
    r1 = (await authed.post("/api/jobs/import", json={"url": "https://boards.greenhouse.io/acme/jobs/1"})).json()
    assert not r1["duplicate"] and r1["job"]["source"] == "link"

    # Same URL again
    r2 = (await authed.post("/api/jobs/import", json={"url": "https://boards.greenhouse.io/acme/jobs/1"})).json()
    assert r2["duplicate"] and r2["job"]["id"] == r1["job"]["id"]

    # Same job, different site
    r3 = (await authed.post("/api/jobs/import", json={"url": "https://www.linkedin.com/jobs/view/123"})).json()
    assert r3["duplicate"] and r3["job"]["id"] == r1["job"]["id"]


async def test_company_filter(authed):
    for title, company in [("DE 1", "Acme"), ("DE 2", "acme "), ("DE 3", "Globex"), ("DE 4", "Northwind"), ("DE 5", "")]:
        r = await authed.post("/api/jobs", json={"title": title, "company": company})
        assert r.status_code == 201, r.text

    async def titles(**params):
        return {j["title"] for j in (await authed.get("/api/jobs", params=params)).json()}

    # Company list: case/space-insensitive, most jobs first, blank company left out
    companies = (await authed.get("/api/jobs/companies")).json()
    assert [(c["name"].lower(), c["count"]) for c in companies] == [("acme", 2), ("globex", 1), ("northwind", 1)]
    assert (await authed.get("/api/company-filter")).json() == {"mode": "", "companies": []}

    # Show only (duplicates removed, spaces trimmed)
    r = await authed.put("/api/company-filter", json={"mode": "only", "companies": ["ACME", "Acme", " Globex "]})
    assert r.json() == {"mode": "only", "companies": ["ACME", "Globex"]}
    assert await titles() == {"DE 1", "DE 2", "DE 3"}
    assert sum((await authed.get("/api/jobs/sources")).json().values()) == 3
    # The company list still shows every company, so one can be picked again
    assert len((await authed.get("/api/jobs/companies")).json()) == 3

    # Hide (jobs without a company stay)
    await authed.put("/api/company-filter", json={"mode": "hide", "companies": ["acme"]})
    assert await titles() == {"DE 3", "DE 4", "DE 5"}
    assert await titles(q="de") == {"DE 3", "DE 4", "DE 5"}

    # Off
    await authed.put("/api/company-filter", json={"mode": "", "companies": []})
    assert len(await titles()) == 5

    assert (await authed.put("/api/company-filter", json={"mode": "all", "companies": []})).status_code == 422


async def test_company_filter_new_badge(authed, maker):
    from sqlalchemy import update

    from app.models import Job

    for company in ("Acme", "Globex"):
        await authed.post("/api/jobs", json={"title": "DE", "company": company})
    async with maker() as s:
        await s.execute(update(Job).values(status="new"))
        await s.commit()
    assert (await authed.get("/api/stats")).json()["new"] == 2
    await authed.put("/api/company-filter", json={"mode": "hide", "companies": ["globex"]})
    assert (await authed.get("/api/stats")).json()["new"] == 1


async def test_company_filter_is_per_user(maker):
    from tests.conftest import new_client, signup

    async with new_client() as a, new_client() as b:
        await signup(a, "a@example.com")
        await signup(b, "b@example.com")
        await a.post("/api/jobs", json={"title": "A job", "company": "Acme"})
        await b.post("/api/jobs", json={"title": "B job", "company": "Acme"})
        await a.put("/api/company-filter", json={"mode": "hide", "companies": ["Acme"]})
        assert (await a.get("/api/jobs")).json() == []
        assert [j["title"] for j in (await b.get("/api/jobs")).json()] == ["B job"]
        assert (await b.get("/api/company-filter")).json()["mode"] == ""
        assert [c["count"] for c in (await b.get("/api/jobs/companies")).json()] == [1]
