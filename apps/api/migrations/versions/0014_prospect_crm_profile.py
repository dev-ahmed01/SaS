"""Optional prospect CRM profile and auditable manual stage transitions.

Revision ID: 0014_prospect_crm_profile
Revises: 0013_strict_contribution_tiers

Manual CRM stage never changes payment-derived sponsorship lifecycle or ledgers.
Existing prospects remain Active in CRM until explicitly reviewed.
"""
import sqlalchemy as sa
from alembic import op

revision = "0014_prospect_crm_profile"
down_revision = "0013_strict_contribution_tiers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, size in (("first_name", 80), ("last_name", 80), ("email", 320), ("occupation", 120)):
        op.add_column("prospects", sa.Column(name, sa.String(size), nullable=True))
    op.add_column("prospects",
        sa.Column("crm_stage", sa.String(12), nullable=False, server_default="active"))
    op.add_column("prospects",
        sa.Column("crm_stage_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("prospects", sa.Column("crm_inactive_reason", sa.String(64), nullable=True))
    op.add_column("prospects", sa.Column("crm_inactive_note", sa.String(500), nullable=True))
    op.create_index("ix_prospects_org_crm_stage", "prospects",
        ["organization_id", "crm_stage", "archived_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.create_check_constraint("ck_prospect_crm_stage", "prospects",
            "crm_stage IN ('active','inactive')")
    elif op.get_bind().dialect.name == "sqlite":
        op.execute("""CREATE TRIGGER trg_prospect_crm_stage_guard
            BEFORE UPDATE OF crm_stage ON prospects
            WHEN NEW.crm_stage NOT IN ('active','inactive')
            BEGIN SELECT RAISE(ABORT, 'Invalid prospect CRM stage'); END""")

    op.create_table(
        "prospect_stage_transitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("prospect_id", sa.Uuid(), nullable=False),
        sa.Column("from_stage", sa.String(12), nullable=False),
        sa.Column("to_stage", sa.String(12), nullable=False),
        sa.Column("reason", sa.String(64), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "actor_admin_id", sa.Uuid(),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "prospect_id"], ["prospects.organization_id", "prospects.id"],
            ondelete="RESTRICT", name="fk_prospect_stage_same_org",
        ),
        sa.CheckConstraint("from_stage IN ('active','inactive')", name="ck_stage_from"),
        sa.CheckConstraint("to_stage IN ('active','inactive')", name="ck_stage_to"),
    )
    op.create_index("ix_prospect_stage_history", "prospect_stage_transitions",
        ["organization_id", "prospect_id", "changed_at"])


def downgrade() -> None:
    # Deliberately do not permit silently destroying reasons and CRM history.
    raise RuntimeError(
        "CRM stage/history downgrade needs an explicit export and data-retention review"
    )
