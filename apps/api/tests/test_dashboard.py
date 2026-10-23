"""Real dashboard acceptance across finance, status, tenant and reminders."""
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.accounting import ist_today, month_start
from app.bootstrap_admin import provision_admin
from app.main import app
from app.models import AdminUser, Base, Organization, OrganizationSettings
from app.security import hash_password


@pytest.fixture
def system(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        provision_admin(
            db, email="admin@foundation.org",
            password="synthetic-long-admin-password",
            organization_name="Emlen Foundation",
            amount_paise=50000,
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


def login(client, email="admin@foundation.org",
          password="synthetic-long-admin-password"):
    result = client.post("/v1/auth/login", json={
        "email": email, "password": password,
    })
    assert result.status_code == 200, result.text
    return {"X-CSRF-Token": client.get("/v1/auth/session").json()["csrf_token"]}


def activate_for_financial_flow(client, csrf, record):
    """Older payment/reminder tests explicitly activate enrolled CRM prospects."""
    response = client.post("/v1/prospects/" + record["id"] + "/stage", headers=csrf, json={
        "version": record["version"], "stage": "active",
        "note": "Synthetic outreach completed for financial flow test",
    })
    assert response.status_code == 200, response.text
    return response.json()


def register(client, csrf, phone="+919876555001", consent=True):
    r = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Synthetic Sponsor", "mobile_number": phone,
        "area_city": "Bengaluru", "whatsapp_opt_in": consent,
        "monthly_contribution_paise": 50000,
    })
    assert r.status_code == 201, r.text
    return activate_for_financial_flow(client, csrf, r.json())


def collection(client, csrf, prospect, reference="DASHBOARDREF0001"):
    today = ist_today()
    r = client.post("/v1/collections", headers=csrf, json={
        "request_id": str(uuid.uuid4()), "prospect_id": prospect["id"],
        "amount_paise": 50000, "period_month": month_start(today).isoformat(),
        "received_on": today.isoformat(), "payment_method": "upi",
        "receipt_reference": reference, "funds_confirmed": True,
    })
    assert r.status_code == 201, r.text
    return r.json()


