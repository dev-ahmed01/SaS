"""Preserve IST follow-up times and immutable pipeline stage references.

Revision ID: 0022_followup_stage_datetime
Revises: 0021_unique_prospect_mobile
"""
import sqlalchemy as sa
from alembic import op

revision = "0022_followup_stage_datetime"
down_revision = "0021_unique_prospect_mobile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "prospects", sa.Column("next_followup_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "prospect_followups",
        sa.Column("next_followup_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "prospect_followups",
        sa.Column("pipeline_stage_id", sa.Uuid(), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text("""
        SELECT COUNT(*) FROM prospect_followups
        WHERE next_followup_at IS NOT NULL OR pipeline_stage_id IS NOT NULL
    """)) or bind.scalar(sa.text("""
        SELECT COUNT(*) FROM prospects WHERE next_followup_at IS NOT NULL
    """)):
        raise RuntimeError("Export timed follow-ups and pipeline stage history before downgrade")
    op.drop_column("prospect_followups", "pipeline_stage_id")
    op.drop_column("prospect_followups", "next_followup_at")
    op.drop_column("prospects", "next_followup_at")
