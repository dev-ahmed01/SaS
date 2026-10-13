"""Audit and apply fixed two-completed-month Foundation inactivity policy.

Revision ID: 0012_fixed_inactivity_policy
Revises: 0011_prospect_archive_intervals

This migration does not alter prior credit, payment, or sponsorship rate rows.
"""
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0012_fixed_inactivity_policy"
down_revision = "0011_prospect_archive_intervals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    settings = sa.table(
        "organization_settings",
        sa.column("organization_id", sa.Uuid()),
        sa.column("inactivity_months", sa.Integer()),
    )
    audit = sa.table(
        "audit_events",
        sa.column("id", sa.Uuid()),
        sa.column("organization_id", sa.Uuid()),
        sa.column("actor_admin_id", sa.Uuid()),
        sa.column("action", sa.String()),
        sa.column("entity_type", sa.String()),
        sa.column("entity_id", sa.String()),
        sa.column("before_data", sa.JSON()),
        sa.column("after_data", sa.JSON()),
    )
    overridden = connection.execute(
        sa.select(settings.c.organization_id, settings.c.inactivity_months)
        .where(settings.c.inactivity_months != 2)
    ).all()
    if overridden:
        connection.execute(audit.insert(), [{
            "id": uuid.uuid4(),
            "organization_id": row.organization_id,
            "actor_admin_id": None,
            "action": "settings.inactivity_policy_migrated",
            "entity_type": "organization_settings",
            "entity_id": str(row.organization_id),
            "before_data": {"inactivity_months": row.inactivity_months},
            "after_data": {"inactivity_months": 2},
        } for row in overridden])
        connection.execute(
            settings.update().where(settings.c.inactivity_months != 2)
            .values(inactivity_months=2)
        )
    with op.batch_alter_table("organization_settings") as batch:
        batch.drop_constraint("ck_settings_inactivity", type_="check")
        batch.create_check_constraint("ck_settings_inactivity", "inactivity_months = 2")


def downgrade() -> None:
    with op.batch_alter_table("organization_settings") as batch:
        batch.drop_constraint("ck_settings_inactivity", type_="check")
        batch.create_check_constraint(
            "ck_settings_inactivity", "inactivity_months BETWEEN 1 AND 24",
        )
    # Audit is never removed and former thresholds are not silently reapplied.
