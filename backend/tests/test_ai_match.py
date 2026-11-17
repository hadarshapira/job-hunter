"""AI match grade: Claude is replaced by a fake, so these tests cost nothing and need no network."""

import anthropic
import httpx
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import Job
from app.services import ai_match
from tests.conftest import new_client, signup
from tests.test_matching import CV, JOB


@pytest.fixture
def fake_ai(monkeypatch):
    """Server has a key; every call returns a fixed grade and is recorded."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()
    calls: list[tuple[str, str]] = []

    async def fake_call(system: str, user_text: str) -> ai_match.AIGrade:
        calls.append((system, user_text))
        return ai_match.AIGrade(
            score=91, verdict="strong", summary="Core data engineering role that matches the CV.",
            strengths=["Airflow pipelines"], gaps=["No Kafka"], dealbreakers=[],
        )

    monkeypatch.setattr(ai_match, "_call", fake_call)
    yield calls
    get_settings.cache_clear()


async def _setup(c, *, ai=True) -> int:
    await c.post("/api/profile/cv", files={"file": ("cv.txt", CV.encode(), "text/plain")})
    s = (await c.get("/api/settings")).json()
    r = await c.put("/api/settings", json={**s, "ai_grading": ai})
    assert r.status_code == 200, r.text
    r = await c.post("/api/jobs", json={"title": "Senior Data Engineer", "company": "X", "description": JOB})
    return r.json()["id"]


async def test_settings_show_whether_ai_is_available(authed, fake_ai):
    s = (await authed.get("/api/settings")).json()
    assert s["ai_available"] is True and s["ai_grading"] is False


async def test_worker_grades_and_the_grade_becomes_the_score(authed, maker, fake_ai):
    job_id = await _setup(authed)
    rule_score = (await authed.get(f"/api/jobs/{job_id}")).json()["match_score"]

    assert (await ai_match.grade_pending(maker))["graded"] == 1
    job = (await authed.get(f"/api/jobs/{job_id}")).json()
    assert job["match_score"] == 91 != rule_score
    assert job["ai_match"]["verdict"] == "strong" and job["ai_match"]["stale"] is False
    assert job["match"]["skills"]  # the rule-based details are still there
    system, user_text = fake_ai[0]
    assert "Airflow" in system and "Senior Data Engineer" in user_text  # CV in the prompt, job in the message

    # Nothing changed: the next run doesn't pay for the same job again
    assert (await ai_match.grade_pending(maker))["graded"] == 0
    assert len(fake_ai) == 1

    # Saving settings re-grades with rules but keeps the still-current AI grade
    s = (await authed.get("/api/settings")).json()
    await authed.put("/api/settings", json=s)
    assert (await authed.get(f"/api/jobs/{job_id}")).json()["match_score"] == 91


async def test_changing_the_job_makes_the_ai_grade_stale(authed, maker, fake_ai):
    job_id = await _setup(authed)
    await ai_match.grade_pending(maker)
    r = await authed.patch(f"/api/jobs/{job_id}", json={"description": JOB + "\nAlso Kafka and Flink."})
    assert r.status_code == 200, r.text
    job = (await authed.get(f"/api/jobs/{job_id}")).json()
    assert job["ai_match"]["stale"] is True and job["match_score"] != 91  # back to the rule-based grade
    assert (await ai_match.grade_pending(maker))["graded"] == 1
    assert (await authed.get(f"/api/jobs/{job_id}")).json()["match_score"] == 91


async def test_off_or_no_cv_or_no_key_means_no_calls(authed, maker, fake_ai, monkeypatch):
    await _setup(authed, ai=False)
    assert (await ai_match.grade_pending(maker))["graded"] == 0

    s = (await authed.get("/api/settings")).json()
    await authed.put("/api/settings", json={**s, "ai_grading": True})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    assert (await ai_match.grade_pending(maker))["graded"] == 0
    assert fake_ai == []


async def test_closed_jobs_are_skipped(authed, maker, fake_ai):
    job_id = await _setup(authed)
    await authed.patch(f"/api/jobs/{job_id}", json={"status": "rejected"})
    assert (await ai_match.grade_pending(maker))["graded"] == 0


async def test_refusal_is_stored_and_not_retried(authed, maker, fake_ai, monkeypatch):
    job_id = await _setup(authed)

    async def refuse(system, user_text):
        fake_ai.append((system, user_text))
        raise ai_match.GradeError("The AI declined to grade this job.")

    monkeypatch.setattr(ai_match, "_call", refuse)
    await ai_match.grade_pending(maker)
    job = (await authed.get(f"/api/jobs/{job_id}")).json()
    assert job["ai_match"]["error"] and job["ai_match"]["score"] is None
    assert job["match_score"] is not None  # rule-based grade stays
    await ai_match.grade_pending(maker)
    assert len(fake_ai) == 1


async def test_network_errors_are_retried_next_run(authed, maker, fake_ai, monkeypatch):
    job_id = await _setup(authed)

    async def down(system, user_text):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))

    monkeypatch.setattr(ai_match, "_call", down)
    assert (await ai_match.grade_pending(maker)) == {"graded": 0, "failed": 1}
    async with maker() as session:
        assert (await session.get(Job, job_id)).ai_match is None


async def test_grade_now_endpoint(authed, fake_ai):
    job_id = await _setup(authed, ai=False)  # works even with the background grading off
    r = await authed.post(f"/api/jobs/{job_id}/ai-match")
    assert r.status_code == 200, r.text
    assert r.json()["match_score"] == 91 and r.json()["ai_match"]["summary"]

    async with new_client() as other:
        await signup(other, "eve@example.com")
        assert (await other.post(f"/api/jobs/{job_id}/ai-match")).status_code == 404


async def test_grade_now_needs_a_cv_and_a_key(authed, maker, fake_ai, monkeypatch):
    r = await authed.post("/api/jobs", json={"title": "Data Engineer", "description": JOB})
    job_id = r.json()["id"]
    r = await authed.post(f"/api/jobs/{job_id}/ai-match")
    assert r.status_code == 422 and "CV" in r.json()["detail"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    assert (await authed.post(f"/api/jobs/{job_id}/ai-match")).status_code == 503


async def test_users_get_their_own_cv_in_the_prompt(authed, maker, fake_ai):
    await _setup(authed)
    async with new_client() as other:
        await signup(other, "eve@example.com")
        await other.post("/api/profile/cv", files={"file": ("cv.txt", (CV + "\nEve-only line").encode(), "text/plain")})
        s = (await other.get("/api/settings")).json()
        await other.put("/api/settings", json={**s, "ai_grading": True})
        await other.post("/api/jobs", json={"title": "Data Engineer", "company": "Y", "description": JOB})
    await ai_match.grade_pending(maker)
    assert len(fake_ai) == 2
    by_company = {("Company: Y" in u): sys for sys, u in fake_ai}
    assert "Eve-only line" in by_company[True] and "Eve-only line" not in by_company[False]
    async with maker() as session:
        assert all(j.ai_match for j in (await session.scalars(select(Job))).all())


async def test_notes_go_into_the_prompt_and_trigger_a_regrade(authed, maker, fake_ai):
    await _setup(authed)
    await ai_match.grade_pending(maker)
    assert "<candidate_notes>" not in fake_ai[0][0]

    prof = (await authed.get("/api/profile")).json()
    r = await authed.put("/api/profile", json={**prof, "ai_notes": "  Not looking for team lead roles.  "})
    assert r.json()["ai_notes"] == "Not looking for team lead roles."
    assert (await ai_match.grade_pending(maker))["graded"] == 1
    assert "<candidate_notes>\nNot looking for team lead roles.\n</candidate_notes>" in fake_ai[1][0]
