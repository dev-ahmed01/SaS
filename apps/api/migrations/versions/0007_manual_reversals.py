"""Append-only reversal and tenant-scoped financial adjustment provenance.

Revision ID: 0007_manual_reversals
Revises: 0006_manual_collections
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_manual_reversals"
down_revision = "0006_manual_collections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manual_collection_reversals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("reason_code", sa.String(32), nullable=False),
        sa.Column(
            "actor_admin_id", sa.Uuid(),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "collection_id"],
            ["manual_collections.organization_id", "manual_collections.id"],
            ondelete="RESTRICT", name="fk_reversal_collection_same_org",
        ),
        sa.UniqueConstraint(
            "organization_id", "collection_id",
            name="uq_reversal_one_per_collection",
        ),
        sa.UniqueConstraint(
            "organization_id", "request_id", name="uq_reversal_request_org",
        ),
        sa.CheckConstraint(
            "reason_code IN ("
            "'duplicate_entry', 'wrong_sponsor', 'wrong_amount', "
            "'funds_not_received', 'other')",
            name="ck_reversal_reason",
        ),
    )
    op.create_index(
        "ix_manual_collection_reversals_organization_id",
        "manual_collection_reversals", ["organization_id"],
    )
    op.create_index(
        "ix_manual_collection_reversals_collection_id",
        "manual_collection_reversals", ["collection_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_manual_collection_reversals_collection_id",
        table_name="manual_collection_reversals",
    )
    op.drop_index(
        "ix_manual_collection_reversals_organization_id",
        table_name="manual_collection_reversals",
    )
    op.drop_table("manual_collection_reversals")
