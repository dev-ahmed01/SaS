"""Payout plans and Admin-attested disbursements.

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
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey(
            "organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payee_name", sa.String(160), nullable=False),
        sa.Column("purpose", sa.String(240), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("frequency", sa.String(12), nullable=False),
        sa.Column("start_month", sa.Date(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("notes", sa.String(1000)),
        sa.Column("created_by_admin_id", sa.Uuid(), sa.ForeignKey(
            "admin_users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "id", name="uq_payout_plan_org_id"),
        sa.UniqueConstraint("organization_id", "request_id", name="uq_payout_plan_request"),
        sa.CheckConstraint("amount_paise > 0", name="ck_payout_plan_positive"),
        sa.CheckConstraint("frequency IN ('recurring', 'one_time')", name="ck_payout_frequency"),
        sa.CheckConstraint("status IN ('active', 'paused', 'closed')",
                           name="ck_payout_plan_status"),
    )
    op.create_index("ix_payout_plans_organization_id", "payout_plans", ["organization_id"])
    op.create_table(
        "payout_disbursements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("payment_method", sa.String(16), nullable=False),
        sa.Column("reference_digest", sa.String(64), nullable=False),
        sa.Column("reference_mask", sa.String(24), nullable=False),
        sa.Column("recorded_by_admin_id", sa.Uuid(), sa.ForeignKey(
            "admin_users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id", "plan_id"],
            ["payout_plans.organization_id", "payout_plans.id"],
            name="fk_payout_disbursement_same_org", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("organization_id", "request_id",
                            name="uq_payout_disbursement_request"),
        sa.UniqueConstraint("organization_id", "reference_digest",
                            name="uq_payout_disbursement_reference"),
        sa.UniqueConstraint("organization_id", "plan_id", "period_month",
                            name="uq_payout_disbursement_period"),
        sa.CheckConstraint("amount_paise > 0", name="ck_payout_disbursement_positive"),
        sa.CheckConstraint("payment_method IN ('upi', 'bank_transfer', 'cash')",
                           name="ck_payout_disbursement_method"),
    )
    op.create_index("ix_payout_disbursements_organization_id",
                    "payout_disbursements", ["organization_id"])
    op.create_index("ix_payout_disbursements_plan_id",
                    "payout_disbursements", ["plan_id"])


def downgrade() -> None:
    op.drop_index("ix_payout_disbursements_plan_id", table_name="payout_disbursements")
    op.drop_index("ix_payout_disbursements_organization_id", table_name="payout_disbursements")
    op.drop_table("payout_disbursements")
    op.drop_index("ix_payout_plans_organization_id", table_name="payout_plans")
    op.drop_table("payout_plans")
