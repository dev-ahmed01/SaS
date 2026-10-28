"""Safe MySQL 8.4 trial schema tests: synthetic only; no live Saasyto calls."""

import os
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, CreateTable

from app.bootstrap_admin import provision_admin
from app.main import app
from app.models import (
    Base,
    ManualCollection,
    Organization,
    Promoter,
    PromoterAssignment,
    Prospect,
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
