"""Promoters and tenant-safe sponsor assignment history.

Revision ID: 0004_promoters
Revises: 0003_prospects
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_promoters"
down_revision = "0003_prospects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promoters",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id", sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("full_name", sa.String(160), nullable=False),
        sa.Column("mobile_number", sa.String(16), nullable=False),
        sa.Column("whatsapp_number", sa.String(16)),
        sa.Column("area_city", sa.String(120), nullable=False),
        sa.Column("notes", sa.String(1500)),
        sa.Column("whatsapp_opt_in", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_promoters_version_positive"),
        sa.UniqueConstraint("organization_id", "id", name="uq_promoters_org_id"),
        sa.UniqueConstraint(
            "organization_id", "mobile_number", name="uq_promoters_org_mobile"
        ),
    )
    op.create_index("ix_promoters_organization_id", "promoters", ["organization_id"])
    op.create_index("ix_promoters_org_active", "promoters",
                    ["organization_id", "is_active"])
    op.create_table(
        "promoter_assignments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("promoter_id", sa.Uuid(), nullable=False),
        sa.Column("prospect_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("assigned_by_admin_id", sa.Uuid(),
                  sa.ForeignKey("admin_users.id", ondelete="SET NULL")),
        sa.Column("ended_by_admin_id", sa.Uuid(),
                  sa.ForeignKey("admin_users.id", ondelete="SET NULL")),
        sa.ForeignKeyConstraint(
            ["organization_id", "promoter_id"],
            ["promoters.organization_id", "promoters.id"],
            name="fk_assignment_promoter_org", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "prospect_id"],
            ["prospects.organization_id", "prospects.id"],
            name="fk_assignment_prospect_org", ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_assignments_promoter_current", "promoter_assignments",
                    ["promoter_id", "ended_at"])
    op.create_index(
        "uq_assignment_current_prospect", "promoter_assignments",
        ["organization_id", "prospect_id"], unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
        sqlite_where=sa.text("ended_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_assignment_current_prospect", table_name="promoter_assignments")
    op.drop_index("ix_assignments_promoter_current", table_name="promoter_assignments")
    op.drop_table("promoter_assignments")
    op.drop_index("ix_promoters_org_active", table_name="promoters")
    op.drop_index("ix_promoters_organization_id", table_name="promoters")
    op.drop_table("promoters")
