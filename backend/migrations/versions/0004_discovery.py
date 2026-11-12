"""discovery: user settings, companies (with starter list), caches, collection runs, job location

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# Israeli companies with active Greenhouse / Lever / Ashby boards (checked 2026-11-12)
STARTER = [
    ("greenhouse", "similarweb", "Similarweb"), ("greenhouse", "taboola", "Taboola"),
    ("greenhouse", "appsflyer", "AppsFlyer"), ("greenhouse", "catonetworks", "Cato Networks"),
    ("greenhouse", "transmitsecurity", "Transmit Security"), ("greenhouse", "riskified", "Riskified"),
    ("greenhouse", "wizinc", "Wiz"), ("greenhouse", "payoneer", "Payoneer"), ("greenhouse", "jfrog", "JFrog"),
    ("greenhouse", "yotpo", "Yotpo"), ("greenhouse", "via", "Via"), ("greenhouse", "axonius", "Axonius"),
    ("greenhouse", "orcasecurity", "Orca Security"), ("greenhouse", "datarails", "Datarails"),
    ("greenhouse", "forter", "Forter"), ("greenhouse", "bigid", "BigID"), ("greenhouse", "island", "Island"),
    ("greenhouse", "optimove", "Optimove"), ("greenhouse", "nanit", "Nanit"), ("lever", "walkme", "WalkMe"),
    ("ashby", "moonactive", "Moon Active"), ("ashby", "nexxen", "Nexxen"), ("ashby", "redis", "Redis"),
    ("ashby", "honeybook", "HoneyBook"),
]


def upgrade() -> None:
    op.add_column("jobs", sa.Column("posting_key", sa.String(300)))
    op.add_column("jobs", sa.Column("lat", sa.Float))
    op.add_column("jobs", sa.Column("lon", sa.Float))
    op.add_column("jobs", sa.Column("distance_km", sa.Float))
    op.create_index("ix_jobs_posting_key", "jobs", ["posting_key"])
    op.create_unique_constraint("uq_jobs_user_posting", "jobs", ["user_id", "posting_key"])

    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("home_label", sa.String(300), nullable=False),
        sa.Column("home_lat", sa.Float),
        sa.Column("home_lon", sa.Float),
        sa.Column("work_modes", sa.JSON, nullable=False),
        sa.Column("max_km_onsite", sa.Integer, nullable=False),
        sa.Column("max_km_hybrid", sa.Integer, nullable=False),
        sa.Column("title_keywords", sa.JSON, nullable=False),
        sa.Column("exclude_keywords", sa.JSON, nullable=False),
        sa.Column("senior_only", sa.Boolean, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    companies = op.create_table(
        "companies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ats", sa.String(20), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("added_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("last_ok_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("ats", "slug"),
    )
    op.bulk_insert(companies, [{"ats": a, "slug": s, "name": n, "last_error": ""} for a, s, n in STARTER])

    op.create_table(
        "geo_cache",
        sa.Column("query", sa.String(300), primary_key=True),
        sa.Column("lat", sa.Float),
        sa.Column("lon", sa.Float),
        sa.Column("label", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "search_cache",
        sa.Column("query", sa.String(300), primary_key=True),
        sa.Column("results", sa.JSON, nullable=False),
        sa.Column("quota_remaining", sa.Integer),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "collection_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("added", sa.Integer, nullable=False),
        sa.Column("seen", sa.Integer, nullable=False),
        sa.Column("errors", sa.Text, nullable=False),
    )


def downgrade() -> None:
    for t in ("collection_runs", "search_cache", "geo_cache", "companies", "user_settings"):
        op.drop_table(t)
    op.drop_constraint("uq_jobs_user_posting", "jobs")
    op.drop_index("ix_jobs_posting_key", "jobs")
    for c in ("distance_km", "lon", "lat", "posting_key"):
        op.drop_column("jobs", c)
