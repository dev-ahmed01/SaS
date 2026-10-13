"""Effective monthly rates and bank-verification-ready credit ledger.

Revision ID: 0005_monthly_accounting
Revises: 0004_promoters
"""
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from alembic import op

revision = "0005_monthly_accounting"
down_revision = "0004_promoters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("prospects", sa.Column("start_month", sa.Date(), nullable=True))
    op.create_table(
        "sponsorship_rates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("prospect_id", sa.Uuid(), nullable=False),
        sa.Column("effective_month", sa.Date(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "prospect_id"],
            ["prospects.organization_id", "prospects.id"],
            ondelete="RESTRICT", name="fk_rate_prospect_same_org",
        ),
        sa.UniqueConstraint(
            "organization_id", "prospect_id", "effective_month",
            name="uq_rate_prospect_month",
        ),
        sa.CheckConstraint("amount_paise > 0", name="ck_rate_positive_amount"),
        sa.CheckConstraint(
            "amount_paise <= 1000000000", name="ck_rate_amount_maximum"
        ),
    )
    op.create_index("ix_sponsorship_rates_organization_id", "sponsorship_rates",
                    ["organization_id"])
    op.create_index("ix_sponsorship_rates_prospect_id", "sponsorship_rates",
                    ["prospect_id"])
    op.create_table(
        "verified_credits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("prospect_id", sa.Uuid(), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("source_type", sa.String(24), nullable=False),
        sa.Column("source_key", sa.String(128), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "prospect_id"],
            ["prospects.organization_id", "prospects.id"],
            ondelete="RESTRICT", name="fk_credit_prospect_same_org",
        ),
        sa.UniqueConstraint(
            "organization_id", "source_key", name="uq_credit_org_source"
        ),
        sa.CheckConstraint("amount_paise > 0", name="ck_credit_positive_amount"),
        sa.CheckConstraint(
            "source_type IN ('bank_reconciled', 'manual_attested')",
            name="ck_credit_source_type",
        ),
    )
    op.create_index("ix_verified_credits_organization_id", "verified_credits",
                    ["organization_id"])
    op.create_index("ix_verified_credits_prospect_id", "verified_credits",
                    ["prospect_id"])
    op.create_index(
        "ix_credit_prospect_month", "verified_credits",
        ["organization_id", "prospect_id", "period_month"],
    )
    # Existing prospects must not unexpectedly become payable for periods
    # before their real registration; backfill from recorded creation in IST.
    conn = op.get_bind()
    prospect_table = sa.table(
        "prospects",
        sa.column("id", sa.Uuid()),
        sa.column("organization_id", sa.Uuid()),
        sa.column("monthly_contribution_paise", sa.BigInteger()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("start_month", sa.Date()),
    )
    rate_table = sa.table(
        "sponsorship_rates",
        sa.column("id", sa.Uuid()),
        sa.column("organization_id", sa.Uuid()),
        sa.column("prospect_id", sa.Uuid()),
        sa.column("effective_month", sa.Date()),
        sa.column("amount_paise", sa.BigInteger()),
    )
    existing = conn.execute(sa.select(
        prospect_table.c.id, prospect_table.c.organization_id,
        prospect_table.c.monthly_contribution_paise, prospect_table.c.created_at,
    ))
    for row in existing.mappings():
        created = row["created_at"]
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        local = created.astimezone(ZoneInfo("Asia/Kolkata")).date()
        month = local.replace(day=1)
        conn.execute(
            prospect_table.update()
            .where(prospect_table.c.id == row["id"])
            .values(start_month=month)
        )
        conn.execute(rate_table.insert().values(
            id=uuid.uuid4(), organization_id=row["organization_id"],
            prospect_id=row["id"], effective_month=month,
            amount_paise=row["monthly_contribution_paise"],
        ))
    # SQLite batch alterations require special care; nullable columns serve
    # migration compat, and new write APIs always set a start month.


def downgrade() -> None:
    op.drop_index("ix_credit_prospect_month", table_name="verified_credits")
    op.drop_index("ix_verified_credits_prospect_id", table_name="verified_credits")
    op.drop_index("ix_verified_credits_organization_id", table_name="verified_credits")
    op.drop_table("verified_credits")
    op.drop_index("ix_sponsorship_rates_prospect_id", table_name="sponsorship_rates")
    op.drop_index("ix_sponsorship_rates_organization_id", table_name="sponsorship_rates")
    op.drop_table("sponsorship_rates")
    op.drop_column("prospects", "start_month")