def payout(client, csrf):
    today = ist_today()
    body = {
        "request_id": str(uuid.uuid4()), "payee_name": "Synthetic Caretaker",
        "purpose": "Facilities maintenance", "notes": None,
        "cadence": "recurring", "amount_paise": 20000,
        "start_month": month_start(today).isoformat(), "scheduled_on": None,
    }
    r = client.post("/v1/payouts/plans", headers=csrf, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_empty_dashboard_never_invents_payments_or_messages(system):
    client, _ = system
    assert client.get("/v1/dashboard/overview").status_code == 401
    login(client)
    r = client.get("/v1/dashboard/overview")
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    data = r.json()
    for key in [
        "sponsors_total", "sponsors_active", "due_paise",
        "recorded_contributions_paise", "outstanding_paise",
        "payout_planned_paise", "payout_disbursed_paise",
        "whatsapp_deliveries_confirmed", "acknowledgments_awaiting_setup",
    ]:
        assert data[key] == 0, key
    assert data["activity"] == []
    assert len(data["months"]) == 6
    assert data["period_month"] == month_start(ist_today()).isoformat()
    assert all(row["due_paise"] == 0 for row in data["months"])
    assert "Admin-attested" in data["notice"]


def test_contribution_updates_dashboard_without_inventing_delivery(system):
    client, _ = system
    csrf = login(client)
    sponsor = register(client, csrf)
    before = client.get("/v1/dashboard/overview").json()
    assert before["sponsors_new"] == 1
    assert before["due_paise"] == 50000
    assert before["recorded_contributions_paise"] == 0
    assert before["unpaid_sponsors"] == 1

    receipt = collection(client, csrf, sponsor)
    after = client.get("/v1/dashboard/overview").json()
    assert after["sponsors_active"] == 1
    assert after["fully_paid_sponsors"] == 1
    assert after["recorded_contributions_paise"] == 50000
    assert after["outstanding_paise"] == 0
    assert after["acknowledgments_awaiting_setup"] == 1
    assert after["whatsapp_deliveries_confirmed"] == 0
    assert after["months"][-1]["contributions_paise"] == 50000
    assert after["activity"][0]["kind"] == "collection"
    assert "DASHBOARDREF0001" not in rstr(after)

    r = client.post(
        "/v1/collections/" + receipt["id"] + "/reverse",
        headers=csrf,
        json={
            "request_id": str(uuid.uuid4()), "reason_code": "wrong_amount",
            "confirmation": "REVERSE",
        },
    )
    assert r.status_code == 201, r.text
    reversed_view = client.get("/v1/dashboard/overview").json()
    assert reversed_view["sponsors_new"] == 1
    assert reversed_view["recorded_contributions_paise"] == 0
    assert reversed_view["outstanding_paise"] == 50000
    assert reversed_view["acknowledgments_awaiting_setup"] == 0
    assert any(item["kind"] == "reversal" for item in reversed_view["activity"])


def rstr(value):
    import json

    return json.dumps(value)


def test_payout_plan_is_not_cash_disbursement(system):
    client, _ = system
    csrf = login(client)
    plan = payout(client, csrf)
    record = client.get("/v1/dashboard/overview").json()
    assert record["recurring_payouts_active"] == 1
    assert record["payout_planned_paise"] == 20000
    assert record["payout_outstanding_paise"] == 20000
    assert record["payout_disbursed_paise"] == 0

    today = ist_today()
    payment = client.post(
        "/v1/payouts/plans/" + plan["id"] + "/payments",
        headers=csrf, json={
            "request_id": str(uuid.uuid4()),
            "period_month": month_start(today).isoformat(),
            "paid_on": today.isoformat(), "payment_method": "bank_transfer",
            "payment_reference": "DASHBOARDPAYOUT0001",
            "funds_disbursed": True,
        },
    )
    assert payment.status_code == 201, payment.text
    now = client.get("/v1/dashboard/overview").json()
    assert now["payout_disbursed_paise"] == 20000
    assert now["payout_planned_paise"] == 20000
    assert now["payout_outstanding_paise"] == 0
    assert any(row["kind"] == "payout_paid" for row in now["activity"])


def test_dashboard_tenant_isolation_even_with_foreign_records(system):
    client, engine = system
    csrf = login(client)
    register(client, csrf)
    payout(client, csrf)
    with Session(engine) as db:
        other = Organization(name="Other tenant")
        db.add(other)
        db.flush()
        db.add(AdminUser(
            organization_id=other.id, email="other@foundation.org",
            password_hash=hash_password("synthetic-other-admin-password"),
            is_active=True,
        ))
        db.add(OrganizationSettings(
            organization_id=other.id, currency_code="INR",
            timezone="Asia/Kolkata", default_contribution_paise=50000,
            sponsor_reminder_day=5, promoter_reminder_day=20,
            inactivity_months=2, automation_enabled=False,
        ))
        db.commit()
    login(client, "other@foundation.org", "synthetic-other-admin-password")
    result = client.get("/v1/dashboard/overview")
    assert result.status_code == 200, result.text
    state = result.json()
    assert state["sponsors_total"] == 0
    assert state["payout_planned_paise"] == 0
    assert state["activity"] == []


def test_250_receipt_below_legacy_commitment_keeps_balance_and_delivery_unconfirmed(system):
    """An exact ₹250 receipt cannot be rounded to the ₹500 commitment."""
    client, _ = system
    csrf = login(client)
    sponsor = register(client, csrf, phone="+919876555062")
    today = ist_today()
    receipt = client.post("/v1/collections", headers=csrf, json={
        "request_id": str(uuid.uuid4()), "prospect_id": sponsor["id"],
        "amount_paise": 25000, "period_month": month_start(today).isoformat(),
        "received_on": today.isoformat(), "payment_method": "upi",
        "receipt_reference": "DASHBOARDTIER250001", "funds_confirmed": True,
    })
    assert receipt.status_code == 201, receipt.text
    result = client.get("/v1/dashboard/overview")
    assert result.status_code == 200, result.text
    state = result.json()
    assert state["due_paise"] == 50000
    assert state["recorded_contributions_paise"] == 25000
    assert state["outstanding_paise"] == 25000
    assert state["fully_paid_sponsors"] == 0
    assert state["unpaid_sponsors"] == 1
    assert state["acknowledgments_awaiting_setup"] == 1
    assert state["whatsapp_deliveries_confirmed"] == 0
    assert state["months"][-1]["contributions_paise"] == 25000
