"""Audited outgoing-payment correction while retaining original evidence.

Revision ID: 0025_payout_reversal
Revises: 0024_saasyto_claim_window_index
"""
import sqlalchemy as sa
from alembic import op

revision = "0025_payout_reversal"
down_revision = "0024_saasyto_claim_window_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("payout_plans") as batch:
        batch.add_column(sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("payout_payments") as batch:
        batch.add_column(sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("reversal_request_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("reversal_reason", sa.String(40), nullable=True))
        batch.add_column(sa.Column("reversed_by_admin_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_payout_reversed_by_admin", "admin_users",
            ["reversed_by_admin_id"], ["id"], ondelete="SET NULL",
        )
        batch.drop_constraint("uq_payout_payment_one_per_period", type_="unique")
        batch.create_unique_constraint(
            "uq_payout_reversal_request", ["organization_id", "reversal_request_id"]
        )
    op.create_index(
        "uq_payout_active_payment_period", "payout_payments",
        ["organization_id", "plan_id", "period_month"], unique=True,
        postgresql_where=sa.text("reversed_at IS NULL"),
        sqlite_where=sa.text("reversed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_payout_active_payment_period", table_name="payout_payments")
    # A downgrade requires active and reversed receipts not to overlap by
    # original period; DB uniqueness will prevent unsafe loss of evidence.
    with op.batch_alter_table("payout_payments") as batch:
        batch.drop_constraint("uq_payout_reversal_request", type_="unique")
        batch.create_unique_constraint(
            "uq_payout_payment_one_per_period",
            ["organization_id", "plan_id", "period_month"],
        )
        batch.drop_constraint("fk_payout_reversed_by_admin", type_="foreignkey")
        batch.drop_column("reversed_by_admin_id")
        batch.drop_column("reversal_reason")
        batch.drop_column("reversal_request_id")
        batch.drop_column("reversed_at")
    with op.batch_alter_table("payout_plans") as batch:
        batch.drop_column("voided_at")
