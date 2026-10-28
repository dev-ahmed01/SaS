"""Safe MySQL 8.4 trial schema tests: synthetic only; no live Saasyto calls."""

import os
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, CreateTable

from app.accounting import ist_today, month_start
from app.bootstrap_admin import provision_admin
from app.main import app
from app.models import (
    AdminUser,
    AuditEvent,
    Base,
    ManualCollection,
    ManualCollectionReversal,
    MessageOutbox,
    Organization,
    PayoutPayment,
    Promoter,
    PromoterAssignment,
    Prospect,
    SponsorshipRate,
    VerifiedCredit,
)
from app.mysql_trial_schema import assert_disposable_target, create_trial_schema, trial_metadata


def test_mysql_metadata_compiles_without_changing_postgresql_models():
    original = Base.metadata.tables["promoter_assignments"]
    candidate = trial_metadata()
    assignments = candidate.tables["promoter_assignments"]
    assert "mysql_current_prospect_id" not in original.c
    assert "mysql_current_prospect_id" in assignments.c

    original_indexes = {index.name for index in original.indexes}
    candidate_indexes = {index.name for index in assignments.indexes}
    assert "uq_assignment_current_prospect" in original_indexes
    assert "uq_assignment_current_prospect" not in candidate_indexes
    assert "uq_mysql_assignment_current_prospect" in candidate_indexes

    index = next(i for i in assignments.indexes if i.name == "uq_mysql_assignment_current_prospect")
    assert index.unique
    table_ddl = str(CreateTable(assignments).compile(dialect=mysql.dialect()))
    index_ddl = str(CreateIndex(index).compile(dialect=mysql.dialect()))
    assert "GENERATED ALWAYS AS" in table_ddl
    assert "ended_at IS NULL" in table_ddl
    assert "CREATE UNIQUE INDEX" in index_ddl
    assert "mysql_current_prospect_id" in index_ddl
    assert "ENGINE=InnoDB" in table_ddl
    assert "utf8mb4" in table_ddl
    assert len(candidate.tables) == len(Base.metadata.tables)


