"""CI-only PostgreSQL 16 backup/restore. NEVER use with staging or production.

The source is pinned to an explicitly opted-in local ephemeral database.
Creates its own uniquely named disposable database and removes it on exit.
Contains only synthetic records; it never sends messages or transfers money.
"""
import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.accounting import effective_credits
from app.models import (
    AuditEvent, ManualCollection, ManualCollectionReversal, MessageOutbox,
    Organization, OrganizationSettings, PayoutPlan, Prospect, SponsorshipRate,
    VerifiedCredit,
)

PREFIX = "sas_restore_ci_"


def validate_ci_scope(raw_url: str, env: str, opt_in: str):
    """Fail closed: never trust an arbitrary DATABASE_URL for a destructive drill."""
    try:
        url = make_url(raw_url)
    except (ValueError, TypeError) as exc:
        raise ValueError("Explicit local CI connection required") from exc
    if not (
        env == "test" and opt_in == "1"
        and url.drivername == "postgresql+psycopg"
        and url.host in {"localhost", "127.0.0.1"}
        and url.port == 5432 and url.database == "sas_ci"
        and url.username == "sas_ci" and bool(url.password)
        and not url.query
    ):
        raise ValueError("Only opted-in local synthetic sas_ci is permitted")
    return url


def snapshot(engine):
    """Row-for-row comparison of every public table, never printing its data."""
    state = {}
    with engine.connect() as connection:
        inspector = inspect(engine)
        for name in sorted(inspector.get_table_names(schema="public")):
            if not name.replace("_", "").isalnum():
                raise ValueError("Unexpected table identifier")
            columns = [c["name"] for c in inspector.get_columns(name)]
            fingerprints = []
            rows = connection.execute(text('SELECT * FROM public."' + name + '"'))
            for row in rows.mappings():
                encoded = json.dumps(
                    {c: row[c] for c in columns},
                    sort_keys=True, default=str, ensure_ascii=False,
                ).encode("utf-8")
                fingerprints.append(hashlib.sha256(encoded).digest())
            fingerprints.sort()
            state[name] = (
                len(fingerprints), hashlib.sha256(b"".join(fingerprints)).hexdigest()
            )
    return state


def synthetic_seed(engine):
    """Two receipts, one reversal, one planned (not executed) payout."""
    period = date(2026, 10, 1)
    stamp = datetime(2026, 10, 13, 10, tzinfo=UTC)
    with Session(engine) as db:
        org = Organization(name="SAS Synthetic CI Recovery Organization")
        db.add(org)
        db.flush()
        db.add(OrganizationSettings(
            organization_id=org.id, currency_code="INR", timezone="Asia/Kolkata",
            default_contribution_paise=25000, sponsor_reminder_day=5,
            promoter_reminder_day=20, inactivity_months=2, automation_enabled=False,
        ))
        sponsor = Prospect(
            organization_id=org.id, full_name="Synthetic CI Sponsor",
            mobile_number="+919000000099", area_city="CI-Only",
            monthly_contribution_paise=50000, start_month=period,
            whatsapp_opt_in=False, lifecycle_status="active",
            last_verified_payment_at=stamp, version=1,
        )
        db.add(sponsor)
        db.flush()
        db.add(SponsorshipRate(
            organization_id=org.id, prospect_id=sponsor.id,
            effective_month=period, amount_paise=50000,
        ))
        for index in range(2):
            credit = VerifiedCredit(
                organization_id=org.id, prospect_id=sponsor.id,
                period_month=period, amount_paise=25000,
                source_type="manual_attested",
                source_key="manual:ci-restore-" + uuid.uuid4().hex,
                verified_at=stamp,
            )
            db.add(credit)
            db.flush()
            entry = ManualCollection(
                organization_id=org.id, prospect_id=sponsor.id,
                verified_credit_id=credit.id, request_id=uuid.uuid4(),
                request_payload_hash=uuid.uuid4().hex * 2,
                reference_digest=uuid.uuid4().hex * 2,
                reference_mask="****CI99", received_on=period,
                period_month=period, payment_method="upi",
                amount_paise=25000,
            )
            db.add(entry)
            db.flush()
            db.add(MessageOutbox(
                organization_id=org.id, prospect_id=sponsor.id,
                collection_id=entry.id, event_type="collection_recorded",
                status="suppressed", suppress_reason="consent_missing",
            ))
            if index == 1:
                db.add(ManualCollectionReversal(
                    organization_id=org.id, collection_id=entry.id,
                    request_id=uuid.uuid4(), reason_code="wrong_amount",
                ))
        db.add(PayoutPlan(
            organization_id=org.id, create_request_id=uuid.uuid4(),
            create_hash=uuid.uuid4().hex * 2,
            payee_name="Synthetic Planned Recipient", purpose="CI-only planned grant",
            cadence="one_time", start_month=period,
            scheduled_on=date(2026, 10, 22), amount_paise=100000,
        ))
        db.add(AuditEvent(
            organization_id=org.id, actor_admin_id=None,
            action="ci.synthetic_restore", entity_type="organization",
            entity_id=str(org.id), before_data=None,
            after_data={"synthetic": True},
        ))
        db.commit()
        return org.id


