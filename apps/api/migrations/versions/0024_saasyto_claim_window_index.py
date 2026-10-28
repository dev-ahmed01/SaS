"""Index Saasyto claimed-at windows for 10k-recipient dispatch throttling.

Revision ID: 0024_saasyto_claim_window_index
Revises: 0023_stage_system_identity
"""
from alembic import op

revision = "0024_saasyto_claim_window_index"
down_revision = "0023_stage_system_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_saasyto_recipient_claim_window",
        "saasyto_campaign_recipients",
        ["organization_id", "claimed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_saasyto_recipient_claim_window",
        table_name="saasyto_campaign_recipients",
    )
