"""Payout acceptance: recurring obligations, one-time payouts, and evidence integrity."""
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.accounting import ist_today, month_start, shift_month
from app.bootstrap_admin import provision_admin
from app.main import app
from app.models import (
    AdminUser,
    AuditEvent,
    Base,
    Organization,
    OrganizationSettings,
    PayoutPayment,
    PayoutPlan,
    PayoutPlanTerm,
)
from app.security import hash_password


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
    with TestClient(app) as client:
        yield client, engine
    engine.dispose()


def login(client, email="admin@foundation.org",
          password="synthetic-long-admin-password"):
    response = client.post("/v1/auth/login", json={
        "email": email, "password": password,
    })
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": client.get("/v1/auth/session").json()["csrf_token"]}


def plan_input(kind="recurring", **overrides):
    today = ist_today()
    data = {
        "request_id": str(uuid.uuid4()),
        "payee_name": "Synthetic Caretaker",
        "purpose": "Facilities support",
        "notes": "Synthetic controlled test data",
        "cadence": kind,
        "amount_paise": 72500,
        "start_month": month_start(today).isoformat(),
        "scheduled_on": today.isoformat() if kind == "one_time" else None,
    }
    data.update(overrides)
    return data


def create(client, csrf, kind="recurring", **overrides):
    response = client.post(
        "/v1/payouts/plans", headers=csrf, json=plan_input(kind, **overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def pay_input(**overrides):
    today = ist_today()
    data = {
        "request_id": str(uuid.uuid4()),
        "period_month": month_start(today).isoformat(),
        "paid_on": today.isoformat(),
        "payment_method": "bank_transfer",
        "payment_reference": "SYNTHETICPAYOUT0001",
        "funds_disbursed": True,
    }
    data.update(overrides)
    return data


def test_admin_only_new_plan_does_not_count_as_paid(system):
    client, engine = system
    assert client.get("/v1/payouts/plans").status_code == 401
    assert client.post("/v1/payouts/plans", json={}).status_code == 401
    csrf = login(client)
    attempted = plan_input()
    assert client.post("/v1/payouts/plans", json=attempted).status_code == 403
    result = client.post("/v1/payouts/plans", headers=csrf, json=attempted)
    assert result.status_code == 201, result.text
    data = result.json()
    assert data["status"] == "active"
    assert data["amount_paise"] == 72500
    assert data["current_month_due_paise"] == 72500
    assert data["current_month_paid_paise"] == 0
    assert data["payment_count"] == 0
    active = client.get("/v1/payouts/plans?view=active").json()
    assert active["total"] == 1
    assert active["items"][0]["id"] == data["id"]
    assert client.get("/v1/payouts/payments").json()["total"] == 0
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(PayoutPlan)) == 1
        assert db.scalar(select(func.count()).select_from(PayoutPlanTerm)) == 1
        assert db.scalar(select(func.count()).select_from(PayoutPayment)) == 0
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "payout.plan_created"
        )) == 1


def test_one_time_stays_visible_in_all_and_due_after_paid(system):
    client, engine = system
    csrf = login(client)
    one = create(client, csrf, "one_time")
    assert one["cadence"] == "one_time"
    assert one["status"] == "scheduled"
    assert client.get("/v1/payouts/plans?view=active").json()["total"] == 0
    before = client.get("/v1/payouts/plans?view=all").json()["items"][0]
    assert before["current_month_due_paise"] == 72500
    paid = client.post(
        "/v1/payouts/plans/" + one["id"] + "/payments",
        headers=csrf, json=pay_input(),
    )
    assert paid.status_code == 201, paid.text
    assert paid.json()["amount_paise"] == 72500
    assert paid.json()["reference_mask"] == "****0001"
    after = client.get("/v1/payouts/plans").json()["items"][0]
    assert after["status"] == "paid"
    assert after["current_month_due_paise"] == 72500
    assert after["current_month_paid_paise"] == 72500
    assert after["payment_count"] == 1
    assert client.get("/v1/payouts/payments").json()["total"] == 1
    assert "SYNTHETICPAYOUT0001" not in client.get("/v1/payouts/payments").text
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "payout.disbursement_attested"
        )) == 1
        assert db.scalar(select(AuditEvent.entity_id).where(
            AuditEvent.action == "payout.disbursement_attested"
        )) == paid.json()["id"]


