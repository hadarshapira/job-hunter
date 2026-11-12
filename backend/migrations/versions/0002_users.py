"""multi-user: users table, jobs.user_id

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("picture", sa.Text),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("google_sub", sa.String(64), unique=True),
        sa.Column("email_verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    conn = op.get_bind()
    orphans = conn.scalar(sa.text("SELECT count(*) FROM jobs"))
    if orphans:
        raise RuntimeError(
            f"{orphans} job(s) exist from the single-user version. Delete them or assign them to a user "
            "before upgrading (jobs now belong to a user)."
        )
    op.add_column("jobs", sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False))
    op.create_index("ix_jobs_user_id", "jobs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_user_id", "jobs")
    op.drop_column("jobs", "user_id")
    op.drop_table("users")
