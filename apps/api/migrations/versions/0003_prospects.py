"""Sponsor candidate records and minimal UPI reconciliation identifiers.

Revision ID: 0003_prospects
Revises: 0002_admin_sessions
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_prospects"
down_revision = "0002_admin_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prospects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id", sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("full_name", sa.String(160), nullable=False),
        sa.Column("mobile_number", sa.String(16), nullable=False),
        sa.Column("whatsapp_number", sa.String(16), nullable=True),
        sa.Column("area_city", sa.String(120), nullable=False),
        sa.Column("monthly_contribution_paise", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("registration_request_id", sa.Uuid()),
        sa.Column("registration_payload_hash", sa.String(64)),
        sa.Column("next_followup_on", sa.Date(), nullable=True),
        sa.Column("last_contact_on", sa.Date(), nullable=True),
        sa.Column("notes", sa.String(1500), nullable=True),
        sa.Column("whatsapp_opt_in", sa.Boolean(), nullable=False),
        sa.Column("lifecycle_status", sa.String(12), nullable=False),
        sa.Column("last_verified_payment_at", sa.DateTime(timezone=True)),
        sa.Column(
            "status_updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint("organization_id", "id", name="uq_prospects_org_id"),
        sa.UniqueConstraint(
            "organization_id", "registration_request_id", name="uq_prospect_registration"
        ),
        sa.CheckConstraint(
            "monthly_contribution_paise > 0", name="ck_prospect_amount_positive"
        ),
        sa.CheckConstraint(
            "lifecycle_status IN ('new', 'active', 'inactive')",
            name="ck_prospect_lifecycle_status",
        ),
    )
    op.create_index("ix_prospects_organization_id", "prospects", ["organization_id"])
    op.create_index(
        "ix_prospects_org_status", "prospects",
        ["organization_id", "lifecycle_status", "archived_at"],
    )
    op.create_table(
        "prospect_upi_ids",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("prospect_id", sa.Uuid(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("masked_vpa", sa.String(130), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["organization_id", "prospect_id"],
            ["prospects.organization_id", "prospects.id"],
            ondelete="CASCADE", name="fk_prospect_upi_same_org",
        ),
        sa.UniqueConstraint("prospect_id", "digest", name="uq_prospect_upi_digest"),
    )
    op.create_index(
        "ix_prospect_upi_org_digest", "prospect_upi_ids",
        ["organization_id", "digest"],
    )


def downgrade() -> None:
    op.drop_index("ix_prospect_upi_org_digest", table_name="prospect_upi_ids")
    op.drop_table("prospect_upi_ids")
    op.drop_index("ix_prospects_org_status", table_name="prospects")
    op.drop_index("ix_prospects_organization_id", table_name="prospects")
    op.drop_table("prospects")
