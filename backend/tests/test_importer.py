from app.models import WorkMode
from app.services.dedup import dedup_key
from app.services.importer import guess_work_mode, parse_job_html

JSONLD_PAGE = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting",
 "title":"Senior Data Engineer",
 "hiringOrganization":{"@type":"Organization","name":"Acme Data Ltd"},
 "jobLocation":{"@type":"Place","address":{"addressLocality":"Tel Aviv","addressCountry":"IL"}},
 "datePosted":"2026-11-01T08:00:00Z",
 "baseSalary":{"currency":"ILS","value":{"minValue":35000,"maxValue":45000,"unitText":"MONTH"}},
 "description":"<p>Build pipelines with <b>Spark</b> and Airflow.</p><ul><li>Kafka</li><li>dbt</li></ul><p>Hybrid, 3 days in office.</p>"}
</script></head><body></body></html>
"""

GRAPH_PAGE = """
<script type="application/ld+json">
{"@graph":[{"@type":"WebSite","name":"x"},{"@type":["JobPosting"],"title":"Data Engineer","jobLocationType":"TELECOMMUTE",
 "hiringOrganization":"Remote Co","description":"plain text"}]}
</script>
"""

META_PAGE = """
<html><head><title>Fallback</title>
<meta property="og:title" content="Big Data Engineer at Foo">
<meta property="og:site_name" content="Foo Careers">
<meta name="description" content="Remote-friendly role">
</head></html>
"""


def test_parses_jsonld_job_posting():
    job = parse_job_html(JSONLD_PAGE)
    assert job and job.complete
    assert job.title == "Senior Data Engineer"
    assert job.company == "Acme Data Ltd"
    assert job.location == "Tel Aviv, IL"
    assert job.salary == "35000-45000 ILS MONTH"
    assert job.posted_at.isoformat() == "2026-11-01"
    assert "• Kafka" in job.description and "Spark" in job.description
    assert job.work_mode == WorkMode.hybrid


def test_parses_graph_and_telecommute():
    job = parse_job_html(GRAPH_PAGE)
    assert job.title == "Data Engineer"
    assert job.company == "Remote Co"
    assert job.work_mode == WorkMode.remote


def test_meta_fallback_is_incomplete():
    job = parse_job_html(META_PAGE)
    assert job.title == "Big Data Engineer at Foo"
    assert not job.complete
    assert job.work_mode == WorkMode.remote


def test_no_data_returns_none():
    assert parse_job_html("<html><body>nothing</body></html>") is None


def test_work_mode_hebrew():
    assert guess_work_mode("משרה במודל היברידי") == WorkMode.hybrid
    assert guess_work_mode("עבודה מהבית") == WorkMode.remote
    assert guess_work_mode("Hybrid role") == WorkMode.hybrid


def test_dedup_key_normalizes():
    a = dedup_key("Senior Data Engineer", "Acme Data Ltd.", "Tel Aviv, Israel")
    b = dedup_key("senior data engineer ", "ACME Data", "Tel Aviv")
    assert a == b
