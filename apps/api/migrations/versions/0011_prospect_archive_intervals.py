"""Preserve archived sponsorship intervals across restoration.

Revision ID: 0011_prospect_archive_intervals
Revises: 0010_message_dispatches
"""
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0011_prospect_archive_intervals"
down_revision = "0010_message_dispatches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prospect_archive_intervals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("prospect_id", sa.Uuid(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restored_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["organization_id", "prospect_id"],
            ["prospects.organization_id", "prospects.id"],
            name="fk_archive_interval_prospect_org", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "organization_id", "prospect_id", "archived_at",
            name="uq_archive_interval_start",
        ),
        sa.CheckConstraint(
            "restored_at IS NULL OR restored_at >= archived_at",
            name="ck_archive_interval_order",
        ),
    )
    op.create_index(
        "ix_archive_interval_org_prospect", "prospect_archive_intervals",
        ["organization_id", "prospect_id"],
    )

    # Existing versions used a single archived_at marker and cleared it on
    # restore. Reconstruct completed cycles from immutable audit events and
    # preserve currently archived markers even when an old audit is missing.
    connection = op.get_bind()
    audit = sa.table(
        "audit_events",
        sa.column("id", sa.Uuid()),
        sa.column("organization_id", sa.Uuid()),
        sa.column("entity_id", sa.String()),
        sa.column("entity_type", sa.String()),
        sa.column("action", sa.String()),
        sa.column("occurred_at", sa.DateTime(timezone=True)),
    )
    prospect = sa.table(
        "prospects",
        sa.column("id", sa.Uuid()),
        sa.column("organization_id", sa.Uuid()),
        sa.column("archived_at", sa.DateTime(timezone=True)),
    )
    history = sa.table(
        "prospect_archive_intervals",
        sa.column("id", sa.Uuid()),
        sa.column("organization_id", sa.Uuid()),
        sa.column("prospect_id", sa.Uuid()),
        sa.column("archived_at", sa.DateTime(timezone=True)),
        sa.column("restored_at", sa.DateTime(timezone=True)),
    )
    known_prospects = {
        (row.organization_id, row.id): row.archived_at
        for row in connection.execute(sa.select(
            prospect.c.organization_id, prospect.c.id, prospect.c.archived_at
        ))
    }
    active = {}
    intervals = []
    for row in connection.execute(
        sa.select(
            audit.c.organization_id, audit.c.entity_id,
            audit.c.action, audit.c.occurred_at,
        ).where(
            audit.c.entity_type == "prospect",
            audit.c.action.in_(("prospect.archived", "prospect.restored")),
        ).order_by(audit.c.occurred_at, audit.c.id)
    ):
        try:
            sponsor_id = uuid.UUID(row.entity_id)
        except (ValueError, AttributeError, TypeError):
            continue
        key = (row.organization_id, sponsor_id)
        if key not in known_prospects:
            continue
        if row.action == "prospect.archived":
            active[key] = row.occurred_at
        elif key in active:
            start = active.pop(key)
            intervals.append({
                "id": uuid.uuid4(), "organization_id": key[0],
                "prospect_id": key[1], "archived_at": start,
                "restored_at": row.occurred_at,
            })
    for key, archived_at in known_prospects.items():
        if archived_at is not None:
            intervals.append({
                "id": uuid.uuid4(), "organization_id": key[0],
                "prospect_id": key[1],
                "archived_at": active.get(key, archived_at),
                "restored_at": None,
            })
    if intervals:
        connection.execute(history.insert(), intervals)


def downgrade() -> None:
    # Existing archive interval history would be lost. Never downgrade a live
    # financial database without an explicitly reviewed recovery plan.
    op.drop_index(
        "ix_archive_interval_org_prospect",
        table_name="prospect_archive_intervals",
    )
    op.drop_table("prospect_archive_intervals")
