"""Owner-managed payout purposes, non-destructive history preservation.

Revision ID: 0027_field_options
Revises: 0026_admin_roles
"""
import re
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0027_field_options"
down_revision = "0026_admin_roles"
branch_labels = None
depends_on = None

DEFAULT_PURPOSES = (
    "Rent", "Utilities", "Maintenance", "Salary", "Vendor payment",
    "Reimbursement", "Other",
)


def _slug(label: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return (value or "legacy")[:48]


def upgrade() -> None:
    op.create_table(
        "organization_field_options",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("field_key", sa.String(32), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("label", sa.String(240), nullable=False),
        sa.Column("label_key", sa.String(240), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"],
                                ondelete="RESTRICT"),
        sa.UniqueConstraint("organization_id", "id", name="uq_field_option_org_id"),
        sa.UniqueConstraint("organization_id", "field_key", "code",
                            name="uq_field_option_code"),
        sa.UniqueConstraint("organization_id", "field_key", "label_key",
                            name="uq_field_option_label"),
        sa.CheckConstraint("field_key IN ('payout_purpose')",
                           name="ck_field_option_key"),
        sa.CheckConstraint("version >= 1", name="ck_field_option_version"),
    )
    op.create_index("ix_organization_field_options_organization_id",
                    "organization_field_options", ["organization_id"])
    op.create_index("ix_field_option_active_order", "organization_field_options",
                    ["organization_id", "field_key", "is_active", "sort_order"])
    with op.batch_alter_table("payout_plans") as batch:
        batch.add_column(sa.Column("purpose_option_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_payout_purpose_org", "organization_field_options",
            ["organization_id", "purpose_option_id"], ["organization_id", "id"],
            ondelete="RESTRICT",
        )

    # For established organizations, load the standard choices AND every
    # historic purpose as separate, active, owner-editable options. Existing
    # plan purpose snapshots are never changed by this migration.
    conn = op.get_bind()
    org = sa.table("organizations", sa.column("id", sa.Uuid()))
    plans = sa.table(
        "payout_plans", sa.column("organization_id", sa.Uuid()),
        sa.column("purpose_option_id", sa.Uuid()), sa.column("purpose", sa.String()),
    )
    options = sa.table(
        "organization_field_options",
        sa.column("id", sa.Uuid()), sa.column("organization_id", sa.Uuid()),
        sa.column("field_key", sa.String()), sa.column("code", sa.String()),
        sa.column("label", sa.String()), sa.column("label_key", sa.String()),
        sa.column("is_active", sa.Boolean()), sa.column("sort_order", sa.Integer()),
        sa.column("version", sa.Integer()),
    )
    organizations = list(conn.execute(sa.select(org.c.id)).scalars())
    for organization_id in organizations:
        history = list(conn.execute(
            sa.select(plans.c.purpose)
            .where(plans.c.organization_id == organization_id)
            .distinct()
        ).scalars())
        all_labels = list(DEFAULT_PURPOSES) + sorted(
            (p.strip() for p in history if isinstance(p, str) and p.strip()),
            key=str.casefold,
        )
        ids: dict[str, uuid.UUID] = {}
        for label in all_labels:
            label_key = label.casefold()
            if label_key in ids:
                continue
            option_id = uuid.uuid4()
            ids[label_key] = option_id
            conn.execute(options.insert().values(
                id=option_id, organization_id=organization_id,
                field_key="payout_purpose",
                code=f"{_slug(label)}-{option_id.hex[:8]}",
                label=label, label_key=label_key,
                is_active=True, sort_order=len(ids) * 10, version=1,
            ))
        for old_label in history:
            if isinstance(old_label, str):
                option_id = ids.get(old_label.strip().casefold())
                if option_id:
                    conn.execute(
                        plans.update()
                        .where(plans.c.organization_id == organization_id)
                        .where(plans.c.purpose == old_label)
                        .values(purpose_option_id=option_id)
                    )


def downgrade() -> None:
    # Removing configuration must never erase original payout purpose snapshots.
    with op.batch_alter_table("payout_plans") as batch:
        batch.drop_constraint("fk_payout_purpose_org", type_="foreignkey")
        batch.drop_column("purpose_option_id")
    op.drop_index("ix_field_option_active_order",
                  table_name="organization_field_options")
    op.drop_index("ix_organization_field_options_organization_id",
                  table_name="organization_field_options")
    op.drop_table("organization_field_options")
