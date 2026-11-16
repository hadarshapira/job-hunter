import pytest

from app.models import Job, UserProfile, UserSettings
from app.services import matching
from app.services import skills as sk
from tests.conftest import new_client, signup

CV = """Dana Cohen - Senior Data Engineer
Experience
Acme Data, Senior Data Engineer 2020 - Present
Built batch and streaming pipelines with Python, PySpark and Airflow on AWS (S3, EMR, Glue jobs).
Modeled the warehouse in Snowflake with dbt. Kafka for event ingestion. Docker, Kubernetes, Terraform.
Widgets Ltd, Data Engineer 03/2017 - 12/2019
SQL, PostgreSQL, Hadoop and Hive. CI/CD with Jenkins. Git.
Education
B.Sc. Computer Science, Tel Aviv University 2013 - 2017
"""

JOB = """About the role
You will build our data platform.
Requirements
5+ years of experience as a Data Engineer
Strong Python and SQL
Hands-on with Spark and Airflow
Experience with BigQuery or another cloud warehouse, GCP
Nice to have
Flink
Kafka
Terraform
"""


def test_find_skills_in_cv():
    found = set(sk.find_skills(CV))
    assert {"Python", "Spark", "Airflow", "AWS", "Snowflake", "dbt", "Kafka", "SQL", "PostgreSQL", "Glue", "EMR"} <= found
    assert "Java" not in found and "Go" not in found and "R" not in found


def test_tricky_words_are_not_skills():
    text = "We glue teams together. Ray of light. Go to market strategy. NoSQL, MySQL, PostgreSQL. JavaScript."
    found = set(sk.find_skills(text))
    assert "Glue" not in found and "Dask/Ray" not in found and "Go" not in found
    assert "SQL" not in found  # only appears inside other names
    assert "Java" not in found and "TypeScript/JavaScript" in found


def test_job_skills_required_vs_nice():
    needs = sk.job_skills(JOB)
    assert needs["Python"] == needs["Spark"] == needs["BigQuery"] == needs["GCP"] == "required"
    assert needs["Flink"] == needs["Kafka"] == needs["Terraform"] == "nice"
    inline = sk.job_skills("Requirements\nPython\nExperience with dbt - an advantage")
    assert inline == {"Python": "required", "dbt": "nice"}


def test_one_line_posting_is_split_into_bullets():
    text = ("Requirements - 5+ years of experience. - Strong Spark (Spark strongly preferred). - Python and SQL. "
            "- PostgreSQL and OpenSearch - a significant advantage. - Kubernetes.")
    needs = sk.job_skills(text)
    assert needs["Spark"] == needs["Python"] == needs["Kubernetes"] == "required"
    assert needs["Elasticsearch"] == needs["PostgreSQL"] == "nice"
    assert sk.required_years(text) == 5


def test_years():
    assert sk.required_years(JOB) == 5
    assert sk.required_years("3+ years with Spark\n6+ years of experience in data engineering") == 6
    assert sk.required_years("No numbers here") is None
    # 2017-2019 and 2020-2026 (education 2013-2017 ignored) = 2 + 6
    assert sk.cv_years(CV, 2026) == 8


def make_job(**kw) -> Job:
    base = dict(user_id=1, title="Senior Data Engineer", description=JOB, work_mode="hybrid", distance_km=12.0)
    return Job(**{**base, **kw})


def settings() -> UserSettings:
    return UserSettings(user_id=1, work_modes=["onsite", "hybrid", "remote"], max_km_onsite=25, max_km_hybrid=40,
                        home_lat=32.08, home_lon=34.78, title_keywords=["data engineer"], exclude_keywords=[])


def test_score_strong_vs_weak_profile():
    strong = UserProfile(user_id=1, skills=sk.find_skills(CV), years_experience=8)
    weak = UserProfile(user_id=1, skills=["Java", "MySQL"], years_experience=2)
    s = settings()
    good, bad = matching.score_job(make_job(), strong, s), matching.score_job(make_job(), weak, s)
    assert good["score"] >= 75 > 40 >= bad["score"]
    rows = {r["skill"]: r for r in good["skills"]}
    assert rows["Python"]["status"] == "have"
    assert rows["BigQuery"]["status"] == "similar" and "Snowflake" in rows["BigQuery"]["via"]
    assert rows["GCP"]["status"] == "similar"  # AWS is the same group
    assert rows["Flink"]["need"] == "nice" and rows["Flink"]["status"] == "missing"
    # Missing required skills are listed first
    assert good["skills"][0]["need"] == "required"
    parts = {p["key"]: p for p in good["parts"]}
    assert parts["experience"]["score"] == 100 and parts["location"]["score"] == 100


