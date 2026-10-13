"""Tenant-bound Prospects API acceptance tests, using synthetic data."""

import uuid
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
    Prospect,
    ProspectUpiIdentifier,
    SponsorshipRate,
)
from app.security import hash_password

BASE = {
    "full_name": "Ayesha Khan",
    "mobile_number": "+919876543210",
    "area_city": "Bengaluru",
}


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
            db, email="office@foundation.org", password="synthetic-long-admin-password",
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


def login(client):
    response = client.post(
        "/v1/auth/login",
        json={"email": "office@foundation.org", "password": "synthetic-long-admin-password"},
    )
    assert response.status_code == 200
    return {"X-CSRF-Token": client.get("/v1/auth/session").json()["csrf_token"]}


def create(client, csrf, **changes):
    return client.post("/v1/prospects", json={**BASE, **changes}, headers=csrf)


def test_requires_admin_csrf_and_starts_new(system):
    client, engine = system
    assert client.get("/v1/prospects").status_code == 401
    assert client.post("/v1/prospects", json=BASE).status_code == 401
    csrf = login(client)
    assert client.post("/v1/prospects", json=BASE).status_code == 403
    r = create(client, csrf)
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["lifecycle_status"] == "new"
    assert item["monthly_contribution_paise"] == 50000
    assert item["version"] == 1
    assert not item["upi_ids"]
    assert client.patch(
        "/v1/prospects/" + item["id"],
        headers=csrf, json={"version": 1, "lifecycle_status": "active"},
    ).status_code == 422
    with Session(engine) as db:
        assert db.scalars(select(Prospect)).one().lifecycle_status == "new"


def test_upi_is_not_stored_in_plaintext_and_can_be_revoked(system):
    client, engine = system
    csrf = login(client)
    r = create(client, csrf, upi_ids=["Ahmed123@oksbi"])
    assert r.status_code == 201, r.text
    item = r.json()
    assert len(item["upi_ids"]) == 1
    assert not item["upi_ids"][0]["is_verified"]
    assert "Ahmed123" not in r.text
    with Session(engine) as db:
        rec = db.scalars(select(ProspectUpiIdentifier)).one()
        assert len(rec.digest) == 64
        assert "ahmed123" not in str(rec.__dict__).lower()
    path = "/v1/prospects/" + item["id"] + "/upi-ids"
    uid = item["upi_ids"][0]["id"]
    revoked = client.delete(path + "/" + uid, headers={**csrf, "If-Match": "1"})
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["upi_ids"] == []
    restored = client.post(
        path, headers=csrf, json={"upi_id": "ahmed123@oksbi", "version": 2}
    )
    assert restored.status_code == 201, restored.text
    assert restored.json()["upi_ids"][0]["id"] == uid


def test_search_filter_soft_delete_restore_and_version_conflict(system):
    client, engine = system
    csrf = login(client)
    first = create(client, csrf).json()
    second = create(
        client, csrf, full_name="Sana Sheikh", mobile_number="+919888877766"
    ).json()
    with Session(engine) as db:
        record = db.get(Prospect, uuid.UUID(first["id"]))
        record.lifecycle_status = "active"  # stale materialized cache
        old_month = shift_month(month_start(ist_today()), -2)
        record.start_month = old_month
        rate = db.scalars(select(SponsorshipRate).where(
            SponsorshipRate.prospect_id == record.id,
        )).one()
        rate.effective_month = old_month
        db.commit()
    assert client.get("/v1/prospects?status=inactive").json()["total"] == 1
    assert client.get("/v1/prospects?q=sheikh").json()["items"][0]["id"] == second["id"]
    assert client.get("/v1/prospects?limit=1").json()["total"] == 2
    assert client.get("/v1/prospects?q=%25").json()["total"] == 0
    assert client.get("/v1/prospects?limit=101").status_code == 422
    edit = client.patch(
        "/v1/prospects/" + second["id"],
        headers=csrf, json={"version": 1, "notes": "Call next week"},
    )
    assert edit.status_code == 200
    assert edit.json()["version"] == 2
    assert client.patch(
        "/v1/prospects/" + second["id"],
        headers=csrf, json={"version": 1, "notes": "stale"},
    ).status_code == 409
    assert client.delete(
        "/v1/prospects/" + first["id"], headers={**csrf, "If-Match": "1"}
    ).status_code == 204
    assert client.get("/v1/prospects?status=inactive").json()["total"] == 0
    assert client.get("/v1/prospects?include_archived=true").json()["total"] == 2
    assert client.post(
        "/v1/prospects/" + first["id"] + "/restore",
        headers={**csrf, "If-Match": "2"},
    ).status_code == 200
    assert client.get("/v1/prospects?status=inactive").json()["total"] == 1


