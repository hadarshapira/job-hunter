"""AI match grade per job, and the per-user switch for it

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("ai_match", sa.JSON))
    op.add_column("user_settings", sa.Column("ai_grading", sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("user_settings", "ai_grading")
    op.drop_column("jobs", "ai_match")
