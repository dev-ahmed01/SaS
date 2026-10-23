"""Sponsor WhatsApp possession verification; no contact-consent or payment changes.

Revision ID: 0019_sponsor_otp
Revises: 0018_crm_fathom
"""
import sqlalchemy as sa
from alembic import op

revision = "0019_sponsor_otp"
down_revision = "0018_crm_fathom"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "prospects",
        sa.Column("whatsapp_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "sponsor_otp_challenges",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("prospect_id", sa.Uuid(), nullable=False),
        sa.Column("phone_digest", sa.String(64), nullable=False),
        sa.Column("code_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id", "prospect_id"],
            ["prospects.organization_id", "prospects.id"],
            ondelete="RESTRICT", name="fk_otp_prospect_org",
        ),
    )
    op.create_index(
        "ix_otp_org_prospect_created",
        "sponsor_otp_challenges",
        ["organization_id", "prospect_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    count = bind.scalar(sa.text("SELECT COUNT(*) FROM sponsor_otp_challenges"))
    verified = bind.scalar(sa.text(
        "SELECT COUNT(*) FROM prospects WHERE whatsapp_verified_at IS NOT NULL"
    ))
    if count or verified:
        raise RuntimeError("Export OTP and verified-phone audit records before downgrade")
    op.drop_index("ix_otp_org_prospect_created", table_name="sponsor_otp_challenges")
    op.drop_table("sponsor_otp_challenges")
    op.drop_column("prospects", "whatsapp_verified_at")
