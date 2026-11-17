"""The user's notes for the AI grader

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("ai_notes", sa.Text, nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("user_profiles", "ai_notes")