def test_disposable_target_gate_rejects_pg_and_off_mode(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SAS_MYSQL_TRIAL_ONLY", "1")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with pytest.raises(RuntimeError, match="test-only gate"):
            assert_disposable_target(engine)
        monkeypatch.setenv("APP_ENV", "test")
        with pytest.raises(RuntimeError, match="requires MySQL"):
            assert_disposable_target(engine)
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def mysql_trial_engine():
    url = os.getenv("SAS_MYSQL_TRIAL_URL")
    if not url:
        pytest.skip("MySQL 8.4 CI service not configured")
    engine = create_engine(url, pool_pre_ping=True)
    try:
        create_trial_schema(engine)
        yield engine
    finally:
        engine.dispose()


def test_mysql_disposable_schema_exists(mysql_trial_engine):
    tables = set(inspect(mysql_trial_engine).get_table_names())
    assert set(Base.metadata.tables) == tables
    with mysql_trial_engine.connect() as connection:
        check = connection.scalar(text("""
            SELECT COUNT(*) FROM information_schema.triggers
            WHERE trigger_schema = DATABASE()
              AND trigger_name IN ('sas_manual_collection_tier_insert',
                                   'sas_manual_collection_tier_update')
        """))
    assert check == 2


def test_mysql_schema_enforces_current_assignment_and_historic_reassignment(mysql_trial_engine):
    with Session(mysql_trial_engine) as db:
        org = Organization(name="Synthetic MySQL migration trial")
        db.add(org)
        db.flush()
        sponsor = Prospect(
            organization_id=org.id,
            full_name="Synthetic sponsor",
            mobile_number="+919876501231",
            area_city="Synthetic City",
            monthly_contribution_paise=25000,
        )
        first = Promoter(
            organization_id=org.id,
            full_name="Synthetic promoter first",
            mobile_number="+919876501232",
            area_city="Synthetic City",
        )
        second = Promoter(
            organization_id=org.id,
            full_name="Synthetic promoter second",
            mobile_number="+919876501233",
            area_city="Synthetic City",
        )
        db.add_all([sponsor, first, second])
        db.flush()
        ids = (org.id, sponsor.id, first.id, second.id)
        db.add(PromoterAssignment(
            organization_id=org.id, prospect_id=sponsor.id, promoter_id=first.id
        ))
        db.commit()

    org_id, prospect_id, first_id, second_id = ids
    with Session(mysql_trial_engine) as db:
        db.add(PromoterAssignment(
            organization_id=org_id, prospect_id=prospect_id, promoter_id=second_id
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    with Session(mysql_trial_engine) as db:
        current = db.scalars(select(PromoterAssignment)).one()
        current.ended_at = datetime(2026, 10, 29, 0, tzinfo=UTC)
        db.commit()

    with Session(mysql_trial_engine) as db:
        db.add(PromoterAssignment(
            organization_id=org_id, prospect_id=prospect_id, promoter_id=second_id
        ))
        db.commit()
        rows = db.scalars(select(PromoterAssignment)).all()
        assert len(rows) == 2
        assert sum(row.ended_at is None for row in rows) == 1
        assert {row.promoter_id for row in rows} == {first_id, second_id}


def test_mysql_new_receipts_follow_250_rule(mysql_trial_engine):
    with Session(mysql_trial_engine) as db:
        sponsor = db.scalars(select(Prospect)).one()
        credit = VerifiedCredit(
            organization_id=sponsor.organization_id,
            prospect_id=sponsor.id,
            period_month=date(2026, 10, 1),
            amount_paise=25000,
            source_type="manual_attested",
            source_key="trial-valid-credit-1",
            verified_at=datetime(2026, 10, 29, tzinfo=UTC),
        )
        db.add(credit)
        db.flush()
        values = dict(
            organization_id=sponsor.organization_id,
            prospect_id=sponsor.id,
            verified_credit_id=credit.id,
            request_id=uuid.uuid4(),
            request_payload_hash="a" * 64,
            reference_digest="b" * 64,
            reference_mask="****1234",
            received_on=date(2026, 10, 29),
            period_month=date(2026, 10, 1),
            payment_method="upi",
            amount_paise=25000,
        )
        valid = ManualCollection(**values)
        db.add(valid)
        db.commit()
        receipt_id = valid.id

    with Session(mysql_trial_engine) as db:
        # SIGNAL SQLSTATE 45000 is surfaced by PyMySQL as OperationalError,
        # while duplicate-key conflicts are IntegrityError. Both inherit
        # DBAPIError, and either must abort the attempted write.
        with pytest.raises(DBAPIError):
            db.execute(
                text("UPDATE manual_collections SET amount_paise = :bad WHERE id = :id"),
                {"bad": 37500, "id": receipt_id.hex},
            )
            db.commit()
        db.rollback()
        assert db.get(ManualCollection, receipt_id).amount_paise == 25000


def test_mysql_fastapi_login_prospect_and_promoter_smoke(mysql_trial_engine, monkeypatch):
    """Real HTTP routes must be able to use the trial MySQL schema.

    Uses synthetic contacts, no communications transports, and no live host.
    """
    with Session(mysql_trial_engine) as db:
        provision_admin(
            db,
            email="trial-admin@example.com",
            password="synthetic-mysql-admin-long-password",
            organization_name="Isolated MySQL API trial",
        )
    monkeypatch.setattr("app.auth.get_engine", lambda: mysql_trial_engine)
    monkeypatch.setattr(
        "app.auth.get_settings",
        lambda: SimpleNamespace(
            auth_secret="mysql-trial-auth-secret-only-not-production-12345",
            app_env="test",
        ),
    )
    monkeypatch.setattr(
        "app.prospects.get_settings",
        lambda: SimpleNamespace(upi_match_secret="mysql-trial-upi-hmac-only-not-prod-12345"),
    )
    with TestClient(app) as client:
        login = client.post("/v1/auth/login", json={
            "email": "trial-admin@example.com",
            "password": "synthetic-mysql-admin-long-password",
        })
        assert login.status_code == 200, login.text
        csrf = {"X-CSRF-Token": client.get("/v1/auth/session").json()["csrf_token"]}
        sponsor = client.post("/v1/prospects", headers=csrf, json={
            "full_name": "Synthetic MySQL CRM sponsor",
            "mobile_number": "+919876509901",
            "area_city": "Test-only City",
            "monthly_contribution_paise": 25000,
            "whatsapp_opt_in": False,
        })
        assert sponsor.status_code == 201, sponsor.text
        sponsor_id = sponsor.json()["id"]
        assert client.get("/v1/prospects/" + sponsor_id).status_code == 200
        promoter = client.post("/v1/promoters", headers=csrf, json={
            "full_name": "Synthetic MySQL CRM promoter",
            "mobile_number": "+919876509902",
            "area_city": "Test-only City",
            "whatsapp_opt_in": False,
        })
        assert promoter.status_code == 201, promoter.text
        assert client.get("/v1/promoters/" + promoter.json()["id"]).status_code == 200


def test_mysql_financial_http_idempotency_reversal_and_payout(mysql_trial_engine, monkeypatch):
    """Exercise the real ledger API and DB constraints using fake data only.

    No external WhatsApp request is ever enabled: sponsor opt-in is false and
    every collection notification must be suppressed in the outbox.
    """
    now_day = ist_today()
    billing_month = month_start(now_day)
    with Session(mysql_trial_engine) as db:
        admin = db.scalars(
            select(AdminUser).where(AdminUser.email == "trial-admin@example.com")
        ).one()
        sponsor = Prospect(
            organization_id=admin.organization_id,
            full_name="Synthetic audited finance sponsor",
            mobile_number="+919876509923",
            area_city="Trial Only",
            monthly_contribution_paise=25000,
            crm_stage="active",
            lifecycle_status="active",
            start_month=billing_month,
            whatsapp_opt_in=False,
        )
        db.add(sponsor)
        db.flush()
        sponsor_id = sponsor.id
        db.add(SponsorshipRate(
            organization_id=admin.organization_id,
            prospect_id=sponsor.id,
            effective_month=billing_month,
            amount_paise=25000,
        ))
        db.commit()

    monkeypatch.setattr("app.auth.get_engine", lambda: mysql_trial_engine)
    monkeypatch.setattr(
        "app.auth.get_settings",
        lambda: SimpleNamespace(
            auth_secret="mysql-trial-auth-secret-only-not-production-12345",
            app_env="test",
        ),
    )
    with TestClient(app) as client:
        login = client.post("/v1/auth/login", json={
            "email": "trial-admin@example.com",
            "password": "synthetic-mysql-admin-long-password",
        })
        assert login.status_code == 200, login.text
        csrf = {"X-CSRF-Token": client.get("/v1/auth/session").json()["csrf_token"]}
        receipt_payload = {
            "request_id": str(uuid.uuid4()),
            "prospect_id": str(sponsor_id),
            "period_month": billing_month.isoformat(),
            "received_on": now_day.isoformat(),
            "amount_paise": 25000,
            "payment_method": "upi",
            "receipt_reference": "MYSQL-TRIAL-REF-90001",
            "funds_confirmed": True,
        }
        first = client.post("/v1/collections", headers=csrf, json=receipt_payload)
        assert first.status_code == 201, first.text
        collection_id = first.json()["id"]
        assert first.json()["amount_paise"] == 25000
        assert first.json()["message_status"] == "suppressed"

        replay = client.post("/v1/collections", headers=csrf, json=receipt_payload)
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == collection_id

        duplicate_ref = client.post("/v1/collections", headers=csrf, json={
            **receipt_payload,
            "request_id": str(uuid.uuid4()),
        })
        assert duplicate_ref.status_code == 409, duplicate_ref.text

        wrong_amount = client.post("/v1/collections", headers=csrf, json={
            **receipt_payload,
            "request_id": str(uuid.uuid4()),
            "receipt_reference": "MYSQL-TRIAL-REF-90002",
            "amount_paise": 37500,
        })
        assert wrong_amount.status_code == 422, wrong_amount.text

        reverse_payload = {
            "request_id": str(uuid.uuid4()),
            "reason_code": "wrong_amount",
            "confirmation": "REVERSE",
        }
        rev_url = "/v1/collections/" + collection_id + "/reverse"
        reversed_once = client.post(rev_url, headers=csrf, json=reverse_payload)
        assert reversed_once.status_code == 201, reversed_once.text
        assert reversed_once.json()["reversed"] is True
        reversed_retry = client.post(rev_url, headers=csrf, json=reverse_payload)
        assert reversed_retry.status_code == 200, reversed_retry.text
        assert reversed_retry.json()["id"] == reversed_once.json()["id"]
        assert client.post(rev_url, headers=csrf, json={
            **reverse_payload, "request_id": str(uuid.uuid4()),
        }).status_code == 409

        payout_payload = {
            "request_id": str(uuid.uuid4()),
            "first_name": "Synthetic",
            "last_name": "Payee",
            "purpose": "Trial audit payment",
            "amount_paise": 25000,
            "paid_on": now_day.isoformat(),
            "payment_method": "bank_transfer",
            "payment_reference": "MYSQL-TRIAL-PAYOUT-001",
            "funds_disbursed": True,
        }
        outgoing = client.post("/v1/payouts/quick", headers=csrf, json=payout_payload)
        assert outgoing.status_code == 201, outgoing.text
        outgoing_retry = client.post("/v1/payouts/quick", headers=csrf, json=payout_payload)
        assert outgoing_retry.status_code == 200, outgoing_retry.text
        assert outgoing_retry.json()["id"] == outgoing.json()["id"]
        assert client.post("/v1/payouts/quick", headers=csrf, json={
            **payout_payload, "request_id": str(uuid.uuid4()),
        }).status_code == 409

    with Session(mysql_trial_engine) as db:
        assert db.scalar(select(func.count()).select_from(ManualCollection).where(
            ManualCollection.prospect_id == sponsor_id,
        )) == 1
        assert db.scalar(select(func.count()).select_from(ManualCollectionReversal).where(
            ManualCollectionReversal.collection_id == uuid.UUID(collection_id),
        )) == 1
        assert db.scalar(select(func.count()).select_from(PayoutPayment).where(
            PayoutPayment.request_id == uuid.UUID(payout_payload["request_id"]),
        )) == 1
        outbox = db.scalars(select(MessageOutbox).where(
            MessageOutbox.collection_id == uuid.UUID(collection_id),
        )).one()
        assert outbox.status == "suppressed"
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "collection.manual_recorded",
            AuditEvent.entity_id == collection_id,
        )) == 1
