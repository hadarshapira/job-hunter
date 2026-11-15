"""LinkedIn as a search source (on for everyone), and a per-run report

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("collection_runs", sa.Column("stats", sa.JSON))
    op.create_table(
        "posting_cache",
        sa.Column("key", sa.String(300), primary_key=True),
        sa.Column("data", sa.JSON, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.alter_column("user_settings", "sources",
                    server_default='["linkedin", "jsearch", "greenhouse", "lever", "ashby"]')
    # Turn LinkedIn on for existing users
    op.execute(
        """UPDATE user_settings SET sources = ('["linkedin"]'::jsonb || sources::jsonb)::json
           WHERE NOT (sources::jsonb ? 'linkedin')"""
    )


def downgrade() -> None:
    op.execute(
        """UPDATE user_settings SET sources = (sources::jsonb - 'linkedin')::json"""
    )
    op.alter_column("user_settings", "sources", server_default='["jsearch", "greenhouse", "lever", "ashby"]')
    op.drop_table("posting_cache")
    op.drop_column("collection_runs", "stats")
