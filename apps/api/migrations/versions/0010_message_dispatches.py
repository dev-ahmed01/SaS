"""Durable WhatsApp dispatch attempts and signed provider receipts.

Revision ID: 0010_message_dispatches
Revises: 0009_reminder_intents
"""
import sqlalchemy as sa
from alembic import op

revision = "0010_message_dispatches"
down_revision = "0009_reminder_intents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("message_outbox") as batch:
        batch.create_unique_constraint("uq_outbox_org_id", ["organization_id", "id"])
    with op.batch_alter_table("reminder_intents") as batch:
        batch.create_unique_constraint("uq_reminder_intent_org_id", ["organization_id", "id"])
    op.create_table(
        "message_dispatches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("outbox_id", sa.Uuid()),
        sa.Column("reminder_intent_id", sa.Uuid()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("failure_code", sa.String(32)),
        sa.Column("provider_message_id", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["organization_id", "outbox_id"],
            ["message_outbox.organization_id", "message_outbox.id"],
            name="fk_dispatch_outbox_org", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "reminder_intent_id"],
            ["reminder_intents.organization_id", "reminder_intents.id"],
            name="fk_dispatch_reminder_org", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("organization_id", "id", name="uq_dispatch_org_id"),
        sa.UniqueConstraint("organization_id", "outbox_id", name="uq_dispatch_outbox"),
        sa.UniqueConstraint(
            "organization_id", "reminder_intent_id", name="uq_dispatch_reminder"
        ),
        sa.CheckConstraint(
            "(outbox_id IS NOT NULL AND reminder_intent_id IS NULL) OR "
            "(outbox_id IS NULL AND reminder_intent_id IS NOT NULL)",
            name="ck_dispatch_exactly_one_source",
        ),
        sa.CheckConstraint(
            "status IN ('claimed', 'accepted', 'unknown', 'failed', "
            "'cancelled', 'sent', 'delivered')", name="ck_dispatch_status",
        ),
    )
    op.create_index(
        "ix_dispatch_org_status", "message_dispatches", ["organization_id", "status"]
    )
    op.create_table(
        "message_delivery_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("dispatch_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("provider_message_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "dispatch_id"],
            ["message_dispatches.organization_id", "message_dispatches.id"],
            name="fk_delivery_event_dispatch_org", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "organization_id", "event_id", name="uq_delivery_callback_event"
        ),
        sa.CheckConstraint(
            "status IN ('sent', 'delivered', 'failed')",
            name="ck_delivery_callback_state",
        ),
    )


def downgrade() -> None:
    op.drop_table("message_delivery_events")
    op.drop_index("ix_dispatch_org_status", table_name="message_dispatches")
    op.drop_table("message_dispatches")
    with op.batch_alter_table("reminder_intents") as batch:
        batch.drop_constraint("uq_reminder_intent_org_id", type_="unique")
    with op.batch_alter_table("message_outbox") as batch:
        batch.drop_constraint("uq_outbox_org_id", type_="unique")
