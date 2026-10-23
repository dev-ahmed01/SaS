"""Start new prospects inactive and enable auditable follow-up activity.

Revision ID: 0018_crm_fathom
Revises: 0017_comm_preflight
"""
import sqlalchemy as sa
from alembic import op

revision = "0018_crm_fathom"
down_revision = "0017_comm_preflight"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prospect_followups",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("prospect_id", sa.Uuid(), nullable=False),
        sa.Column("actor_admin_id", sa.Uuid(),
                  sa.ForeignKey("admin_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("notes", sa.String(500), nullable=False),
        sa.Column("next_followup_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id", "prospect_id"],
            ["prospects.organization_id", "prospects.id"],
            ondelete="RESTRICT", name="fk_followup_prospect_org",
        ),
    )
    op.create_index(
        "ix_followups_org_prospect_created", "prospect_followups",
        ["organization_id", "prospect_id", "created_at"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column("prospects", "crm_stage", server_default="inactive")
    else:
        # SQLite table default remains historically 'active'; all API writes
        # explicitly set inactive, while the ORM default also uses inactive.
        pass


def downgrade() -> None:
    db = op.get_bind()
    if db.scalar(sa.text("SELECT COUNT(*) FROM prospect_followups")):
        raise RuntimeError("Export prospect follow-up activity before downgrade")
    if db.dialect.name == "postgresql":
        op.alter_column("prospects", "crm_stage", server_default="active")
    op.drop_index("ix_followups_org_prospect_created", table_name="prospect_followups")
    op.drop_table("prospect_followups")
