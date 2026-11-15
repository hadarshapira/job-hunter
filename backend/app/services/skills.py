"""Data-engineering skills taxonomy: find skills in CV and job text.

Each skill has a display name, regex aliases, and a group. Skills in the same group count as
"similar" when matching (a job asking for BigQuery is partly covered by Snowflake experience).
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Skill:
    name: str
    group: str
    patterns: tuple[str, ...]
    case_sensitive: bool = False


def _s(name: str, group: str, *aliases: str, cs: bool = False) -> Skill:
    pats = aliases or (re.escape(name),)
    return Skill(name, group, tuple(pats), cs)


# Group names are shown to the user ("similar: you know Airflow (orchestration)")
SKILLS: list[Skill] = [
    # Languages
    _s("Python", "language", r"python", r"pyspark"),
    _s("SQL", "sql", r"sql(?![\s-]*server)", r"t-sql", r"pl/sql"),
    _s("Scala", "jvm language"),
    _s("Java", "jvm language", r"java(?!\s*script)"),
    _s("Kotlin", "jvm language"),
    _s("Go", "language", r"golang", r"Go(?=\s*(?:,|/|\)|\band\b|lang))", cs=True),
    _s("Bash", "language", r"bash", r"shell scripting"),
    _s("TypeScript/JavaScript", "language", r"typescript", r"javascript", r"node\.?js"),
    _s("R", "language", r"(?<![\w/])R(?=\s*(?:,|/|\)|\band\b))", cs=True),
    # Big data processing
    _s("Spark", "distributed processing", r"spark", r"pyspark", r"spark\s*sql"),
    _s("Hadoop", "distributed processing", r"hadoop", r"hdfs", r"mapreduce", r"yarn"),
    _s("Hive", "distributed processing", r"hive"),
    _s("Presto/Trino", "query engine", r"presto", r"trino", r"starburst"),
    _s("Athena", "query engine", r"athena"),
    _s("Flink", "stream processing", r"flink"),
    _s("Spark Streaming", "stream processing", r"spark\s*(?:structured\s*)?streaming"),
    _s("Kafka Streams", "stream processing", r"kafka\s*streams", r"ksql(?:db)?"),
    _s("Beam/Dataflow", "stream processing", r"apache beam", r"dataflow"),
    _s("Dask/Ray", "distributed processing", r"dask", r"\bray(?:\.io| cluster| serve| tune| data)\b", r"\bRay(?=\s*(?:,|/|\)|\band\b))"),
    _s("Pandas", "python data", r"pandas", r"polars"),
    # Messaging / streaming platforms
    _s("Kafka", "messaging", r"kafka(?!\s*streams)", r"confluent"),
    _s("Kinesis", "messaging", r"kinesis"),
    _s("Pub/Sub", "messaging", r"pub\s*/\s*sub", r"pubsub"),
    _s("RabbitMQ", "messaging", r"rabbitmq", r"rabbit mq"),
    _s("Pulsar", "messaging", r"pulsar"),
    _s("SQS/SNS", "messaging", r"\bsqs\b", r"\bsns\b"),
    # Orchestration
    _s("Airflow", "orchestration", r"airflow", r"\bmwaa\b", r"cloud composer"),
    _s("Dagster", "orchestration"),
    _s("Prefect", "orchestration"),
    _s("Luigi", "orchestration"),
    _s("Argo Workflows", "orchestration", r"argo\s*workflows?"),
    _s("Step Functions", "orchestration", r"step functions"),
    # Transformation
    _s("dbt", "transformation", r"\bdbt\b"),
    _s("ETL/ELT", "transformation", r"\betl\b", r"\belt\b", r"data pipelines?"),
    # Warehouses / lakehouse
    _s("Snowflake", "warehouse"),
    _s("BigQuery", "warehouse", r"big\s*query"),
    _s("Redshift", "warehouse"),
    _s("Databricks", "lakehouse", r"databricks"),
    _s("Synapse", "warehouse", r"synapse"),
    _s("ClickHouse", "olap database", r"click\s*house"),
    _s("Druid/Pinot", "olap database", r"\bdruid\b", r"\bpinot\b"),
    _s("Vertica", "olap database"),
    _s("Delta Lake", "table format", r"delta\s*lake"),
    _s("Iceberg", "table format", r"iceberg"),
    _s("Hudi", "table format", r"\bhudi\b"),
    _s("Parquet/Avro", "file format", r"parquet", r"\bavro\b", r"\borc\b"),
    _s("Data lake", "storage", r"data\s*lake(?:house)?s?"),
    # Databases
    _s("PostgreSQL", "relational database", r"postgres(?:ql)?"),
    _s("MySQL", "relational database", r"mysql", r"mariadb"),
    _s("SQL Server", "relational database", r"sql\s*server", r"mssql"),
    _s("Oracle", "relational database", r"oracle"),
    _s("MongoDB", "nosql database", r"mongo\s*db", r"\bmongo\b"),
    _s("Cassandra", "nosql database", r"cassandra", r"scylla"),
    _s("DynamoDB", "nosql database", r"dynamo\s*db"),
    _s("Redis", "nosql database", r"\bredis\b"),
    _s("Elasticsearch", "search database", r"elastic\s*search", r"opensearch", r"\belk\b"),
    _s("Vector databases", "search database", r"vector\s*(?:db|database|store)s?", r"pinecone", r"pgvector", r"weaviate", r"milvus"),
    # Cloud
    _s("AWS", "cloud", r"\baws\b", r"amazon web services"),
    _s("GCP", "cloud", r"\bgcp\b", r"google cloud"),
    _s("Azure", "cloud", r"azure"),
    _s("S3", "object storage", r"\bs3\b"),
    _s("GCS", "object storage", r"\bgcs\b", r"google cloud storage"),
    _s("EMR", "managed big data", r"\bemr\b"),
    _s("Glue", "managed big data", r"aws glue", r"glue (?:jobs?|catalog|etl)"),
    _s("Dataproc", "managed big data", r"dataproc"),
    _s("Lambda/Serverless", "serverless", r"aws lambda", r"\blambda functions?\b", r"serverless", r"cloud functions"),
    # Infra / DevOps
    _s("Docker", "containers", r"docker", r"containeri[sz]"),
    _s("Kubernetes", "containers", r"kubernetes", r"\bk8s\b", r"\beks\b", r"\bgke\b", r"\baks\b"),
    _s("Terraform", "infrastructure as code", r"terraform", r"pulumi", r"cloudformation"),
    _s("CI/CD", "ci/cd", r"ci\s*/\s*cd", r"github actions", r"jenkins", r"gitlab ci", r"circleci"),
    _s("Git", "version control", r"\bgit\b", r"github", r"gitlab"),
    _s("Linux", "os", r"linux", r"unix"),
    # Data quality, governance, observability
    _s("Data quality", "data quality", r"data quality", r"great expectations", r"\bsoda\b", r"monte carlo"),
    _s("Data modeling", "data modeling", r"data model(?:l)?ing", r"dimensional model", r"star schema", r"data vault", r"kimball"),
    _s("Data governance", "governance", r"data governance", r"data catalog", r"datahub", r"unity catalog", r"lineage"),
    _s("Monitoring", "observability", r"prometheus", r"grafana", r"datadog", r"observability"),
    # BI / analytics
    _s("BI tools", "bi", r"tableau", r"looker", r"power\s*bi", r"superset", r"metabase", r"quicksight"),
    # ML / AI
    _s("Machine learning", "ml", r"machine learning", r"\bml\b", r"mlops", r"feature store"),
    _s("LLM/GenAI", "ml", r"\bllms?\b", r"gen\s*ai", r"generative ai", r"\brag\b", r"langchain"),
    # APIs and architecture
    _s("REST APIs", "backend", r"rest(?:ful)?\s*apis?", r"fastapi", r"flask", r"django", r"microservices?"),
    _s("Real-time streaming", "streaming concept", r"real[\s-]*time", r"streaming", r"event[\s-]*driven"),
    _s("Distributed systems", "architecture", r"distributed systems?", r"high[\s-]*scale", r"large[\s-]*scale"),
]

BY_NAME = {s.name.lower(): s for s in SKILLS}

_COMPILED = [
    (s, re.compile("|".join(rf"(?<![\w.]){p}(?![\w])" if not p.startswith(r"\b") and not p.startswith("(") else p
                            for p in s.patterns), 0 if s.case_sensitive else re.I))
    for s in SKILLS
]

# Lines/sections that mark optional skills
_NICE_HEAD = re.compile(
    r"^\W*(nice[\s-]to[\s-]have|advantages?|bonus(?: points)?|preferred(?: qualifications)?|"
    r"it(?:'|’)?s a plus|a plus|pluses|extra credit|great to have|good to have|would be great)\W*$", re.I)
_NICE_INLINE = re.compile(
    r"\b(advantage|nice to have|a plus|is a plus|bonus|(?<!strongly )preferred|desirable|familiarity with)\b", re.I)
# Bullets and sentences inside one line ("- Python. - Spark (an advantage).")
_SEGMENT = re.compile(r"(?<=[.;!?])\s+(?=[A-Z(])|\s+[-–•·*]\s+(?=[A-Z0-9(])|^\s*[-–•·*]\s+|•")


def _segments(line: str) -> list[str]:
    return [s.strip() for s in _SEGMENT.split(line) if s and s.strip()]
_REQ_HEAD = re.compile(
    r"^\W*(requirements?|qualifications?|what you(?:'|’)?ll need|what you need.*|must[\s-]haves?|"
    r"what we(?:'|’)?re looking for|who you are|about you|you have|skills|responsibilities|what you(?:'|’)?ll do.*)\W*$",
    re.I)


def find_skills(text: str) -> list[str]:
    """All skills mentioned in the text, in taxonomy order."""
    return [s.name for s, rx in _COMPILED if rx.search(text or "")]


def job_skills(description: str) -> dict[str, str]:
    """Skills a job asks for: {skill name: "required" | "nice"}.
    A skill is "nice" when it only appears under a nice-to-have heading or on a line saying "advantage"/"plus"."""
    out: dict[str, str] = {}
    section_nice = False
    for raw in (description or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if len(line) < 60:
            if _NICE_HEAD.match(line):
                section_nice = True
                continue
            if _REQ_HEAD.match(line):
                section_nice = False
                continue
        for seg in _segments(line):
            nice = section_nice or bool(_NICE_INLINE.search(seg))
            for s, rx in _COMPILED:
                if rx.search(seg):
                    if not nice:
                        out[s.name] = "required"
                    else:
                        out.setdefault(s.name, "nice")
    return out


def group_of(name: str) -> str | None:
    s = BY_NAME.get(name.lower())
    return s.group if s else None


def canonical(name: str) -> str:
    """Taxonomy spelling for a user-typed skill, or the trimmed text if it isn't in the taxonomy."""
    name = " ".join(name.split())
    if s := BY_NAME.get(name.lower()):
        return s.name
    found = find_skills(name)
    return found[0] if len(found) == 1 else name


