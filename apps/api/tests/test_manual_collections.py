"""Manual collection acceptance: financial attestation, consent and idempotency."""
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.accounting import ist_today, month_start
from app.bootstrap_admin import provision_admin
from app.main import app
from app.models import (
    AuditEvent,
    Base,
    ManualCollection,
    MessageOutbox,
    Prospect,
    VerifiedCredit,
)


@pytest.fixture
def system(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        provision_admin(
            db, email="admin@foundation.org", password="synthetic-long-admin-password",
            organization_name="Emlen Foundation",
        )
    monkeypatch.setattr("app.auth.get_engine", lambda: engine)
    monkeypatch.setattr(
        "app.auth.get_settings",
        lambda: SimpleNamespace(
            auth_secret="synthetic-auth-secret-more-than-thirty-two-characters",
            app_env="test",
        ),
    )
    monkeypatch.setattr(
        "app.prospects.get_settings",
        lambda: SimpleNamespace(
            upi_match_secret="synthetic-independent-upi-hmac-key-for-tests",
        ),
    )
    with TestClient(app) as client:
        yield client, engine
    engine.dispose()


def login(client):
    result = client.post("/v1/auth/login", json={
        "email": "admin@foundation.org", "password": "synthetic-long-admin-password",
    })
    assert result.status_code == 200, result.text
    return {"X-CSRF-Token": client.get("/v1/auth/session").json()["csrf_token"]}


def sponsor(client, headers, consent):
    response = client.post("/v1/prospects", headers=headers, json={
        "full_name": "Synthetic Sponsor",
        "mobile_number": "+919876543210",
        "area_city": "Bengaluru",
        "whatsapp_opt_in": consent,
        "monthly_contribution_paise": 50000,
    })
    assert response.status_code == 201, response.text
    return response.json()


def sample(prospect_id):
    today = ist_today()
    return {
        "request_id": str(uuid.uuid4()),
        "prospect_id": prospect_id,
        "period_month": month_start(today).isoformat(),
        "received_on": today.isoformat(),
        "amount_paise": 50000,
        "payment_method": "upi",
        "receipt_reference": "SYNTHETICREF001",
        "funds_confirmed": True,
    }


def test_requires_auth_csrf_and_explicit_attestation(system):
    client, engine = system
    assert client.get("/v1/collections").status_code == 401
    assert client.post("/v1/collections", json={}).status_code == 401
    headers = login(client)
    p = sponsor(client, headers, consent=True)
    payload = sample(p["id"])
    assert client.post("/v1/collections", json=payload).status_code == 403
    assert client.post("/v1/collections", headers=headers, json={
        **payload, "funds_confirmed": False,
    }).status_code == 422
    assert client.post("/v1/collections", headers=headers, json={
        **payload, "funds_confirmed": True, "extra": "bad",
    }).status_code == 422
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(VerifiedCredit)) == 0


def test_full_month_payment_activates_and_prepares_eligible_message(system):
    client, engine = system
    csrf = login(client)
    p = sponsor(client, csrf, consent=True)
    data = sample(p["id"])
    response = client.post("/v1/collections", headers=csrf, json=data)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["message_status"] == "awaiting_integration"
    assert result["evidence"] == "admin_attested"
    assert result["sponsor_status"] == "active"
    assert result["reference_mask"] == "****F001"
    current = client.get("/v1/accounting/overview").json()
    assert current["verified_paise"] == 50000
    assert current["fully_paid_sponsors"] == 1
    assert client.get("/v1/prospects/" + p["id"]).json()["lifecycle_status"] == "active"
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ManualCollection)) == 1
        assert db.scalar(select(func.count()).select_from(VerifiedCredit)) == 1
        event = db.scalars(select(MessageOutbox)).one()
        assert event.event_type == "collection_recorded"
        assert event.status == "awaiting_integration"
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "collection.manual_recorded"
        )) == 1


def test_retries_idempotent_duplicates_rejected_without_second_credit(system):
    client, engine = system
    csrf = login(client)
    p = sponsor(client, csrf, consent=True)
    original = sample(p["id"])
    assert client.post("/v1/collections", headers=csrf, json=original).status_code == 201
    repeated = client.post("/v1/collections", headers=csrf, json=original)
    assert repeated.status_code == 200
    assert client.post("/v1/collections", headers=csrf, json={
        **original, "amount_paise": 70000,
    }).status_code == 409
    assert client.post("/v1/collections", headers=csrf, json={
        **original, "request_id": str(uuid.uuid4()),
    }).status_code == 409
    assert client.post("/v1/collections", headers=csrf, json={
        **original, "request_id": str(uuid.uuid4()), "payment_method": "bank_transfer",
    }).status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(VerifiedCredit)) == 1
        assert db.scalar(select(func.count()).select_from(MessageOutbox)) == 1


def test_missing_consent_suppresses_message_and_partial_payment_is_not_full(system):
    client, engine = system
    csrf = login(client)
    p = sponsor(client, csrf, consent=False)
    partial = {**sample(p["id"]), "amount_paise": 15000}
    res = client.post("/v1/collections", headers=csrf, json=partial)
    assert res.status_code == 201, res.text
    assert res.json()["message_status"] == "suppressed"
    ledger = client.get("/v1/accounting/overview").json()
    assert ledger["verified_paise"] == 15000
    assert ledger["outstanding_paise"] == 35000
    assert ledger["fully_paid_sponsors"] == 0
    with Session(engine) as db:
        message = db.scalars(select(MessageOutbox)).one()
        assert message.suppress_reason == "consent_missing"


def test_date_reference_future_and_archived_rejections(system):
    client, engine = system
    csrf = login(client)
    p = sponsor(client, csrf, consent=True)
    sample_data = sample(p["id"])
    for changed in [
        {"received_on": (ist_today() + timedelta(days=1)).isoformat()},
        {"receipt_reference": "A"},
        {"receipt_reference": "NOT ALLOWED"},
        {"period_month": (month_start(ist_today()) + timedelta(days=1)).isoformat()},
    ]:
        response = client.post("/v1/collections", headers=csrf, json={
            **sample_data, **changed,
        })
        assert response.status_code == 422, response.text
    assert client.delete(
        "/v1/prospects/" + p["id"], headers={**csrf, "If-Match": "1"},
    ).status_code == 204
    assert client.post("/v1/collections", headers=csrf, json=sample_data).status_code == 404
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ManualCollection)) == 0


def test_payment_lists_and_does_not_expose_unmasked_reference(system):
    client, engine = system
    csrf = login(client)
    p = sponsor(client, csrf, consent=True)
    original = sample(p["id"])
    assert client.post("/v1/collections", headers=csrf, json=original).status_code == 201
    response = client.get("/v1/collections?limit=10")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert "SYNTHETICREF001" not in response.text
    assert client.get("/v1/collections?limit=101").status_code == 422
    assert client.get("/v1/collections?period_month=2026-10-03").status_code == 422
    with Session(engine) as db:
        assert db.get(Prospect, uuid.UUID(p["id"])) is not None
