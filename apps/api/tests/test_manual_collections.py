"""Manual collection acceptance: financial attestation, consent and idempotency."""
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from activation_helper import activate_with_test_otp
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
    MessageDispatch,
    MessageOutbox,
    OrganizationSettings,
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
    result = client.post("/v1/auth/login", json={
        "email": "admin@foundation.org", "password": "synthetic-long-admin-password",
    })
    assert result.status_code == 200, result.text
    return {"X-CSRF-Token": client.get("/v1/auth/session").json()["csrf_token"]}


def activate_for_financial_flow(client, csrf, record):
    """Older payment/reminder tests explicitly activate enrolled CRM prospects."""
    response = activate_with_test_otp(client, csrf, record)
    assert response.status_code == 200, response.text
    return response.json()


def sponsor(client, headers, consent):
    response = client.post("/v1/prospects", headers=headers, json={
        "full_name": "Synthetic Sponsor",
        "mobile_number": "+919876543210",
        "area_city": "Bengaluru",
        "whatsapp_opt_in": consent,
        "monthly_contribution_paise": 50000,
    })
    assert response.status_code == 201, response.text
    return activate_for_financial_flow(client, headers, response.json())


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
        **original, "amount_paise": 75000,
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


def test_missing_consent_suppresses_message_and_250_receipt_tracks_balance(system):
    client, engine = system
    csrf = login(client)
    p = sponsor(client, csrf, consent=False)
    receipt = {**sample(p["id"]), "amount_paise": 25000}
    res = client.post("/v1/collections", headers=csrf, json=receipt)
    assert res.status_code == 201, res.text
    assert res.json()["message_status"] == "suppressed"
    ledger = client.get("/v1/accounting/overview").json()
    assert ledger["verified_paise"] == 25000
    assert ledger["outstanding_paise"] == 25000
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
        "/v1/prospects/" + p["id"], headers={**csrf, "If-Match": str(p["version"])},
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
    assert response.json()["items"][0]["sponsor_mobile"] == p["mobile_number"]
    current_month = month_start(ist_today()).isoformat()
    paid_this_month = client.get("/v1/collections?received_month=" + current_month)
    assert paid_this_month.status_code == 200, paid_this_month.text
    assert paid_this_month.json()["total"] == 1
    assert client.get("/v1/collections?received_month=2026-10-03").status_code == 422
    assert client.get("/v1/prospects/" + p["id"]).json()["total_contribution_paise"] == 50000
    assert client.get("/v1/collections?limit=101").status_code == 422
    assert client.get("/v1/collections?period_month=2026-10-03").status_code == 422
    with Session(engine) as db:
        assert db.get(Prospect, uuid.UUID(p["id"])) is not None


def test_contribution_denominations_reject_under_250_and_nonmultiples(system):
    client, engine = system
    csrf = login(client)
    person = sponsor(client, csrf, consent=True)
    for invalid in (0, 1, 12500, 24999, 25001, 37500, 70000):
        request = {
            **sample(person["id"]),
            "request_id": str(uuid.uuid4()),
            "amount_paise": invalid,
        }
        result = client.post("/v1/collections", headers=csrf, json=request)
        assert result.status_code == 422, (invalid, result.text)
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ManualCollection)) == 0
        assert db.scalar(select(func.count()).select_from(VerifiedCredit)) == 0
        assert db.scalar(select(func.count()).select_from(MessageOutbox)) == 0

    accepted = client.post("/v1/collections", headers=csrf, json={
        **sample(person["id"]), "amount_paise": 25000,
    })
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["amount_paise"] == 25000