def test_request_idempotency_and_financial_duplicate_protection(system):
    client, engine = system
    csrf = login(client)
    body = plan_input()
    first = client.post("/v1/payouts/plans", headers=csrf, json=body)
    assert first.status_code == 201
    assert client.post("/v1/payouts/plans", headers=csrf, json=body).status_code == 200
    assert client.post("/v1/payouts/plans", headers=csrf, json={
        **body, "amount_paise": 70000,
    }).status_code == 409
    payout = first.json()
    path = "/v1/payouts/plans/" + payout["id"] + "/payments"
    payment = pay_input()
    assert client.post(path, headers=csrf, json=payment).status_code == 201
    assert client.post(path, headers=csrf, json=payment).status_code == 200
    assert client.post(path, headers=csrf, json={
        **payment, "paid_on": (ist_today() + timedelta(days=1)).isoformat(),
    }).status_code == 409
    assert client.post(path, headers=csrf, json={
        **payment, "request_id": str(uuid.uuid4()),
    }).status_code == 409
    assert client.post(path, headers=csrf, json={
        **payment, "request_id": str(uuid.uuid4()),
        "payment_method": "cash",
    }).status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(PayoutPlan)) == 1
        assert db.scalar(select(func.count()).select_from(PayoutPayment)) == 1


def test_pay_requires_funds_attestation_not_just_a_plan(system):
    client, engine = system
    csrf = login(client)
    one = create(client, csrf)
    path = "/v1/payouts/plans/" + one["id"] + "/payments"
    assert client.post(path, json=pay_input()).status_code == 403
    for changes in [
        {"funds_disbursed": False},
        {"payment_reference": "x"},
        {"payment_reference": "INVALID REFERENCE"},
        {"paid_on": (ist_today() + timedelta(days=1)).isoformat()},
        {"period_month": (month_start(ist_today()) + timedelta(days=1)).isoformat()},
        {"period_month": shift_month(month_start(ist_today()), 1).isoformat()},
        {"funds_disbursed": True, "unapproved_field": "danger"},
    ]:
        response = client.post(path, headers=csrf, json=pay_input(**changes))
        assert response.status_code == 422, (changes, response.text)
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(PayoutPayment)) == 0


def test_recurring_pause_then_resume_only_from_next_month(system, monkeypatch):
    client, engine = system
    csrf = login(client)
    today = ist_today()
    current = month_start(today)
    nxt = shift_month(current, 1)
    later = shift_month(current, 2)
    payout = create(client, csrf)
    path = "/v1/payouts/plans/" + payout["id"] + "/status"
    body = {"request_id": str(uuid.uuid4()), "new_status": "paused"}
    first = client.post(path, headers=csrf, json=body)
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "active"
    assert first.json()["next_status"] == "paused"
    assert client.post(path, headers=csrf, json=body).status_code == 200
    assert client.post(path, headers=csrf, json={
        "request_id": str(uuid.uuid4()), "new_status": "closed",
    }).status_code == 409

    monkeypatch.setattr("app.payouts.ist_today", lambda: nxt)
    listed = client.get("/v1/payouts/plans?view=all").json()["items"][0]
    assert listed["status"] == "paused"
    assert listed["current_month_due_paise"] == 0
    assert client.get("/v1/payouts/plans?view=active").json()["total"] == 0
    resume = client.post(path, headers=csrf, json={
        "request_id": str(uuid.uuid4()), "new_status": "active",
    })
    assert resume.status_code == 201, resume.text
    assert resume.json()["next_status"] == "active"
    monkeypatch.setattr("app.payouts.ist_today", lambda: later)
    assert client.get("/v1/payouts/plans?view=active").json()["total"] == 1
    with Session(engine) as db:
        terms = db.scalars(select(PayoutPlanTerm).order_by(
            PayoutPlanTerm.effective_month
        )).all()
        assert [(r.effective_month, r.status) for r in terms] == [
            (current, "active"), (nxt, "paused"), (later, "active"),
        ]


