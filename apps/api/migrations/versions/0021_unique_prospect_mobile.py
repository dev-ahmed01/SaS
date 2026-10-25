"""Guard prospect identity by organization + normalized phone.

Revision ID: 0021_unique_prospect_mobile
Revises: 0020_saasyto_campaigns

This migration intentionally fails on legacy duplicates rather than silently
merging donor identities, payment histories or promoter assignments.
"""
import sqlalchemy as sa
from alembic import op

revision = "0021_unique_prospect_mobile"
down_revision = "0020_saasyto_campaigns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    conflicting_groups = bind.scalar(sa.text("""
        SELECT COUNT(*) FROM (
            SELECT organization_id, mobile_number
            FROM prospects
            GROUP BY organization_id, mobile_number
            HAVING COUNT(*) > 1
        ) AS conflicting_numbers
    """))
    if conflicting_groups:
        raise RuntimeError(
            f"{conflicting_groups} duplicate prospect mobile groups exist. "
            "Review and correct their identity and linked financial records "
            "before applying this migration; do not auto-merge them."
        )
    op.create_index(
        "uq_prospects_org_mobile", "prospects",
        ["organization_id", "mobile_number"], unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_prospects_org_mobile", table_name="prospects")