# ---------- years of experience ----------

_YEARS_REQ = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:\+\s*)?years?", re.I)
_RANGE = re.compile(
    r"(?:(?:0?[1-9]|1[0-2])[./-])?((?:19|20)\d{2})\s*(?:-|–|—|to)\s*(?:(?:0?[1-9]|1[0-2])[./-])?((?:19|20)\d{2}|present|current|now|today)",
    re.I)


def required_years(description: str) -> int | None:
    """The main 'N+ years' bar: the largest one on a line about experience that isn't nice-to-have."""
    main, other = [], []
    for line in (seg for raw in (description or "").splitlines() for seg in _segments(raw)):
        if _NICE_INLINE.search(line):
            continue
        for m in _YEARS_REQ.finditer(line):
            n = int(m.group(1))
            if 1 <= n <= 15:
                (main if re.search(r"experience|years as|years in|years of", line, re.I) else other).append(n)
    found = main or other
    return max(found) if found else None


def cv_years(cv_text: str, this_year: int) -> int | None:
    """Estimate total years of work from date ranges in a CV (union of ranges, skipping an education section)."""
    text = cv_text or ""
    edu = re.search(r"^\s*(education|academic|studies)\b.*$", text, re.I | re.M)
    if edu:
        nxt = re.search(r"^\s*(experience|work|employment|professional|skills|projects)\b", text[edu.end():], re.I | re.M)
        text = text[: edu.start()] + (text[edu.end() + nxt.start():] if nxt else "")
    spans = []
    for m in _RANGE.finditer(text):
        start = int(m.group(1))
        end = this_year if not m.group(2)[0].isdigit() else int(m.group(2))
        if 1980 <= start <= end <= this_year:
            spans.append((start, end))
    if not spans:
        return None
    spans.sort()
    total, cur_s, cur_e = 0, *spans[0]
    for s, e in spans[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s
            cur_s, cur_e = s, e
    total += cur_e - cur_s
    return max(total, 1)
