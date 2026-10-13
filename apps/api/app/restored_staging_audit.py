"""Read-only integrity audit for a *separately restored* staging database.

No backup, restore, DDL, worker start, webhook or message is performed here.
The actual restore must be done by an approved operator on an isolated target.
Output contains aggregate counts only; donor/recipient data is never displayed.
"""
import json
import os
from urllib.parse import unquote

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

REQUIRED_TABLES = (
    "alembic_version",
    "organizations",
    "organization_settings",
    "prospects",
    "sponsorship_rates",
    "verified_credits",
    "manual_collections",
    "manual_collection_reversals",
    "payout_plans",
    "payout_payments",
    "audit_events",
    "message_outbox",
)
EXPECTED_MIGRATION = "0013_strict_contribution_tiers"


def validate_restored_target(raw_url: str, *, app_env: str, approved_name: str):
    """Require a separate named restore target and explicit operator opt-in."""
    try:
        target = make_url(raw_url)
    except (ArgumentError, ValueError, TypeError) as exc:
        raise ValueError("Explicit restored-target PostgreSQL URL required") from exc
    db_name = unquote(target.database or "")
    if not (
        app_env == "staging"
        and target.drivername == "postgresql+psycopg"
        and db_name.startswith("sas_recovery_")
        and len(db_name) >= len("sas_recovery_") + 8
        and target.host
        and target.username
        and target.password
        and approved_name == db_name
        and target.query.get("sslmode") == "verify-full"
    ):
        raise ValueError("A dedicated TLS-verified, explicitly approved staging restore is required")
    return target


def audit_database(engine) -> dict:
    """Use a read-only PostgreSQL transaction and verify accounting invariants."""
    if engine.dialect.name != "postgresql":
        raise ValueError("Only a restored PostgreSQL database may be audited")
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '15s'")
            available = set(inspect(connection).get_table_names(schema="public"))
            missing = set(REQUIRED_TABLES) - available
            if missing:
                raise AssertionError("Missing required application tables")
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars().all()
            if version != [EXPECTED_MIGRATION]:
                raise AssertionError("Restored schema is not at approved migration head")

            tests = {
                "collection_to_credit": """
                    SELECT COUNT(*) FROM manual_collections m
                    LEFT JOIN verified_credits c
                      ON c.id=m.verified_credit_id
                      AND c.organization_id=m.organization_id
                    WHERE c.id IS NULL
                       OR c.prospect_id <> m.prospect_id
                       OR c.amount_paise <> m.amount_paise
                       OR c.period_month <> m.period_month
                """,
                "credit_to_sponsor": """
                    SELECT COUNT(*) FROM verified_credits c
                    LEFT JOIN prospects p ON p.id=c.prospect_id
                    WHERE p.id IS NULL OR p.organization_id <> c.organization_id
                """,
                "rate_to_sponsor": """
                    SELECT COUNT(*) FROM sponsorship_rates c
                    LEFT JOIN prospects p ON p.id=c.prospect_id
                    WHERE p.id IS NULL OR p.organization_id <> c.organization_id
                """,
                "reversal_to_receipt": """
                    SELECT COUNT(*) FROM manual_collection_reversals r
                    LEFT JOIN manual_collections c ON c.id=r.collection_id
                       AND c.organization_id=r.organization_id
                    WHERE c.id IS NULL
                """,
                "receipt_messages": """
                    SELECT COUNT(*) FROM message_outbox m
                    LEFT JOIN manual_collections c ON c.id=m.collection_id
                       AND c.organization_id=m.organization_id
                    WHERE c.id IS NULL
                """,
            }
            for label, query in tests.items():
                if connection.execute(text(query)).scalar_one() != 0:
                    raise AssertionError("Restored financial integrity failed: " + label)

            # Both sides refer exclusively to verified credit rows tied to a
            # manual collection, excluding only fully reversed manual entries.
            net_cash = connection.execute(text("""
                SELECT COALESCE(SUM(c.amount_paise),0)
                FROM manual_collections c
                WHERE NOT EXISTS (
                    SELECT 1 FROM manual_collection_reversals r
                    WHERE r.organization_id=c.organization_id
                      AND r.collection_id=c.id
                )
            """)).scalar_one()
            net_credit = connection.execute(text("""
                SELECT COALESCE(SUM(v.amount_paise),0)
                FROM verified_credits v
                JOIN manual_collections c ON
                    c.verified_credit_id=v.id
                    AND c.organization_id=v.organization_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM manual_collection_reversals r
                    WHERE r.organization_id=c.organization_id
                      AND r.collection_id=c.id
                )
            """)).scalar_one()
            if net_cash != net_credit:
                raise AssertionError("Net manual ledger does not reconcile")

            # Restored environments must not be safely startable for outbound
            # messaging by accident, even if the audit itself starts no worker.
            armed = connection.execute(text("""
                SELECT COUNT(*) FROM organization_settings
                WHERE automation_enabled IS TRUE
            """)).scalar_one()
            if armed:
                raise AssertionError("Restored tenant settings contain active automation")

            totals = {}
            for label, table in (
                ("organizations", "organizations"),
                ("sponsors", "prospects"),
                ("recorded_receipts", "manual_collections"),
                ("reversals", "manual_collection_reversals"),
                ("payout_attestations", "payout_payments"),
                ("audit_events", "audit_events"),
            ):
                totals[label] = connection.execute(
                    text("SELECT COUNT(*) FROM " + table)
                ).scalar_one()
            transaction.rollback()
            return {
                "restored_postgres_read_only": True,
                "migration_verified": True,
                "tenant_relationships_verified": True,
                "net_manual_ledger_verified": True,
                "messaging_automation_off": True,
                "row_counts": totals,
                "identities_or_receipt_references_logged": False,
                "real_backup_origin_or_business_rpo_rto_verified": False,
            }
        finally:
            if transaction.is_active:
                transaction.rollback()


def main() -> int:
    """Run locally with a staging read-only credential, not in shared CI."""
    try:
        target = validate_restored_target(
            os.environ.get("SAS_RESTORED_TARGET_URL", ""),
            app_env=os.environ.get("APP_ENV", ""),
            approved_name=os.environ.get("SAS_RESTORE_TARGET_APPROVED", ""),
        )
        engine = create_engine(target, pool_pre_ping=True, connect_args={
            "options": "-c default_transaction_read_only=on"
        })
        try:
            result = audit_database(engine)
        finally:
            engine.dispose()
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        # Do not leak connection strings, donors, SQL row contents or credentials.
        print("Staging restore audit BLOCKED: " + type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
