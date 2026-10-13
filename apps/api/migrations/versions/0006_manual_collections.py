"""Admin manual collections and consent-gated confirmation intent.

Revision ID: 0006_manual_collections
Revises: 0005_monthly_accounting
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_manual_collections"
down_revision = "0005_monthly_accounting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_credits_org_id", "verified_credits", ["organization_id", "id"]
    )
    op.create_table(
        "manual_collections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("prospect_id", sa.Uuid(), nullable=False),
        sa.Column("verified_credit_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("request_payload_hash", sa.String(64), nullable=False),
        sa.Column("reference_digest", sa.String(64), nullable=False),
        sa.Column("reference_mask", sa.String(16), nullable=False),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("payment_method", sa.String(20), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("recorded_by_admin_id", sa.Uuid(),
                  sa.ForeignKey("admin_users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id", "prospect_id"], ["prospects.organization_id", "prospects.id"],
            name="fk_manual_collection_prospect_org", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "verified_credit_id"],
            ["verified_credits.organization_id", "verified_credits.id"],
            name="fk_manual_collection_credit_org", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "organization_id", "id", name="uq_manual_collections_org_id"
        ),
        sa.UniqueConstraint(
            "organization_id", "request_id", name="uq_manual_collection_request"
        ),
        sa.UniqueConstraint(
            "organization_id", "reference_digest", name="uq_manual_collection_reference"
        ),
        sa.UniqueConstraint("verified_credit_id", name="uq_manual_collection_credit"),
        sa.CheckConstraint("amount_paise > 0", name="ck_manual_collection_amount"),
        sa.CheckConstraint(
            "payment_method IN ('upi', 'bank_transfer', 'cash')",
            name="ck_manual_collection_method",
        ),
    )
    op.create_index("ix_manual_collections_organization_id", "manual_collections",
                    ["organization_id"])
    op.create_index("ix_manual_collections_prospect_id", "manual_collections",
                    ["prospect_id"])
    op.create_index("ix_manual_collection_org_date", "manual_collections",
                    ["organization_id", "received_on"])
    op.create_table(
        "message_outbox",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("prospect_id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("suppress_reason", sa.String(60)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id", "prospect_id"], ["prospects.organization_id", "prospects.id"],
            name="fk_message_prospect_org", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "collection_id"],
            ["manual_collections.organization_id", "manual_collections.id"],
            name="fk_message_collection_org", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "organization_id", "collection_id", "event_type",
            name="uq_message_collection_event",
        ),
        sa.CheckConstraint(
            "status IN ('awaiting_integration', 'suppressed')",
            name="ck_message_preintegration_status",
        ),
    )
    op.create_index("ix_message_outbox_organization_id", "message_outbox",
                    ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_message_outbox_organization_id", table_name="message_outbox")
    op.drop_table("message_outbox")
    op.drop_index("ix_manual_collection_org_date", table_name="manual_collections")
    op.drop_index("ix_manual_collections_prospect_id", table_name="manual_collections")
    op.drop_index("ix_manual_collections_organization_id", table_name="manual_collections")
    op.drop_table("manual_collections")
    op.drop_constraint("uq_credits_org_id", "verified_credits", type_="unique")
