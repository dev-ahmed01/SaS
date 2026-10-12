"""Durable Admin sessions and anonymous login attempt throttling.

Revision ID: 0002_admin_sessions
Revises: 0001_foundation
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_admin_sessions"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "admin_user_id", sa.Uuid(),
            sa.ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "organization_id", sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_admin_sessions_admin_user_id", "admin_sessions", ["admin_user_id"])
    op.create_index("ix_admin_sessions_organization_id", "admin_sessions", ["organization_id"])
    op.create_index("ix_admin_sessions_expires_at", "admin_sessions", ["expires_at"])
    op.create_table(
        "admin_login_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email_hash", sa.String(64), nullable=False),
        sa.Column("network_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_admin_login_attempts_email_hash", "admin_login_attempts", ["email_hash"])
    op.create_index("ix_admin_login_attempts_network_hash", "admin_login_attempts", ["network_hash"])
    op.create_index("ix_admin_login_attempts_occurred_at", "admin_login_attempts", ["occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_admin_login_attempts_occurred_at", table_name="admin_login_attempts")
    op.drop_index("ix_admin_login_attempts_network_hash", table_name="admin_login_attempts")
    op.drop_index("ix_admin_login_attempts_email_hash", table_name="admin_login_attempts")
    op.drop_table("admin_login_attempts")
    op.drop_index("ix_admin_sessions_expires_at", table_name="admin_sessions")
    op.drop_index("ix_admin_sessions_organization_id", table_name="admin_sessions")
    op.drop_index("ix_admin_sessions_admin_user_id", table_name="admin_sessions")
    op.drop_table("admin_sessions")
