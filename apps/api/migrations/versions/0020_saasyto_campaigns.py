"""Durable, tenant-bound Saasyto campaign authorization and recipient claims.

Revision ID: 0020_saasyto_campaigns
Revises: 0019_sponsor_otp
"""
import sqlalchemy as sa
from alembic import op

revision = "0020_saasyto_campaigns"
down_revision = "0019_sponsor_otp"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "saasyto_campaign_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by_admin_id", sa.Uuid(), nullable=False),
        sa.Column("eligible_count", sa.Integer(), nullable=False),
        sa.Column("suppressed_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("organization_id", "campaign_id",
                            name="uq_saasyto_run_campaign"),
        sa.UniqueConstraint("organization_id", "id", name="uq_saasyto_run_org_id"),
        sa.ForeignKeyConstraint(
            ["organization_id", "campaign_id"],
            ["communication_campaigns.organization_id", "communication_campaigns.id"],
            ondelete="RESTRICT", name="fk_saasyto_run_campaign_org",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_admin_id"], ["admin_users.id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("status IN ('approved','cancelled','completed')",
                           name="ck_saasyto_run_status"),
    )
    op.create_index(
        "ix_saasyto_due", "saasyto_campaign_runs",
        ["organization_id", "status", "due_at"],
    )
    op.create_table(
        "saasyto_campaign_recipients",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_kind", sa.String(12), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(32)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["organization_id", "run_id"],
            ["saasyto_campaign_runs.organization_id", "saasyto_campaign_runs.id"],
            ondelete="RESTRICT", name="fk_saasyto_recipient_run_org",
        ),
        sa.UniqueConstraint("run_id", "recipient_kind", "recipient_id",
                            name="uq_saasyto_run_recipient"),
        sa.CheckConstraint(
            "recipient_kind IN ('prospect','promoter')",
            name="ck_saasyto_recipient_kind",
        ),
        sa.CheckConstraint(
            "status IN ('queued','claimed','accepted_unverified','rejected',"
            "'unknown','suppressed')",
            name="ck_saasyto_recipient_status",
        ),
    )
    op.create_index(
        "ix_saasyto_recipient_queue", "saasyto_campaign_recipients",
        ["organization_id", "status", "run_id"],
    )


def downgrade():
    bind = op.get_bind()
    if (bind.scalar(sa.text("SELECT COUNT(*) FROM saasyto_campaign_runs"))
            or bind.scalar(sa.text("SELECT COUNT(*) FROM saasyto_campaign_recipients"))):
        raise RuntimeError("Export campaign sending audit records before downgrade")
    op.drop_index("ix_saasyto_recipient_queue", table_name="saasyto_campaign_recipients")
    op.drop_table("saasyto_campaign_recipients")
    op.drop_index("ix_saasyto_due", table_name="saasyto_campaign_runs")
    op.drop_table("saasyto_campaign_runs")