def test_no_profile_means_no_score():
    assert matching.score_job(make_job(), None, settings()) is None
    assert matching.score_job(make_job(), UserProfile(user_id=1, skills=[]), settings()) is None


def test_parts_without_data_are_skipped():
    p = UserProfile(user_id=1, skills=["Python"], years_experience=None)
    r = matching.score_job(make_job(description="Short text", title="Data Engineer"), p, None)
    assert r["parts"] == [] and r["score"] is None and r["notes"]
    r2 = matching.score_job(make_job(description="Requirements\nPython and Spark", title="Data Engineer"), p, settings())
    assert {x["key"] for x in r2["parts"]} == {"skills", "role", "location"}
    assert r2["score"] is not None


# ---------- API ----------

async def test_cv_upload_grades_jobs(authed):
    r = await authed.post("/api/jobs", json={"title": "Senior Data Engineer", "company": "X", "description": JOB})
    job_id = r.json()["id"]
    assert r.json()["match"] is None  # no profile yet

    r = await authed.post("/api/profile/cv", files={"file": ("cv.txt", CV.encode(), "text/plain")})
    assert r.status_code == 200, r.text
    prof = r.json()
    assert "Airflow" in prof["skills"] and prof["years_experience"] == prof["cv_years_guess"]
    assert prof["rescored"] == 1

    job = (await authed.get(f"/api/jobs/{job_id}")).json()
    assert job["match_score"] is not None and job["match"]["skills"]

    # Editing the profile re-grades: dropping skills lowers the grade
    r = await authed.put("/api/profile", json={"skills": ["python", "Bigquery"], "years_experience": 1})
    assert r.json()["skills"] == ["Python", "BigQuery"]  # canonical spelling
    lower = (await authed.get(f"/api/jobs/{job_id}")).json()["match_score"]
    assert lower < job["match_score"]

    # New jobs are graded on creation, and the list can sort by grade
    await authed.post("/api/jobs", json={"title": "Frontend Developer", "company": "Y", "description": "React and CSS"})
    listed = (await authed.get("/api/jobs?sort=match")).json()
    scores = [j["match_score"] for j in listed]
    assert None not in scores and scores == sorted(scores, reverse=True)


async def test_bad_cv_files(authed):
    r = await authed.post("/api/profile/cv", files={"file": ("cv.exe", b"MZ" * 100, "application/octet-stream")})
    assert r.status_code == 422
    r = await authed.post("/api/profile/cv", files={"file": ("cv.txt", b"too short", "text/plain")})
    assert r.status_code == 422


async def test_match_endpoint_is_per_user(authed, maker):
    r = await authed.post("/api/jobs", json={"title": "Data Engineer", "description": JOB})
    job_id = r.json()["id"]
    await authed.put("/api/profile", json={"skills": ["Python"], "years_experience": 5})
    r = await authed.post(f"/api/jobs/{job_id}/match")
    assert r.status_code == 200 and r.json()["match_score"] is not None

    async with new_client() as other:
        await signup(other, "eve@example.com")
        assert (await other.post(f"/api/jobs/{job_id}/match")).status_code == 404
        assert (await other.get("/api/profile")).json()["skills"] == []


def test_job_skills_cache_returns_a_fresh_dict():
    # job_skills is cached; changing one result must not change what the next caller gets
    first = sk.job_skills("Requirements\nPython and Spark")
    first["Python"] = "nice"
    assert sk.job_skills("Requirements\nPython and Spark") == {"Python": "required", "Spark": "required"}


def test_plain_aliases_still_need_word_boundaries():
    assert sk.find_skills("We use node.js and Tableau") == ["TypeScript/JavaScript", "BI tools"]
    assert sk.find_skills("tableaux, sparkle, pythonic") == []
