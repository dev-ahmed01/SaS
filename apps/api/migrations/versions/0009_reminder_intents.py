"""Consent-aware reminder preview batch and intent constraints.

Revision ID: 0009_reminder_intents
Revises: 0008_payouts
"""
import sqlalchemy as sa
from alembic import op

revision = "0009_reminder_intents"
down_revision = "0008_payouts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reminder_batches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("scheduled_on", sa.Date(), nullable=False),
        sa.Column("recipient_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_by_admin_id", sa.Uuid(),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "organization_id", "id", name="uq_reminder_batch_org_id",
        ),
        sa.UniqueConstraint(
            "organization_id", "kind", "period_month",
            name="uq_reminder_one_batch_kind_month",
        ),
        sa.UniqueConstraint(
            "organization_id", "request_id", name="uq_reminder_batch_request",
        ),
        sa.CheckConstraint(
            "kind IN ('sponsor', 'promoter')", name="ck_reminder_batch_kind",
        ),
        sa.CheckConstraint(
            "recipient_count >= 0", name="ck_reminder_batch_count",
        ),
    )
    op.create_index(
        "ix_reminder_batches_organization_id",
        "reminder_batches", ["organization_id"],
    )
    op.create_table(
        "reminder_intents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("prospect_id", sa.Uuid(), nullable=True),
        sa.Column("promoter_id", sa.Uuid(), nullable=True),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("scheduled_on", sa.Date(), nullable=False),
        sa.Column("sponsor_count", sa.Integer(), nullable=False),
        sa.Column("outstanding_paise", sa.BigInteger(), nullable=False),
        sa.Column("sponsor_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "batch_id"],
            ["reminder_batches.organization_id", "reminder_batches.id"],
            ondelete="RESTRICT", name="fk_reminder_intent_batch_org",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "prospect_id"],
            ["prospects.organization_id", "prospects.id"],
            ondelete="RESTRICT", name="fk_reminder_intent_prospect_org",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "promoter_id"],
            ["promoters.organization_id", "promoters.id"],
            ondelete="RESTRICT", name="fk_reminder_intent_promoter_org",
        ),
        sa.UniqueConstraint(
            "organization_id", "kind", "prospect_id", "period_month",
            name="uq_reminder_once_sponsor_month",
        ),
        sa.UniqueConstraint(
            "organization_id", "kind", "promoter_id", "period_month",
            name="uq_reminder_once_promoter_month",
        ),
        sa.CheckConstraint(
            "kind IN ('sponsor', 'promoter')",
            name="ck_reminder_intent_kind",
        ),
        sa.CheckConstraint(
            "(kind = 'sponsor' AND prospect_id IS NOT NULL AND promoter_id IS NULL)"
            " OR (kind = 'promoter' AND promoter_id IS NOT NULL AND prospect_id IS NULL)",
            name="ck_reminder_recipient_exclusive",
        ),
        sa.CheckConstraint(
            "status IN ('prepared', 'cancelled')",
            name="ck_reminder_preintegration_state",
        ),
        sa.CheckConstraint(
            "outstanding_paise > 0 AND sponsor_count > 0",
            name="ck_reminder_positive_outstanding",
        ),
    )
    op.create_index(
        "ix_reminder_intents_organization_id",
        "reminder_intents", ["organization_id"],
    )
    op.create_index(
        "ix_reminder_org_period_kind",
        "reminder_intents", ["organization_id", "period_month", "kind"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reminder_org_period_kind", table_name="reminder_intents",
    )
    op.drop_index(
        "ix_reminder_intents_organization_id", table_name="reminder_intents",
    )
    op.drop_table("reminder_intents")
    op.drop_index(
        "ix_reminder_batches_organization_id", table_name="reminder_batches",
    )
    op.drop_table("reminder_batches")
