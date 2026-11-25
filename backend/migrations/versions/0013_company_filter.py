"""Jobs list company filter (show only / hide companies), per user

Revision ID: 0013
Revises: 0012
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_settings", sa.Column("company_filter_mode", sa.String(10), nullable=False, server_default=""))
    op.add_column("user_settings", sa.Column("company_filter", sa.JSON, nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("user_settings", "company_filter")
    op.drop_column("user_settings", "company_filter_mode")
