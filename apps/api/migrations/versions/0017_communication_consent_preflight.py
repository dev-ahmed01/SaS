"""Append-only consent evidence and simulation-only campaign recipient preflight.

Revision ID: 0017_comm_preflight
Revises: 0016_communication
"""
import sqlalchemy as sa
from alembic import op

revision = "0017_comm_preflight"
down_revision = "0016_communication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "communication_consent_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(),
                  sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("recipient_kind", sa.String(12), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(12), nullable=False),
        sa.Column("decision", sa.String(12), nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("evidence_reference", sa.String(160)),
        sa.Column("actor_admin_id", sa.Uuid(),
                  sa.ForeignKey("admin_users.id", ondelete="SET NULL")),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("recipient_kind IN ('prospect','promoter')",
                           name="ck_comm_consent_kind"),
        sa.CheckConstraint("channel IN ('whatsapp','email')",
                           name="ck_comm_consent_channel"),
        sa.CheckConstraint("decision IN ('opted_in','opted_out')",
                           name="ck_comm_consent_decision"),
    )
    op.create_index("ix_comm_consent_person", "communication_consent_events",
                    ["organization_id", "recipient_kind", "recipient_id",
                     "channel", "recorded_at"])

    op.create_table(
        "communication_preparations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("eligible_count", sa.Integer(), nullable=False),
        sa.Column("suppressed_count", sa.Integer(), nullable=False),
        sa.Column("created_by_admin_id", sa.Uuid(),
                  sa.ForeignKey("admin_users.id", ondelete="SET NULL")),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "campaign_id"],
            ["communication_campaigns.organization_id", "communication_campaigns.id"],
            ondelete="RESTRICT", name="fk_comm_prep_campaign_org"),
        sa.UniqueConstraint("organization_id", "id", name="uq_comm_prep_org_id"),
        sa.UniqueConstraint("organization_id", "request_id", name="uq_comm_prep_request"),
    )
    op.create_index("ix_comm_prep_campaign", "communication_preparations",
                    ["organization_id", "campaign_id", "evaluated_at"])

    op.create_table(
        "communication_recipient_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("preparation_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_kind", sa.String(12), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(12), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("suppression_reason", sa.String(32)),
        sa.ForeignKeyConstraint(
            ["organization_id", "preparation_id"],
            ["communication_preparations.organization_id", "communication_preparations.id"],
            ondelete="RESTRICT", name="fk_comm_recipient_prep_org"),
        sa.UniqueConstraint("preparation_id", "recipient_kind", "recipient_id",
                            name="uq_comm_recipient_once"),
        sa.CheckConstraint("recipient_kind IN ('prospect','promoter')",
                           name="ck_comm_recipient_kind"),
        sa.CheckConstraint("channel IN ('whatsapp','email')",
                           name="ck_comm_recipient_channel"),
        sa.CheckConstraint("status IN ('eligible','suppressed')",
                           name="ck_comm_recipient_state"),
    )
    op.create_index("ix_comm_recipient_org_prep", "communication_recipient_snapshots",
                    ["organization_id", "preparation_id"])


def downgrade() -> None:
    db = op.get_bind()
    for table in (
        "communication_recipient_snapshots",
        "communication_preparations",
        "communication_consent_events",
    ):
        if db.scalar(sa.text(f"SELECT COUNT(*) FROM {table}")):
            raise RuntimeError("Export consent evidence and preparations before downgrade")
    op.drop_index("ix_comm_recipient_org_prep",
                  table_name="communication_recipient_snapshots")
    op.drop_table("communication_recipient_snapshots")
    op.drop_index("ix_comm_prep_campaign", table_name="communication_preparations")
    op.drop_table("communication_preparations")
    op.drop_index("ix_comm_consent_person", table_name="communication_consent_events")
    op.drop_table("communication_consent_events")
