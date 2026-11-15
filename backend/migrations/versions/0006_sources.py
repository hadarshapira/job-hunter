"""settings: which sources the job search uses

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("sources", sa.JSON, nullable=False, server_default='["jsearch", "greenhouse", "lever", "ashby"]'),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "sources")
