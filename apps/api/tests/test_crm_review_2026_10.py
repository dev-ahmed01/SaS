"""October CRM review: tenant-safe status gates, follow-ups, transfers and payouts."""
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.accounting import ist_today, month_start
from app.bootstrap_admin import provision_admin
from app.main import app
from app.models import Base, ManualCollection, PayoutPayment, PromoterAssignment


@pytest.fixture
def api(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        provision_admin(db, email="admin@foundation.org",
                        password="synthetic-long-admin-password",
                        organization_name="Emlen Foundation", amount_paise=25000)
    monkeypatch.setattr("app.auth.get_engine", lambda: engine)
    monkeypatch.setattr("app.auth.get_settings", lambda: SimpleNamespace(
        auth_secret="synthetic-auth-secret-longer-than-thirty-two-characters",
        app_env="test"))
    monkeypatch.setattr("app.prospects.get_settings", lambda: SimpleNamespace(
        upi_match_secret="synthetic-upi-key-longer-than-32-characters"))
    with TestClient(app) as client:
        auth = client.post("/v1/auth/login", json={
            "email": "admin@foundation.org",
            "password": "synthetic-long-admin-password",
        })
        assert auth.status_code == 200, auth.text
        csrf = {"X-CSRF-Token": client.get("/v1/auth/session").json()["csrf_token"]}
        yield client, csrf, engine
    engine.dispose()


def create_sponsor(client, csrf):
    created = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Synthetic New Sponsor",
        "mobile_number": "+919812345678", "area_city": "Bengaluru",
    })
    assert created.status_code == 201, created.text
    return created.json()


def test_inactive_default_followup_and_active_only_collections(api):
    client, csrf, engine = api
    sponsor = create_sponsor(client, csrf)
    assert sponsor["crm_stage"] == "inactive"
    assert sponsor["pipeline_stage_name"] == "New Inquiry"
    assert client.get("/v1/prospects?crm_stage=active").json()["total"] == 0
    today = ist_today()
    body = {
        "request_id": str(uuid.uuid4()), "prospect_id": sponsor["id"],
        "period_month": month_start(today).isoformat(),
        "received_on": today.isoformat(), "amount_paise": 25000,
        "payment_method": "upi", "receipt_reference": "CRMOCTRECEIPT123",
        "funds_confirmed": True,
    }
    blocked = client.post("/v1/collections", headers=csrf, json=body)
    assert blocked.status_code == 422, blocked.text
    with Session(engine) as db:
        assert db.scalar(select(func.count(ManualCollection.id))) == 0
    activity = client.post("/v1/prospects/" + sponsor["id"] + "/followups",
                           headers=csrf, json={
        "version": sponsor["version"], "occurred_on": today.isoformat(),
        "outcome": "interested", "notes": "Discussed sponsorship by telephone",
    })
    assert activity.status_code == 201, activity.text
    events = client.get("/v1/prospects/" + sponsor["id"] + "/followups")
    assert events.status_code == 200 and len(events.json()) == 1
    updated = client.get("/v1/prospects/" + sponsor["id"]).json()
    no_reason = client.post("/v1/prospects/" + sponsor["id"] + "/stage",
                            headers=csrf, json={
        "version": updated["version"], "stage": "active",
    })
    assert no_reason.status_code == 422
    activated = client.post("/v1/prospects/" + sponsor["id"] + "/stage",
                            headers=csrf, json={
        "version": updated["version"], "stage": "active",
        "note": "Promoter confirmed their wish to begin",
    })
    assert activated.status_code == 200, activated.text
    accepted = client.post("/v1/collections", headers=csrf, json=body)
    assert accepted.status_code == 201, accepted.text


def test_promoter_deactivation_reassigns_all_current_links(api):
    client, csrf, engine = api
    sponsor = create_sponsor(client, csrf)
    persons = []
    for name, phone in (("Promoter One", "+919812345601"),
                        ("Promoter Two", "+919812345602")):
        response = client.post("/v1/promoters", headers=csrf, json={
            "full_name": name, "mobile_number": phone, "area_city": "Bengaluru",
        })
        assert response.status_code == 201, response.text
        persons.append(response.json())
    first, second = persons
    assigned = client.put("/v1/promoters/" + first["id"] + "/sponsors/" + sponsor["id"],
                          headers={**csrf, "If-Match": str(sponsor["version"])})
    assert assigned.status_code == 200, assigned.text
    current = client.get("/v1/promoters/" + first["id"]).json()
    denied = client.patch("/v1/promoters/" + first["id"], headers=csrf, json={
        "version": current["version"], "is_active": False,
    })
    assert denied.status_code == 422
    transferred = client.patch("/v1/promoters/" + first["id"], headers=csrf, json={
        "version": current["version"], "is_active": False,
        "reassign_to_promoter_id": second["id"],
    })
    assert transferred.status_code == 200, transferred.text
    assert transferred.json()["is_active"] is False
    assert client.get("/v1/promoters/" + first["id"] + "/sponsors").json()["total"] == 0
    assert client.get("/v1/promoters/" + second["id"] + "/sponsors").json()["total"] == 1
    with Session(engine) as db:
        assert db.scalar(select(func.count(PromoterAssignment.id))) == 2


def test_one_step_payout_attestation_is_idempotent(api):
    client, csrf, engine = api
    payload = {
        "request_id": str(uuid.uuid4()), "first_name": "Support",
        "last_name": "Vendor", "purpose": "Facility upkeep",
        "amount_paise": 25000, "paid_on": ist_today().isoformat(),
        "payment_method": "upi", "payment_reference": "UTRCRMREVIEW1234",
        "funds_disbursed": True,
    }
    first = client.post("/v1/payouts/quick", headers=csrf, json=payload)
    assert first.status_code == 201, first.text
    assert first.json()["payee_name"] == "Support Vendor"
    again = client.post("/v1/payouts/quick", headers=csrf, json=payload)
    assert again.status_code == 200, again.text
    assert first.json()["id"] == again.json()["id"]
    duplicate = client.post("/v1/payouts/quick", headers=csrf, json={
        **payload, "request_id": str(uuid.uuid4()),
    })
    assert duplicate.status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count(PayoutPayment.id))) == 1
