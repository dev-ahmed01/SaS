"""One-time, fail-closed repair of a *verified* local SaS demo identity collision.

Never import this from a migration: all other duplicates must be investigated.
Run only after taking and validating a PostgreSQL backup and stopping the API.
"""
import argparse
import json
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import get_settings

EXPECTED_LINKS = {
    "prospect_stage_transitions.prospect_id": 1,
    "sponsorship_rates.prospect_id": 1,
}
APPROVAL = "REMOVE FIRST PROSPECT"


def validate_records(rows: list[dict]) -> tuple[dict, dict]:
    if len(rows) != 2:
        raise RuntimeError("STOP: the two expected legacy prospects are not present")
    disposable = [row for row in rows if row["full_name"] == "First Prospect"]
    if len(disposable) != 1:
        raise RuntimeError("STOP: expected one disposable seeded test identity")
    remove = disposable[0]
    keep = next(row for row in rows if row["id"] != remove["id"])
    if not (
        remove["full_name"] == "First Prospect"
        and keep["full_name"] != remove["full_name"]
        and remove["organization_id"] == keep["organization_id"]
        and remove["mobile_number"] == keep["mobile_number"]
        and remove["crm_stage"] == keep["crm_stage"] == "inactive"
        and remove["archived_at"] is None
        and keep["archived_at"] is None
        and remove["whatsapp_opt_in"] is False
        and remove["whatsapp_verified_at"] is None
    ):
        raise RuntimeError("STOP: identity, consent or status no longer matches")
    return remove, keep


def validate_links(links: dict[str, int], keeper_assignments: int) -> None:
    if links != EXPECTED_LINKS or keeper_assignments != 1:
        raise RuntimeError(
            f"STOP: unexpected linked records: {links}, "
            f"keeper promoter assignments: {keeper_assignments}"
        )


def quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", required=True, type=Path)
    args = parser.parse_args()
    backup = args.backup.expanduser().resolve()
    if not backup.is_file() or backup.stat().st_size < 1024:
        raise SystemExit("STOP: verified pg_dump backup file not found")

    # This is explicitly for the user's local sas_dev DB. Never touch a remote
    # database, staging, production, or a differently named local DB.
    settings = get_settings()
    url = make_url(settings.database_url)
    if not (
        settings.app_env == "development"
        and url.drivername == "postgresql+psycopg"
        and url.host in {"localhost", "127.0.0.1"}
        and (url.port or 5432) == 5432
        and url.database == "sas_dev"
        and url.username == "sas_dev"
    ):
        raise SystemExit("STOP: repair is permitted only on local sas_dev")
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with engine.begin() as db:
            db.execute(text("SELECT pg_advisory_xact_lock(8619210021)"))
            if db.scalar(text("SELECT current_database()")) != "sas_dev":
                raise RuntimeError("STOP: target PostgreSQL database differs")
            revision = db.scalar(text("SELECT version_num FROM alembic_version"))
            if revision != "0020_saasyto_campaigns":
                raise RuntimeError(f"STOP: expected schema 0020, got {revision}")

            collision_count = db.scalar(text("""
                SELECT COUNT(*) FROM (
                    SELECT organization_id, mobile_number FROM prospects
                    GROUP BY organization_id, mobile_number HAVING COUNT(*) > 1
                ) duplicate_groups
            """))
            if collision_count != 1:
                raise RuntimeError("STOP: expected precisely one duplicate phone group")

            rows = list(db.execute(text("""
                SELECT id, organization_id, full_name, mobile_number, crm_stage,
                       archived_at, whatsapp_opt_in, whatsapp_verified_at, version
                FROM prospects
                WHERE (organization_id, mobile_number) IN (
                    SELECT organization_id, mobile_number
                    FROM prospects
                    GROUP BY organization_id, mobile_number HAVING COUNT(*) > 1
                )
                FOR UPDATE
            """)).mappings().all())
            remove, keep = validate_records(rows)
            column_rows = db.execute(text("""
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
            """)).all()
            columns: dict[str, set[str]] = {}
            for table, col in column_rows:
                columns.setdefault(table, set()).add(col)
            links: dict[str, int] = {}
            for table, fields in columns.items():
                for col in ("prospect_id", "recipient_id"):
                    if col not in fields:
                        continue
                    condition = f"{quoted(col)} = :id"
                    if col == "recipient_id" and "recipient_kind" in fields:
                        condition += " AND recipient_kind = 'prospect'"
                    count = db.scalar(text(
                        f"SELECT COUNT(*) FROM public.{quoted(table)} WHERE {condition}"
                    ), {"id": remove["id"]}) or 0
                    if count:
                        links[f"{table}.{col}"] = count
            if "sponsor_snapshot" in columns.get("reminder_batches", set()):
                count = db.scalar(text("""
                    SELECT COUNT(*) FROM reminder_batches
                    WHERE sponsor_snapshot::text LIKE :needle
                """), {"needle": f"%{remove['id']}%"}) or 0
                if count:
                    links["reminder_batches.sponsor_snapshot"] = count

            assignments = db.scalar(text("""
                SELECT COUNT(*) FROM promoter_assignments
                WHERE prospect_id = :id
            """), {"id": keep["id"]}) or 0
            validate_links(links, assignments)

            rate = db.execute(text("""
                SELECT id, organization_id, effective_month, amount_paise,
                       created_at FROM sponsorship_rates
                WHERE prospect_id = :id FOR UPDATE
            """), {"id": remove["id"]}).mappings().one()
            transition = db.execute(text("""
                SELECT id, organization_id, from_stage, to_stage, reason,
                       note, changed_at, actor_admin_id
                FROM prospect_stage_transitions
                WHERE prospect_id = :id FOR UPDATE
            """), {"id": remove["id"]}).mappings().one()
            if not (
                rate["organization_id"] == remove["organization_id"]
                and transition["organization_id"] == remove["organization_id"]
                and transition["to_stage"] == "inactive"
            ):
                raise RuntimeError("STOP: test-rate or stage history changed")
            audit_count = db.scalar(text("""
                SELECT COUNT(*) FROM audit_events
                WHERE entity_type = 'prospect' AND entity_id = :id
            """), {"id": str(remove["id"])}) or 0

            print(f"Validated backup: {backup.name} ({backup.stat().st_size} bytes)")
            print(f"DUPLICATE MOBILE ENDS IN: {remove['mobile_number'][-4:]}")
            print(f"KEEP: {keep['full_name']} ({str(keep['id'])[:8]})")
            print(f"KEEP promoter assignments: {assignments}")
            print(f"REMOVE: {remove['full_name']} ({str(remove['id'])[:8]})")
            print(f"REMOVE only these 2 linked rows: {links}")
            print(f"Historical sponsorship: INR {rate['amount_paise'] / 100}")
            print(f"Stage transition: {transition['from_stage']} -> "
                  f"{transition['to_stage']}")
            print(f"Existing audit events retained: {audit_count}")
            print("No payment, campaign, consent, OTP or other references found.")
            print("This irreversibly deletes only the disposable test identity "
                  "and its 2 links, preserving a recovery audit snapshot.")
            approval = input(f"Type {APPROVAL} to proceed, otherwise cancel: ")
            if approval != APPROVAL:
                raise RuntimeError("CANCELLED: nothing changed")

            snapshot = {
                "removed_id": str(remove["id"]), "name": remove["full_name"],
                "mobile_last4": remove["mobile_number"][-4:],
                "version": remove["version"],
                "sponsorship_rate": {
                    "id": str(rate["id"]),
                    "effective_month": rate["effective_month"].isoformat(),
                    "amount_paise": rate["amount_paise"],
                    "created_at": rate["created_at"].isoformat(),
                },
                "stage_transition": {
                    "id": str(transition["id"]), "from_stage": transition["from_stage"],
                    "to_stage": transition["to_stage"], "reason": transition["reason"],
                    "note": transition["note"],
                    "changed_at": transition["changed_at"].isoformat(),
                    "actor_admin_id": (
                        str(transition["actor_admin_id"])
                        if transition["actor_admin_id"] else None
                    ),
                },
            }
            db.execute(text("""
                INSERT INTO audit_events
                   (id, organization_id, actor_admin_id, action, entity_type,
                    entity_id, before_data, after_data, occurred_at)
                VALUES (:id, :org, NULL, 'prospect.legacy_duplicate_cleanup',
                    'prospect', :entity_id, CAST(:before AS json),
                    CAST(:after AS json), NOW())
            """), {
                "id": uuid.uuid4(), "org": remove["organization_id"],
                "entity_id": str(remove["id"]), "before": json.dumps(snapshot),
                "after": json.dumps({
                    "reason": "duplicate_mobile_before_migration_0021",
                    "retained_id": str(keep["id"]), "backup": backup.name,
                }),
            })
            for table in ("prospect_stage_transitions", "sponsorship_rates"):
                deleted = db.execute(text(
                    f"DELETE FROM {quoted(table)} "
                    "WHERE prospect_id = :id AND organization_id = :org"
                ), {"id": remove["id"], "org": remove["organization_id"]}).rowcount
                if deleted != 1:
                    raise RuntimeError(f"STOP: unexpected delete count in {table}")
            deleted = db.execute(text("""
                DELETE FROM prospects WHERE id = :id AND organization_id = :org
            """), {"id": remove["id"], "org": remove["organization_id"]}).rowcount
            if deleted != 1:
                raise RuntimeError("STOP: test Prospect deletion did not match")
            remaining = db.scalar(text("""
                SELECT COUNT(*) FROM (
                    SELECT organization_id, mobile_number
                    FROM prospects GROUP BY organization_id, mobile_number
                    HAVING COUNT(*) > 1
                ) duplicate_groups
            """))
            if remaining:
                raise RuntimeError("STOP: duplicate identities still exist")
            current = db.execute(text("""
                SELECT mobile_number, version FROM prospects WHERE id = :id
            """), {"id": keep["id"]}).mappings().one()
            if (
                current["mobile_number"] != keep["mobile_number"]
                or current["version"] != keep["version"]
                or db.scalar(text("""
                    SELECT COUNT(*) FROM promoter_assignments
                    WHERE prospect_id = :id
                """), {"id": keep["id"]}) != assignments
            ):
                raise RuntimeError("STOP: retained Prospect changed unexpectedly")
        print("SUCCESS: only known disposable test identity and 2 links removed.")
        print("Keeper, promoter assignment, prior audit and financial history retained.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