def test_one_time_has_no_recurring_status_and_plan_dates_must_match(system):
    client, engine = system
    csrf = login(client)
    today = ist_today()
    for updates in [
        {"cadence": "one_time", "scheduled_on": None},
        {"cadence": "recurring", "scheduled_on": today.isoformat()},
        {"cadence": "one_time", "scheduled_on": shift_month(
            month_start(today), 1
        ).isoformat()},
    ]:
        body = plan_input("one_time", **updates)
        assert client.post("/v1/payouts/plans", headers=csrf, json=body).status_code == 422
    payout = create(client, csrf, "one_time")
    response = client.post(
        "/v1/payouts/plans/" + payout["id"] + "/status", headers=csrf,
        json={"request_id": str(uuid.uuid4()), "new_status": "paused"},
    )
    assert response.status_code == 409
    assert client.post(
        "/v1/payouts/plans/" + str(uuid.uuid4()) + "/payments",
        headers=csrf, json=pay_input(),
    ).status_code == 404
    assert client.get("/v1/payouts/plans?month=notdate").status_code == 422
    assert client.get("/v1/payouts/plans?limit=1000").status_code == 422
    assert client.get("/v1/payouts/payments?limit=1000").status_code == 422


def test_cross_tenant_payouts_not_visible_or_mutable(system):
    client, engine = system
    csrf = login(client)
    payout = create(client, csrf)
    with Session(engine) as db:
        org = Organization(name="Other Foundation")
        db.add(org)
        db.flush()
        db.add(OrganizationSettings(
            organization_id=org.id, currency_code="INR",
            timezone="Asia/Kolkata", default_contribution_paise=50000,
            sponsor_reminder_day=5, promoter_reminder_day=20,
            inactivity_months=2, automation_enabled=False,
        ))
        db.add(AdminUser(
            organization_id=org.id, email="secondary@foundation.org",
            password_hash=hash_password("synthetic-secondary-password"),
            is_active=True,
        ))
        db.commit()
    other = login(client, "secondary@foundation.org", "synthetic-secondary-password")
    assert client.get("/v1/payouts/plans").json()["total"] == 0
    path = "/v1/payouts/plans/" + payout["id"]
    assert client.post(path + "/status", headers=other, json={
        "request_id": str(uuid.uuid4()), "new_status": "paused",
    }).status_code == 404
    assert client.post(path + "/payments", headers=other, json=pay_input()).status_code == 404
    assert client.get("/v1/payouts/payments").json()["total"] == 0


def test_one_time_disbursement_cannot_predate_scheduled_day(system):
    """An attestation cannot silently become an unapproved advance payment."""
    client, engine = system
    csrf = login(client)
    today = ist_today()
    if today.day == 1:
        scheduled = today + timedelta(days=1)
        attempted = today
    else:
        scheduled = today
        attempted = month_start(today)
    one = create(client, csrf, "one_time", scheduled_on=scheduled.isoformat())
    path = "/v1/payouts/plans/" + one["id"] + "/payments"
    rejected = client.post(path, headers=csrf, json=pay_input(
        paid_on=attempted.isoformat(),
    ))
    assert rejected.status_code == 422, rejected.text
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(PayoutPayment)) == 0
    if scheduled <= today:
        accepted = client.post(path, headers=csrf, json=pay_input(
            paid_on=scheduled.isoformat(),
        ))
        assert accepted.status_code == 201, accepted.text