def test_exact_legacy_off_tier_request_replay_is_read_only(system):
    from app.collections import CollectionInput, _legacy_payload_hash, _legacy_reference_hash

    client, engine = system
    csrf = login(client)
    person = sponsor(client, csrf, consent=False)
    payload = {**sample(person["id"]), "amount_paise": 12500}
    checked = CollectionInput(**payload)
    with Session(engine) as db:
        existing = db.get(Prospect, uuid.UUID(person["id"]))
        from app.models import ManualCollection, MessageOutbox, VerifiedCredit
        from app.security import utc_now

        proof = VerifiedCredit(
            organization_id=existing.organization_id, prospect_id=existing.id,
            period_month=checked.period_month, amount_paise=12500,
            source_type="manual_attested",
            source_key="manual:legacy-preserved-synthetic",
            verified_at=utc_now(),
        )
        db.add(proof)
        db.flush()
        receipt = ManualCollection(
            organization_id=existing.organization_id, prospect_id=existing.id,
            verified_credit_id=proof.id, request_id=checked.request_id,
            request_payload_hash=_legacy_payload_hash(checked),
            reference_digest=_legacy_reference_hash(checked.receipt_reference),
            reference_mask="****F001",
            received_on=checked.received_on, period_month=checked.period_month,
            payment_method=checked.payment_method, amount_paise=12500,
        )
        db.add(receipt)
        db.flush()
        db.add(MessageOutbox(
            organization_id=existing.organization_id,
            prospect_id=existing.id, collection_id=receipt.id,
            event_type="collection_recorded", status="suppressed",
            suppress_reason="consent_missing",
        ))
        db.commit()
        original_id = str(receipt.id)
    retried = client.post("/v1/collections", headers=csrf, json=payload)
    assert retried.status_code == 200, retried.text
    assert retried.json()["id"] == original_id
    assert retried.json()["amount_paise"] == 12500
    changed = client.post("/v1/collections", headers=csrf, json={
        **payload, "amount_paise": 25000,
    })
    assert changed.status_code == 409, changed.text
    fresh_invalid = client.post("/v1/collections", headers=csrf, json={
        **payload, "request_id": str(uuid.uuid4()),
    })
    assert fresh_invalid.status_code == 422, fresh_invalid.text
    # Replaying the full legacy *reference* with a new id is also rejected.
    ref_again = client.post("/v1/collections", headers=csrf, json={
        **payload, "request_id": str(uuid.uuid4()), "amount_paise": 25000,
    })
    assert ref_again.status_code == 409, ref_again.text
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ManualCollection)) == 1
        assert db.scalar(select(func.count()).select_from(VerifiedCredit)) == 1


def test_new_collection_reference_and_request_fingerprints_are_keyed(system):
    import hashlib

    client, engine = system
    csrf = login(client)
    person = sponsor(client, csrf, consent=False)
    payload = sample(person["id"])
    recorded = client.post("/v1/collections", headers=csrf, json=payload)
    assert recorded.status_code == 201, recorded.text
    with Session(engine) as db:
        row = db.scalars(select(ManualCollection)).one()
        assert row.reference_digest != hashlib.sha256(
            payload["receipt_reference"].encode()
        ).hexdigest()
        assert len(row.reference_digest) == len(row.request_payload_hash) == 64
        assert row.request_payload_hash != hashlib.sha256(
            __import__("json").dumps({
                key: value for key, value in payload.items() if key != "request_id"
            }, sort_keys=True).encode()
        ).hexdigest()
    assert client.post("/v1/collections", headers=csrf, json=payload).status_code == 200


def test_active_only_excludes_reversed_contributions(system):
    client, _ = system
    csrf = login(client)
    person = sponsor(client, csrf, consent=False)
    payment = client.post("/v1/collections", headers=csrf, json=sample(person["id"]))
    assert payment.status_code == 201, payment.text
    active = client.get("/v1/collections?active_only=true")
    assert active.status_code == 200
    assert active.json()["total"] == 1
    reversed_payment = client.post(
        "/v1/collections/" + payment.json()["id"] + "/reverse",
        headers=csrf,
        json={
            "request_id": str(uuid.uuid4()),
            "reason_code": "duplicate_entry",
            "confirmation": "REVERSE",
        },
    )
    assert reversed_payment.status_code == 201, reversed_payment.text
    assert client.get("/v1/collections?active_only=true").json()["total"] == 0
    assert client.get("/v1/collections").json()["total"] == 1


