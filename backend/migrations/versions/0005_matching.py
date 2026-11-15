"""matching: user profile (CV, skills, years) and a match grade per job

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("cv_filename", sa.String(255), nullable=False, server_default=""),
        sa.Column("cv_text", sa.Text, nullable=False, server_default=""),
        sa.Column("cv_uploaded_at", sa.DateTime(timezone=True)),
        sa.Column("skills", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("years_experience", sa.Integer),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("jobs", sa.Column("match_score", sa.Integer))
    op.add_column("jobs", sa.Column("match", sa.JSON))
    op.add_column("jobs", sa.Column("match_at", sa.DateTime(timezone=True)))
    op.create_index("ix_jobs_match_score", "jobs", ["match_score"])


def downgrade() -> None:
    op.drop_index("ix_jobs_match_score", "jobs")
    op.drop_column("jobs", "match_at")
    op.drop_column("jobs", "match")
    op.drop_column("jobs", "match_score")
    op.drop_table("user_profiles")
