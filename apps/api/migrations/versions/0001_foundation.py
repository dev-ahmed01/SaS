"""Organization, Admin, configurable settings and audit-event foundations.

Revision ID: 0001_foundation
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("email", sa.String(320), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_admin_users_organization_id", "admin_users", ["organization_id"])
    op.create_table(
        "organization_settings",
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("default_contribution_paise", sa.BigInteger(), nullable=False),
        sa.Column("sponsor_reminder_day", sa.Integer(), nullable=False),
        sa.Column("promoter_reminder_day", sa.Integer(), nullable=False),
        sa.Column("inactivity_months", sa.Integer(), nullable=False),
        sa.Column("automation_enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("default_contribution_paise > 0", name="ck_settings_positive_amount"),
        sa.CheckConstraint("sponsor_reminder_day BETWEEN 1 AND 28", name="ck_settings_sponsor_day"),
        sa.CheckConstraint("promoter_reminder_day BETWEEN 1 AND 28", name="ck_settings_promoter_day"),
        sa.CheckConstraint("inactivity_months BETWEEN 1 AND 24", name="ck_settings_inactivity"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_admin_id", sa.Uuid(), sa.ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.String(80), nullable=False),
        sa.Column("before_data", sa.JSON(), nullable=True),
        sa.Column("after_data", sa.JSON(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_events_organization_id", "audit_events", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_organization_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("organization_settings")
    op.drop_index("ix_admin_users_organization_id", table_name="admin_users")
    op.drop_table("admin_users")
    op.drop_table("organizations")
