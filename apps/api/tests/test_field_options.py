"""Approved payout purpose options: owner controls, history and tenant isolation."""
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.bootstrap_admin import provision_admin
from app.main import app
from app.models import (
    AdminUser, AuditEvent, Base, Organization, OrganizationFieldOption,
    OrganizationSettings, PayoutPlan,
)
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
        )
    monkeypatch.setattr("app.auth.get_engine", lambda: engine)
    monkeypatch.setattr(
        "app.auth.get_settings",
        lambda: SimpleNamespace(
            auth_secret="synthetic-field-options-test-secret-very-long",
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


def options(client):
    result = client.get("/v1/settings/field-options?field_key=payout_purpose")
    assert result.status_code == 200, result.text
    return result.json()["items"]


def test_defaults_and_owner_add_edit_reorder_disable_are_audited(system):
    client, engine = system
    assert client.get("/v1/settings/field-options").status_code == 401
    csrf = login(client)
    initial = options(client)
    assert [row["label"] for row in initial] == [
        "Rent", "Utilities", "Maintenance", "Salary",
        "Vendor payment", "Reimbursement", "Other",
    ]
    endpoint = "/v1/settings/field-options"
    body = {"field_key": "payout_purpose", "label": "  Office    supplies  "}
    assert client.post(endpoint, json=body).status_code == 403
    created = client.post(endpoint, headers=csrf, json=body)
    assert created.status_code == 201, created.text
    option = created.json()
    assert option["label"] == "Office supplies"
    assert client.post(endpoint, headers=csrf, json={
        **body, "label": "office supplies",
    }).status_code == 409
    renamed = client.patch(
        endpoint + "/" + option["id"], headers=csrf,
        json={"version": option["version"], "label": "Office equipment"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["version"] == option["version"] + 1
    assert client.patch(endpoint + "/" + option["id"], headers=csrf, json={
        "version": option["version"], "label": "Unapproved old version",
    }).status_code == 409
    listing = options(client)
    reverse_order = list(reversed([x["id"] for x in listing]))
    changed = client.post(endpoint + "/reorder", headers=csrf, json={
        "field_key": "payout_purpose", "item_ids": reverse_order,
    })
    assert changed.status_code == 200, changed.text
    assert [r["id"] for r in changed.json()["items"]] == reverse_order
    assert [r["id"] for r in options(client)] == reverse_order
    current = next(x for x in options(client) if x["id"] == option["id"])
    deactivated = client.patch(endpoint + "/" + option["id"], headers=csrf, json={
        "version": current["version"], "is_active": False,
    })
    assert deactivated.status_code == 200, deactivated.text
    active = client.get(endpoint + "?field_key=payout_purpose&include_inactive=false")
    assert active.status_code == 200
    assert option["id"] not in [r["id"] for r in active.json()["items"]]
    with Session(engine) as db:
        logs = list(db.scalars(select(AuditEvent).where(
            AuditEvent.action.like("settings.field_option%"),
        )).all())
        assert len(logs) == 3
        assert logs[-1].before_data["is_active"] is True
        assert logs[-1].after_data["is_active"] is False


def test_payout_requires_approved_choice_and_preserves_history(system):
    client, engine = system
    csrf = login(client)
    maintenance = next(r for r in options(client) if r["label"] == "Maintenance")
    today = date.today().isoformat()
    body = {
        "request_id": str(uuid.uuid4()), "first_name": "Synthetic",
        "last_name": "Caretaker", "purpose": maintenance["label"],
        "purpose_option_id": maintenance["id"],
        "amount_paise": 50000, "paid_on": today,
        "payment_method": "cash",
        "payment_reference": "SYNTHETIC-REF-10001",
        "funds_disbursed": True,
    }
    # The date restriction is based on IST; use the business date.
    from app.accounting import ist_today
    body["paid_on"] = ist_today().isoformat()
    created = client.post("/v1/payouts/quick", headers=csrf, json=body)
    assert created.status_code == 201, created.text
    with Session(engine) as db:
        plan = db.scalars(select(PayoutPlan)).one()
        assert plan.purpose == "Maintenance"
        assert str(plan.purpose_option_id) == maintenance["id"]
    deactivated = client.patch(
        "/v1/settings/field-options/" + maintenance["id"], headers=csrf,
        json={"version": maintenance["version"], "is_active": False},
    )
    assert deactivated.status_code == 200, deactivated.text
    assert client.post("/v1/payouts/quick", headers=csrf, json={
        **body, "request_id": str(uuid.uuid4()),
        "payment_reference": "SYNTHETIC-REF-10002",
    }).status_code == 422
    assert client.post("/v1/payouts/quick", headers=csrf, json={
        **body, "request_id": str(uuid.uuid4()),
        "purpose": "Arbitrary payout purpose",
        "payment_reference": "SYNTHETIC-REF-10003",
    }).status_code == 422
    with Session(engine) as db:
        plan = db.scalars(select(PayoutPlan)).one()
        assert plan.purpose == "Maintenance"  # immutable audit snapshot
    assert client.get("/v1/payouts/plans").json()["items"][0]["purpose"] == "Maintenance"


def test_role_and_cross_tenant_options_are_restricted(system):
    client, engine = system
    owner_csrf = login(client)
    with Session(engine) as db:
        organization = Organization(name="Another Foundation")
        db.add(organization)
        db.flush()
        db.add(OrganizationSettings(
            organization_id=organization.id, currency_code="INR",
            timezone="Asia/Kolkata", default_contribution_paise=50000,
            sponsor_reminder_day=5, promoter_reminder_day=20,
            inactivity_months=2, automation_enabled=False,
        ))
        option = OrganizationFieldOption(
            organization_id=organization.id, field_key="payout_purpose",
            code="private-option", label="Secret expense",
            label_key="secret expense", is_active=True, sort_order=10, version=1,
        )
        db.add(option)
        owner = db.scalars(select(AdminUser).where(
            AdminUser.email == "admin@foundation.org",
        )).one()
        db.add(AdminUser(
            organization_id=owner.organization_id, email="finance@foundation.org",
            password_hash=hash_password("finance-test-password-long"),
            role="finance", is_active=True,
        ))
        db.commit()
        private_id = str(option.id)
    assert private_id not in [x["id"] for x in options(client)]
    assert client.patch("/v1/settings/field-options/" + private_id,
                        headers=owner_csrf, json={
                            "version": 1, "label": "Hijack",
                        }).status_code == 404
    finance_csrf = login(client, "finance@foundation.org",
                         "finance-test-password-long")
    assert len(options(client)) == 7
    assert client.post("/v1/settings/field-options", headers=finance_csrf, json={
        "field_key": "payout_purpose", "label": "Staff created",
    }).status_code == 403
