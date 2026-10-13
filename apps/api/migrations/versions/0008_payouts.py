"""Recurring and one-time payout planning with Admin-attested disbursements.

Revision ID: 0008_payouts
Revises: 0007_manual_reversals
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_payouts"
down_revision = "0007_manual_reversals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payout_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id", sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("payee_name", sa.String(160), nullable=False),
        sa.Column("purpose", sa.String(240), nullable=False),
        sa.Column("notes", sa.String(800)),
        sa.Column("cadence", sa.String(16), nullable=False),
        sa.Column("start_month", sa.Date(), nullable=False),
        sa.Column("scheduled_on", sa.Date()),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_by_admin_id", sa.Uuid(),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "organization_id", "id", name="uq_payout_plan_org_id",
        ),
        sa.CheckConstraint(
            "cadence IN ('recurring', 'one_time')", name="ck_payout_plan_cadence",
        ),
        sa.CheckConstraint(
            "amount_paise > 0 AND amount_paise <= 1000000000",
            name="ck_payout_plan_positive_amount",
        ),
        sa.CheckConstraint(
            "(cadence = 'one_time' AND scheduled_on IS NOT NULL) OR "
            "(cadence = 'recurring' AND scheduled_on IS NULL)",
            name="ck_payout_plan_scheduled_only_once",
        ),
    )
    op.create_index(
        "ix_payout_plans_organization_id", "payout_plans", ["organization_id"]
    )
    op.create_table(
        "payout_plan_terms",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("effective_month", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "recorded_by_admin_id", sa.Uuid(),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "plan_id"],
            ["payout_plans.organization_id", "payout_plans.id"],
            ondelete="RESTRICT", name="fk_payout_term_plan_org",
        ),
        sa.UniqueConstraint(
            "organization_id", "plan_id", "effective_month",
            name="uq_payout_term_month",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'closed')",
            name="ck_payout_term_status",
        ),
    )
    op.create_index(
        "ix_payout_plan_terms_organization_id", "payout_plan_terms",
        ["organization_id"],
    )
    op.create_index(
        "ix_payout_plan_terms_plan_id", "payout_plan_terms", ["plan_id"]
    )
    op.create_table(
        "payout_payments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("request_payload_hash", sa.String(64), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("payment_method", sa.String(24), nullable=False),
        sa.Column("reference_digest", sa.String(64), nullable=False),
        sa.Column("reference_mask", sa.String(16), nullable=False),
        sa.Column(
            "recorded_by_admin_id", sa.Uuid(),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "plan_id"],
            ["payout_plans.organization_id", "payout_plans.id"],
            ondelete="RESTRICT", name="fk_payout_payment_plan_org",
        ),
        sa.UniqueConstraint(
            "organization_id", "request_id", name="uq_payout_payment_request",
        ),
        sa.UniqueConstraint(
            "organization_id", "reference_digest",
            name="uq_payout_payment_reference",
        ),
        sa.UniqueConstraint(
            "organization_id", "plan_id", "period_month",
            name="uq_payout_payment_one_per_period",
        ),
        sa.CheckConstraint(
            "amount_paise > 0 AND amount_paise <= 1000000000",
            name="ck_payout_payment_positive_amount",
        ),
        sa.CheckConstraint(
            "payment_method IN ('upi', 'bank_transfer', 'cash', 'cheque')",
            name="ck_payout_payment_method",
        ),
    )
    op.create_index(
        "ix_payout_payments_organization_id", "payout_payments",
        ["organization_id"],
    )
    op.create_index(
        "ix_payout_payments_plan_id", "payout_payments", ["plan_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_payout_payments_plan_id", table_name="payout_payments")
    op.drop_index("ix_payout_payments_organization_id", table_name="payout_payments")
    op.drop_table("payout_payments")
    op.drop_index("ix_payout_plan_terms_plan_id", table_name="payout_plan_terms")
    op.drop_index(
        "ix_payout_plan_terms_organization_id", table_name="payout_plan_terms"
    )
    op.drop_table("payout_plan_terms")
    op.drop_index("ix_payout_plans_organization_id", table_name="payout_plans")
    op.drop_table("payout_plans")