def test_input_validation_and_no_unverified_status_setting(system):
    client, engine = system
    csrf = login(client)
    assert create(client, csrf, mobile_number="invalid").status_code == 422
    assert create(client, csrf, upi_ids=["bad-UPI"]).status_code == 422
    assert create(client, csrf, upi_ids=["payer@oksbi", "PAYER@oksbi"]).status_code == 422
    item = create(client, csrf).json()
    path = "/v1/prospects/" + item["id"]
    assert client.patch(path, headers=csrf, json={"version": 1}).status_code == 422
    assert client.patch(
        path, headers=csrf, json={"version": 1, "full_name": None}
    ).status_code == 422
    assert client.patch(
        path, headers=csrf, json={"version": 1, "mobile_number": "111"}
    ).status_code == 422
    assert client.delete(path, headers=csrf).status_code == 428
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Prospect)) == 1


def test_org_isolation_and_independent_contribution_defaults(system):
    client, engine = system
    csrf = login(client)
    first = create(client, csrf).json()
    with Session(engine) as db:
        other = Organization(name="Second Foundation")
        db.add(other)
        db.flush()
        db.add(AdminUser(
            organization_id=other.id,
            email="different@foundation.org",
            password_hash=hash_password("synthetic-second-admin-password"),
            is_active=True,
        ))
        db.add(OrganizationSettings(
            organization_id=other.id,
            currency_code="INR", timezone="Asia/Kolkata",
            default_contribution_paise=75000,
            sponsor_reminder_day=8, promoter_reminder_day=20,
            inactivity_months=2, automation_enabled=False,
        ))
        db.commit()
    assert client.post(
        "/v1/auth/login", json={
            "email": "different@foundation.org",
            "password": "synthetic-second-admin-password",
        }
    ).status_code == 200
    other_csrf = {"X-CSRF-Token": client.get("/v1/auth/session").json()["csrf_token"]}
    assert client.get("/v1/prospects").json()["total"] == 0
    assert client.get("/v1/prospects/" + first["id"]).status_code == 404
    assert client.patch(
        "/v1/prospects/" + first["id"],
        json={"version": 1, "notes": "unapproved"},
        headers=other_csrf,
    ).status_code == 404
    assert client.delete(
        "/v1/prospects/" + first["id"],
        headers={**other_csrf, "If-Match": "1"},
    ).status_code == 404
    new_item = create(client, other_csrf).json()
    assert new_item["monthly_contribution_paise"] == 75000
    assert client.get("/v1/prospects").json()["total"] == 1


