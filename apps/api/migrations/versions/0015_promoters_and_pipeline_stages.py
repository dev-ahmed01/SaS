"""Extend promoter contact profiles and add configurable Prospect-only pipeline stages.

Revision ID: 0015_promoters_pipeline
Revises: 0014_prospect_crm_profile

Existing sponsor accounting and manual Active/Inactive stage remain unchanged.
"""
import sqlalchemy as sa
from alembic import op

revision = "0015_promoters_pipeline"
down_revision = "0014_prospect_crm_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, size in (
        ("first_name", 80), ("last_name", 80), ("email", 320), ("occupation", 120),
    ):
        op.add_column("promoters", sa.Column(name, sa.String(size), nullable=True))
    op.create_table(
        "prospect_stage_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id", sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("name_key", sa.String(80), nullable=False),
        sa.Column("description", sa.String(300), nullable=True),
        sa.Column("color", sa.String(7), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("organization_id", "id", name="uq_stage_definition_org_id"),
        sa.UniqueConstraint(
            "organization_id", "name_key", name="uq_stage_definition_org_name",
        ),
    )
    op.create_index(
        "ix_stage_definitions_org_sort", "prospect_stage_definitions",
        ["organization_id", "sort_order", "name_key"],
    )
    op.add_column("prospects", sa.Column("pipeline_stage_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_prospects_org_pipeline_stage", "prospects",
        ["organization_id", "pipeline_stage_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_prospect_pipeline_stage_org", "prospects", "prospect_stage_definitions",
            ["organization_id", "pipeline_stage_id"], ["organization_id", "id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    db = op.get_bind()
    count = db.scalar(sa.text("SELECT COUNT(*) FROM prospect_stage_definitions"))
    assigned = db.scalar(sa.text(
        "SELECT COUNT(*) FROM prospects WHERE pipeline_stage_id IS NOT NULL"
    ))
    enriched = db.scalar(sa.text("""
        SELECT COUNT(*) FROM promoters WHERE
        first_name IS NOT NULL OR last_name IS NOT NULL
        OR email IS NOT NULL OR occupation IS NOT NULL
    """))
    if count or assigned or enriched:
        raise RuntimeError("Export promoter profiles and pipeline stages before downgrade")
    if db.dialect.name == "postgresql":
        op.drop_constraint(
            "fk_prospect_pipeline_stage_org", "prospects", type_="foreignkey"
        )
    op.drop_index("ix_prospects_org_pipeline_stage", table_name="prospects")
    op.drop_column("prospects", "pipeline_stage_id")
    op.drop_index(
        "ix_stage_definitions_org_sort", table_name="prospect_stage_definitions"
    )
    op.drop_table("prospect_stage_definitions")
    for name in ("occupation", "email", "last_name", "first_name"):
        op.drop_column("promoters", name)
