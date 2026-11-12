from app import api as api_module
from app.services.importer import ParsedJob


async def test_requires_login(client):
    assert (await client.get("/api/jobs")).status_code == 401
    assert (await client.post("/api/auth/login", json={"password": "nope"})).status_code == 401


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
