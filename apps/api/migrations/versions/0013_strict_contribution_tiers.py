"""Enforce ₹250 increments for NEW Admin-recorded manual collections.

Revision ID: 0013_strict_contribution_tiers
Revises: 0012_fixed_inactivity_policy

Historic manually attested receipts are immutable and are not changed.
PostgreSQL NOT VALID accepts old rows but checks every future insert/update.
SQLite inserts are guarded by a trigger, avoiding a table rewrite.
"""
from alembic import op

revision = "0013_strict_contribution_tiers"
down_revision = "0012_fixed_inactivity_policy"
branch_labels = None
depends_on = None

RULE = "amount_paise BETWEEN 25000 AND 1000000000 AND amount_paise % 25000 = 0"


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            "ALTER TABLE manual_collections "
            "ADD CONSTRAINT ck_manual_collection_new_250_tiers "
            f"CHECK ({RULE}) NOT VALID"
        )
    elif dialect == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_manual_collection_250_tiers_insert
            BEFORE INSERT ON manual_collections
            WHEN NOT (NEW.amount_paise BETWEEN 25000 AND 1000000000
                      AND NEW.amount_paise % 25000 = 0)
            BEGIN
                SELECT RAISE(ABORT, 'Manual collection must use a 250 INR increment');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_manual_collection_250_tiers_update
            BEFORE UPDATE OF amount_paise ON manual_collections
            WHEN NEW.amount_paise <> OLD.amount_paise
              AND NOT (NEW.amount_paise BETWEEN 25000 AND 1000000000
                       AND NEW.amount_paise % 25000 = 0)
            BEGIN
                SELECT RAISE(ABORT, 'Manual collection must use a 250 INR increment');
            END
        """)
    else:
        raise RuntimeError(f"Unsupported database dialect for financial policy: {dialect}")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            "ALTER TABLE manual_collections "
            "DROP CONSTRAINT ck_manual_collection_new_250_tiers"
        )
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_manual_collection_250_tiers_update")
        op.execute("DROP TRIGGER IF EXISTS trg_manual_collection_250_tiers_insert")
    else:
        raise RuntimeError(f"Unsupported database dialect for financial policy: {dialect}")