def test_upi_key_missing_fails_closed_and_audits_omit_personal_values(system, monkeypatch):
    client, engine = system
    csrf = login(client)
    monkeypatch.setattr(
        "app.prospects.get_settings",
        lambda: SimpleNamespace(upi_match_secret=None),
    )
    assert create(client, csrf, upi_ids=["payer@oksbi"]).status_code == 503
    monkeypatch.setattr(
        "app.prospects.get_settings",
        lambda: SimpleNamespace(upi_match_secret="synthetic-valid-upi-match-secret-0123456789"),
    )
    candidate = create(
        client, csrf, full_name="Sensitive Test Candidate",
        notes="private notes for demonstration", upi_ids=["payer@oksbi"],
    ).json()
    assert client.patch(
        "/v1/prospects/" + candidate["id"],
        json={"version": 1, "notes": "private updated note"},
        headers=csrf,
    ).status_code == 200
    with Session(engine) as db:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == "prospect")
        ).all()
        audit_values = str([event.after_data for event in events])
        assert "Sensitive Test Candidate" not in audit_values
        assert "private" not in audit_values
        assert "payer@oksbi" not in audit_values


def test_retried_registration_is_idempotent_and_conflicting_payload_rejected(system):
    client, engine = system
    csrf = login(client)
    registration_key = str(uuid.uuid4())
    payload = {**BASE, "request_id": registration_key, "upi_ids": ["payer@oksbi"]}
    first = client.post("/v1/prospects", headers=csrf, json=payload)
    assert first.status_code == 201, first.text
    repeat = client.post("/v1/prospects", headers=csrf, json=payload)
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["id"] == first.json()["id"]
    assert len(repeat.json()["upi_ids"]) == 1
    tampered = client.post(
        "/v1/prospects", headers=csrf,
        json={**payload, "full_name": "Different Person"},
    )
    assert tampered.status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Prospect)) == 1


def test_request_fingerprint_is_keyed_even_when_upi_is_supplied(system):
    """Raw SHA-256 of sensitive request fields would allow offline VPA guesses."""
    import hashlib
    import json

    from app.prospects import ProspectCreate

    client, engine = system
    csrf = login(client)
    supplied = {
        **BASE,
        "upi_ids": ["hidden-user@oksbi"],
        "request_id": str(uuid.uuid4()),
    }
    first = client.post("/v1/prospects", json=supplied, headers=csrf)
    assert first.status_code == 201, first.text
    duplicate = client.post("/v1/prospects", json=supplied, headers=csrf)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["id"] == first.json()["id"]
    modified = client.post("/v1/prospects", json={
        **supplied, "upi_ids": ["other-user@oksbi"],
    }, headers=csrf)
    assert modified.status_code == 409, modified.text

    canonical = json.dumps(
        ProspectCreate(**supplied).model_dump(mode="json", exclude={"request_id"}),
        sort_keys=True, ensure_ascii=True,
    ).encode("utf-8")
    plain_digest = hashlib.sha256(canonical).hexdigest()
    with Session(engine) as db:
        saved = db.scalars(select(Prospect)).one()
        assert len(saved.registration_payload_hash) == 64
        assert saved.registration_payload_hash != plain_digest
        assert "hidden-user" not in saved.registration_payload_hash


def test_plain_registration_without_upi_secret_still_works(system, monkeypatch):
    client, engine = system
    csrf = login(client)
    monkeypatch.setattr("app.prospects.get_settings", lambda: SimpleNamespace(
        upi_match_secret=None,
        auth_secret="synthetic-fallback-hmac-secret-long-enough-1234",
    ))
    payload = {**BASE, "request_id": str(uuid.uuid4())}
    first = create(client, csrf, request_id=payload["request_id"])
    assert first.status_code == 201, first.text
    retried = create(client, csrf, request_id=payload["request_id"])
    assert retried.status_code == 200, retried.text
    assert retried.json()["id"] == first.json()["id"]
    assert create(client, csrf, upi_ids=["sponsor@upi"]).status_code == 503
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Prospect)) == 1


def test_location_is_optional_for_new_sponsor_without_fake_placeholder(system):
    client, engine = system
    csrf = login(client)
    response = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "No Location Sponsor",
        "mobile_number": "+919876543211",
    })
    assert response.status_code == 201, response.text
    assert response.json()["area_city"] == ""
    with Session(engine) as db:
        assert db.scalars(select(Prospect).where(
            Prospect.id == response.json()["id"]
        )).one().area_city == ""