def test_missing_external_reference_uses_internal_unique_ledger_key(system):
    client, engine = system
    csrf = login(client)
    person = sponsor(client, csrf, consent=False)
    payload = sample(person["id"])
    payload.pop("receipt_reference")
    first = client.post("/v1/collections", headers=csrf, json=payload)
    assert first.status_code == 201, first.text
    assert first.json()["reference_mask"] == "Not provided"
    assert first.json()["evidence"] == "admin_attested"
    replay = client.post("/v1/collections", headers=csrf, json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == first.json()["id"]
    second = client.post("/v1/collections", headers=csrf, json={
        **payload, "request_id": str(uuid.uuid4()),
    })
    assert second.status_code == 201, second.text
    assert second.json()["id"] != first.json()["id"]
    with Session(engine) as db:
        receipts = db.scalars(select(ManualCollection)).all()
        assert len(receipts) == 2
        assert receipts[0].reference_digest != receipts[1].reference_digest
        assert db.scalar(select(func.count()).select_from(VerifiedCredit)) == 2
        assert db.scalar(select(func.count()).select_from(MessageOutbox)) == 2
    # Supplied external IDs retain strict syntax and uniqueness rules.
    invalid = client.post("/v1/collections", headers=csrf, json={
        **payload, "request_id": str(uuid.uuid4()),
        "receipt_reference": "BAD VALUE",
    })
    assert invalid.status_code == 422


def test_resend_confirmation_requires_approved_worker_and_definite_original_status(
    system, monkeypatch,
):
    client, engine = system
    csrf = login(client)
    person = sponsor(client, csrf, consent=True)
    payment = client.post("/v1/collections", headers=csrf, json=sample(person["id"]))
    assert payment.status_code == 201, payment.text
    collection_id = payment.json()["id"]
    path = "/v1/collections/" + collection_id + "/resend-confirmation"
    input_data = {"request_id": str(uuid.uuid4()), "confirmation": "RESEND"}
    assert client.post(path, json=input_data).status_code == 403
    assert client.post(path, headers=csrf, json=input_data).status_code == 503

    monkeypatch.setattr("app.collections.get_settings", lambda: SimpleNamespace(
        messaging_delivery_enabled=True, messaging_sender_approved=True,
        messaging_enable_after=datetime.now(UTC) - timedelta(days=1),
    ))
    with Session(engine) as db:
        setting = db.get(OrganizationSettings, uuid.UUID(person["id"]))  # not an org UUID
        assert setting is None
        prospect = db.get(Prospect, uuid.UUID(person["id"]))
        cfg = db.get(OrganizationSettings, prospect.organization_id)
        cfg.automation_enabled = True
        db.commit()
    # An unattempted original message is pending, not eligible for a resend.
    assert client.post(path, headers=csrf, json=input_data).status_code == 409
    with Session(engine) as db:
        event = db.scalars(select(MessageOutbox).where(
            MessageOutbox.collection_id == uuid.UUID(collection_id),
        )).one()
        db.add(MessageDispatch(
            organization_id=event.organization_id, outbox_id=event.id,
            category="collection", status="failed",
        ))
        db.commit()

    first = client.post(path, headers=csrf, json=input_data)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "queued"
    assert "delivery is not confirmed" in first.json()["notice"]
    again = client.post(path, headers=csrf, json=input_data)
    assert again.status_code == 200
    assert again.json()["status"] == "already_queued"
    listed = client.get("/v1/collections")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["message_status"] == "awaiting_integration"
    with Session(engine) as db:
        events = db.scalars(select(MessageOutbox).where(
            MessageOutbox.collection_id == uuid.UUID(collection_id),
        )).all()
        assert len(events) == 2
    reverted = client.post(
        "/v1/collections/" + collection_id + "/reverse", headers=csrf,
        json={"request_id": str(uuid.uuid4()), "reason_code": "wrong_amount",
              "confirmation": "REVERSE"},
    )
    assert reverted.status_code == 201, reverted.text
    with Session(engine) as db:
        retry = db.scalars(select(MessageOutbox).where(
            MessageOutbox.collection_id == uuid.UUID(collection_id),
            MessageOutbox.event_type == "collection_confirmation_resend",
        )).one()
        assert retry.status == "suppressed"
    assert client.post(path, headers=csrf, json=input_data).status_code == 409


def test_resend_rejects_uncertain_original_delivery(system, monkeypatch):
    client, engine = system
    csrf = login(client)
    person = sponsor(client, csrf, consent=True)
    receipt = client.post("/v1/collections", headers=csrf, json=sample(person["id"]))
    assert receipt.status_code == 201
    monkeypatch.setattr("app.collections.get_settings", lambda: SimpleNamespace(
        messaging_delivery_enabled=True, messaging_sender_approved=True,
        messaging_enable_after=datetime.now(UTC) - timedelta(days=1),
    ))
    with Session(engine) as db:
        p = db.get(Prospect, uuid.UUID(person["id"]))
        db.get(OrganizationSettings, p.organization_id).automation_enabled = True
        original = db.scalars(select(MessageOutbox).where(
            MessageOutbox.collection_id == uuid.UUID(receipt.json()["id"]),
        )).one()
        db.add(MessageDispatch(
            organization_id=original.organization_id, outbox_id=original.id,
            category="collection", status="accepted",
        ))
        db.commit()
    attempt = client.post(
        "/v1/collections/" + receipt.json()["id"] + "/resend-confirmation",
        headers=csrf, json={"request_id": str(uuid.uuid4()), "confirmation": "RESEND"},
    )
    assert attempt.status_code == 409, attempt.text
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(MessageOutbox)) == 1
