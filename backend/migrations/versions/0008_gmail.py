"""Gmail tracking: connected accounts, handled job emails, links on timeline events

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("url", sa.Text))
    op.create_table(
        "gmail_accounts",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, server_default=""),
        sa.Column("refresh_token", sa.Text, nullable=False),
        sa.Column("history_id", sa.String(40)),
        sa.Column("label_id", sa.String(100)),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text, nullable=False, server_default=""),
    )
    op.create_table(
        "gmail_messages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("gmail_id", sa.String(40), nullable=False),
        sa.Column("thread_id", sa.String(40), nullable=False, server_default="", index=True),
        sa.Column("sender", sa.String(320), nullable=False, server_default=""),
        sa.Column("subject", sa.String(500), nullable=False, server_default=""),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("previous_status", sa.String(20)),
        sa.Column("moved", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("company_guess", sa.String(200), nullable=False, server_default=""),
        sa.Column("title_guess", sa.String(300), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "gmail_id", name="uq_gmail_user_message"),
    )


def downgrade() -> None:
    op.drop_table("gmail_messages")
    op.drop_table("gmail_accounts")
    op.drop_column("events", "url")
