"""initial: jobs + events

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("external_id", sa.String(255)),
        sa.Column("url", sa.Text),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("company", sa.String(200), nullable=False),
        sa.Column("location", sa.String(200), nullable=False),
        sa.Column("work_mode", sa.String(20), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("salary", sa.String(120)),
        sa.Column("posted_at", sa.Date),
        sa.Column("dedup_key", sa.String(400), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("follow_up_on", sa.Date),
        sa.Column("notes", sa.Text, nullable=False),
        sa.Column("contact", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jobs_dedup_key", "jobs", ["dedup_key"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_url", "jobs", ["url"])
    op.create_table(
        "events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_events_job_id", "events", ["job_id"])


def downgrade() -> None:
    op.drop_table("events")
    op.drop_table("jobs")
