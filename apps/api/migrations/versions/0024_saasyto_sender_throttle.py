"""Reserve sender-level Saasyto dispatch slots across concurrent workers.

Revision ID: 0024_saasyto_sender_throttle
Revises: 0023_stage_system_identity
"""
import sqlalchemy as sa
from alembic import op

revision = "0024_saasyto_sender_throttle"
down_revision = "0023_stage_system_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "saasyto_dispatch_throttles",
        sa.Column("sender_digest", sa.String(64), primary_key=True),
        sa.Column("next_allowed_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Normalize legacy whitespace in optional WhatsApp numbers when checking
    # shared-address opt-outs. Mobile-number lookups already have org indexes.
    for table in ("prospects", "promoters"):
        op.execute(sa.text(
            f"CREATE INDEX ix_{table}_org_whatsapp_normalized "
            f"ON {table} (organization_id, replace(whatsapp_number, ' ', ''))"
        ))


def downgrade():
    for table in ("promoters", "prospects"):
        op.drop_index(f"ix_{table}_org_whatsapp_normalized", table_name=table)
    op.drop_table("saasyto_dispatch_throttles")
