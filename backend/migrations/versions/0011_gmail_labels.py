"""Gmail label names per user

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_settings", sa.Column("gmail_label_applied", sa.String(200), nullable=False,
                                             server_default="Job search/Applied"))
    op.add_column("user_settings", sa.Column("gmail_label_rejected", sa.String(200), nullable=False,
                                             server_default="Job search/Rejected"))


def downgrade() -> None:
    op.drop_column("user_settings", "gmail_label_rejected")
    op.drop_column("user_settings", "gmail_label_applied")
