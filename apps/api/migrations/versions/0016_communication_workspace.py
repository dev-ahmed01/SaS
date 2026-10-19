"""Reusable communication planning, no automatic transport.

Revision ID: 0016_communication
Revises: 0015_promoters_pipeline
"""
import sqlalchemy as sa
from alembic import op

revision = "0016_communication"
down_revision = "0015_promoters_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "communication_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey(
            "organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_key", sa.String(100), nullable=False),
        sa.Column("channel", sa.String(12), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(160)),
        sa.Column("body", sa.String(1200), nullable=False),
        sa.Column("provider_template_id", sa.String(160)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "id", name="uq_comm_template_org_id"),
        sa.UniqueConstraint("organization_id", "name_key", name="uq_comm_template_name"),
        sa.CheckConstraint("channel IN ('whatsapp','email')", name="ck_comm_template_channel"),
    )
    op.create_index("ix_communication_templates_organization_id",
                    "communication_templates", ["organization_id"])

    op.create_table(
        "communication_campaigns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey(
            "organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("template_id", sa.Uuid(), sa.ForeignKey(
            "communication_templates.id", ondelete="RESTRICT")),
        sa.Column("channel", sa.String(12), nullable=False),
        sa.Column("audience", sa.String(16), nullable=False),
        sa.Column("segment", sa.String(16), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(160)),
        sa.Column("body", sa.String(1200), nullable=False),
        sa.Column("provider_template_id", sa.String(160)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("planned_for", sa.DateTime(timezone=True)),
        sa.Column("eligible_snapshot", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidate_snapshot", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_admin_id", sa.Uuid(), sa.ForeignKey(
            "admin_users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "id", name="uq_comm_campaign_org_id"),
        sa.UniqueConstraint("organization_id", "request_id", name="uq_comm_campaign_request"),
        sa.CheckConstraint("channel IN ('whatsapp','email')", name="ck_comm_campaign_channel"),
        sa.CheckConstraint("audience IN ('prospects','promoters','both')",
                           name="ck_comm_campaign_audience"),
        sa.CheckConstraint("segment IN ('all','active','inactive','unpaid')",
                           name="ck_comm_campaign_segment"),
        sa.CheckConstraint("status IN ('draft','scheduled','cancelled')",
                           name="ck_comm_campaign_status"),
    )
    op.create_index("ix_communication_campaigns_organization_id",
                    "communication_campaigns", ["organization_id"])
    op.create_index("ix_comm_campaign_org_created", "communication_campaigns",
                    ["organization_id", "created_at"])

    op.create_table(
        "communication_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey(
            "organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_key", sa.String(100), nullable=False),
        sa.Column("trigger_kind", sa.String(36), nullable=False),
        sa.Column("channel", sa.String(12), nullable=False),
        sa.Column("audience", sa.String(16), nullable=False),
        sa.Column("segment", sa.String(16), nullable=False),
        sa.Column("template_id", sa.Uuid(), sa.ForeignKey(
            "communication_templates.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "id", name="uq_comm_rule_org_id"),
        sa.UniqueConstraint("organization_id", "name_key", name="uq_comm_rule_name"),
    )
    op.create_index("ix_communication_rules_organization_id",
                    "communication_rules", ["organization_id"])


def downgrade() -> None:
    db = op.get_bind()
    for table in (
        "communication_rules", "communication_campaigns", "communication_templates"
    ):
        if db.scalar(sa.text(f"SELECT COUNT(*) FROM {table}")):
            raise RuntimeError("Export communication plans and templates before downgrade")
    op.drop_index("ix_communication_rules_organization_id",
                  table_name="communication_rules")
    op.drop_table("communication_rules")
    op.drop_index("ix_comm_campaign_org_created",
                  table_name="communication_campaigns")
    op.drop_index("ix_communication_campaigns_organization_id",
                  table_name="communication_campaigns")
    op.drop_table("communication_campaigns")
    op.drop_index("ix_communication_templates_organization_id",
                  table_name="communication_templates")
    op.drop_table("communication_templates")