def verify_finance(engine, org):
    with Session(engine) as db:
        settings = db.get(OrganizationSettings, org)
        records = db.scalars(select(ManualCollection).where(
            ManualCollection.organization_id == org
        )).all()
        reversals = db.scalars(select(ManualCollectionReversal).where(
            ManualCollectionReversal.organization_id == org
        )).all()
        credits = effective_credits(db, org)
        plans = db.scalars(select(PayoutPlan).where(
            PayoutPlan.organization_id == org
        )).all()
        if not (
            settings is not None and settings.automation_enabled is False
            and len(records) == 2 and len(reversals) == 1
            and sum(row.amount_paise for row in records) == 50000
            and len(credits) == 1
            and sum(row.amount_paise for row in credits) == 25000
            and len(plans) == 1 and plans[0].amount_paise == 100000
        ):
            raise AssertionError("Synthetic net ledger or safe messaging mismatch")


def postgres_client(operation, url, database, directory):
    """Use matching PostgreSQL 16 client image without exposing credentials."""
    if operation not in {"pg_dump", "pg_restore"}:
        raise ValueError("Unsupported recovery operation")
    env = os.environ.copy()
    env["PGPASSWORD"] = str(url.password)
    command = [
        "docker", "run", "--rm", "--network", "host",
        "--user", str(os.getuid()) + ":" + str(os.getgid()),
        "-e", "PGPASSWORD", "-v", str(directory) + ":/backup:rw",
        "postgres:16-alpine", operation, "-h", "127.0.0.1", "-p", "5432",
        "-U", "sas_ci", "-d", database,
    ]
    if operation == "pg_dump":
        command += [
            "--format=custom", "--no-owner", "--no-acl",
            "--file=/backup/synthetic.dump",
        ]
    else:
        command += [
            "--exit-on-error", "--single-transaction", "--no-owner",
            "--no-acl", "/backup/synthetic.dump",
        ]
    try:
        subprocess.run(command, env=env, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        # Never include stderr (potential secrets/data) in CI logs.
        raise RuntimeError("Synthetic database client operation failed") from exc


def run():
    url = validate_ci_scope(
        os.getenv("DATABASE_URL", ""),
        os.getenv("APP_ENV", ""),
        os.getenv("SAS_SYNTHETIC_RESTORE_CI", ""),
    )
    target = PREFIX + uuid.uuid4().hex[:12]
    started = time.monotonic()
    source = create_engine(url, pool_pre_ping=True)
    restored = None
    created = False
    admin = psycopg.connect(
        host="127.0.0.1", port=5432, user=url.username, password=url.password,
        dbname="postgres", autocommit=True,
    )
    try:
        org = synthetic_seed(source)
        verify_finance(source, org)
        before = snapshot(source)
        with tempfile.TemporaryDirectory(prefix="sas-ci-backup-") as tmp:
            directory = Path(tmp)
            postgres_client("pg_dump", url, "sas_ci", directory)
            backup = directory / "synthetic.dump"
            if not backup.is_file() or backup.stat().st_size < 100:
                raise AssertionError("Synthetic backup missing")
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target))
                )
            created = True
            postgres_client("pg_restore", url, target, directory)
            restored = create_engine(url.set(database=target), pool_pre_ping=True)
            after = snapshot(restored)
            if before != after:
                changed = sorted(
                    k for k in set(before) | set(after) if before.get(k) != after.get(k)
                )
                raise AssertionError(
                    "Synthetic restore mismatch in tables: " + ", ".join(changed)
                )
            verify_finance(restored, org)
        return {
            "synthetic_only": True,
            "tables_reconciled": len(after),
            "row_level_digest_match": True,
            "reversed_ledger_verified": True,
            "automated_messaging": False,
            "real_payment_or_payout": False,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "production_restore_or_rpo_rto_proven": False,
        }
    finally:
        source.dispose()
        if restored is not None:
            restored.dispose()
        try:
            if created and target.startswith(PREFIX):
                with admin.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                            sql.Identifier(target)
                        )
                    )
        finally:
            admin.close()


if __name__ == "__main__":
    try:
        print(json.dumps(run(), sort_keys=True))
    except Exception as exc:
        print("Synthetic PostgreSQL recovery FAILED: " + type(exc).__name__)
        raise SystemExit(1) from None
