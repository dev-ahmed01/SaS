"""Bind the registration default stage to an immutable database identity.

Revision ID: 0023_stage_system_identity
Revises: 0022_followup_stage_datetime
"""
from collections import defaultdict

import sqlalchemy as sa
from alembic import op

revision = "0023_stage_system_identity"
down_revision = "0022_followup_stage_datetime"
branch_labels = None
depends_on = None

DEFAULT_KEY = "registration_new_inquiry"
ORIGINAL_DESCRIPTION = "Awaiting first documented follow-up"


def upgrade() -> None:
    op.add_column(
        "prospect_stage_definitions",
        sa.Column("system_key", sa.String(48), nullable=True),
    )
    op.create_index(
        "uq_stage_system_key", "prospect_stage_definitions",
        ["organization_id", "system_key"], unique=True,
    )
    connection = op.get_bind()
    rows = connection.execute(sa.text("""
        SELECT id, organization_id, name_key, description
        FROM prospect_stage_definitions
    """)).mappings().all()
    by_org = defaultdict(list)
    for row in rows:
        by_org[row["organization_id"]].append(row)
    for _, stages in by_org.items():
        # Prefer the exact historic label; if renamed, use its unique original
        # description. Ambiguous legacy stages are deliberately not guessed.
        named = [stage for stage in stages if stage["name_key"] == "new inquiry"]
        described = [
            stage for stage in stages
            if stage["description"] == ORIGINAL_DESCRIPTION
        ]
        candidates = named or described
        if len(candidates) == 1:
            connection.execute(sa.text("""
                UPDATE prospect_stage_definitions
                SET system_key = :system_key WHERE id = :stage_id
            """), {"system_key": DEFAULT_KEY, "stage_id": candidates[0]["id"]})


def downgrade() -> None:
    count = op.get_bind().scalar(sa.text("""
        SELECT COUNT(*) FROM prospect_stage_definitions
        WHERE system_key IS NOT NULL
    """))
    if count:
        raise RuntimeError("Export immutable registration-stage identity before downgrade")
    op.drop_index("uq_stage_system_key", table_name="prospect_stage_definitions")
    op.drop_column("prospect_stage_definitions", "system_key")
