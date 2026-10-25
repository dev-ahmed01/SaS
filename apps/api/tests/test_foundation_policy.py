"""Foundation-approved ₹250 denominations, activity lifecycle and reversals."""
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from activation_helper import activate_with_test_otp
from app.accounting import evaluate_status, ist_today, month_start, shift_month
from app.bootstrap_admin import provision_admin
from app.main import app
from app.models import Base, OrganizationSettings, Prospect, SponsorshipRate
from app.sponsorship_policy import valid_commitment


def sponsor(start: date):
    return SimpleNamespace(start_month=start, archived_at=None, archive_intervals=[])


def rate(start: date):
    return SimpleNamespace(effective_month=start, amount_paise=25000)


def credit(period: date, recorded_at: datetime, amount: int = 25000):
    return SimpleNamespace(
        period_month=period, verified_at=recorded_at, amount_paise=amount,
    )


@pytest.mark.parametrize("amount,valid", [
    (0, False), (1, False), (12500, False), (25000, True),
    (37500, False), (50000, True), (75000, True),
    (1000000000, True), (1000025000, False),
])
def test_approved_250_tiers_apply_to_incoming_contributions(amount, valid):
    assert valid_commitment(amount) is valid


def test_two_completed_zero_receipt_months_and_valid_reactivation():
    start = date(2026, 1, 1)
    person = sponsor(start)
    rates = [rate(start)]
    as_of = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
    january = credit(start, datetime(2026, 1, 15, tzinfo=UTC))
    assert evaluate_status(
        person, rates, [january], date(2026, 4, 1), as_of,
    ) == "inactive"
    # A valid ₹250 receipt reactivates even when allocated to an older month.
    newly_recorded = credit(start, as_of, amount=25000)
    assert evaluate_status(
        person, rates, [january, newly_recorded], date(2026, 4, 1), as_of,
    ) == "active"
    # May/June are completed and neither contains positive recorded activity.
    later = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    assert evaluate_status(
        person, rates, [january, newly_recorded], date(2026, 7, 1), later,
    ) == "inactive"


def test_new_sponsor_needs_two_completed_enrollment_months():
    person = sponsor(date(2026, 9, 1))
    rates = [rate(date(2026, 9, 1))]
    now = datetime(2026, 10, 31, 17, 0, tzinfo=UTC)
    assert evaluate_status(
        person, rates, [], date(2026, 10, 31), now,
    ) == "new"
    next_month = datetime(2026, 10, 31, 19, 0, tzinfo=UTC)
    assert evaluate_status(
        person, rates, [], date(2026, 11, 1), next_month,
    ) == "inactive"
    assert evaluate_status(
        person, rates, [
            credit(date(2026, 9, 1), next_month, amount=25000)
        ], date(2026, 11, 1), next_month,
    ) == "active"


def test_future_or_reversed_credit_cannot_create_positive_activity():
    p = sponsor(date(2026, 8, 1))
    rates = [rate(p.start_month)]
    today = date(2026, 11, 1)
    now = datetime(2026, 10, 31, 19, 0, tzinfo=UTC)
    future = credit(date(2026, 11, 1), now.replace(year=2027))
    assert evaluate_status(p, rates, [future], today, now) == "inactive"
    # Effective credits remove full reversals before status evaluation.
    assert evaluate_status(p, rates, [], today, now) == "inactive"


@pytest.fixture
def policy_api(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        provision_admin(
            db, email="admin@foundation.org",
            password="synthetic-admin-password-long",
            organization_name="Emlen Foundation",
        )
    monkeypatch.setattr("app.auth.get_engine", lambda: engine)
    monkeypatch.setattr("app.auth.get_settings", lambda: SimpleNamespace(
        auth_secret="synthetic-auth-secret-for-foundation-policy-12345",
        app_env="test",
    ))
    monkeypatch.setattr("app.prospects.get_settings", lambda: SimpleNamespace(
        upi_match_secret="synthetic-upi-key-for-policy-tests-1234567890",
    ))
    with TestClient(app) as client:
        login = client.post("/v1/auth/login", json={
            "email": "admin@foundation.org",
            "password": "synthetic-admin-password-long",
        })
        assert login.status_code == 200, login.text
        headers = {"X-CSRF-Token": client.get("/v1/auth/session").json()["csrf_token"]}
        yield client, engine, headers
    engine.dispose()


def test_new_org_defaults_to_250_and_rejects_non_tiers(policy_api):
    client, _engine, csrf = policy_api
    settings = client.get("/v1/settings")
    assert settings.status_code == 200
    assert settings.json()["default_contribution_paise"] == 25000
    for invalid in (0, 12500, 37500, 50100):
        result = client.patch("/v1/settings", headers=csrf, json={
            "default_contribution_paise": invalid,
        })
        assert result.status_code == 422, (invalid, result.text)
    assert client.patch("/v1/settings", headers=csrf, json={
        "inactivity_months": 3,
    }).status_code == 422
    assert client.patch("/v1/settings", headers=csrf, json={
        "default_contribution_paise": 75000,
    }).status_code == 200
    for invalid in (12500, 37500):
        result = client.post("/v1/prospects", headers=csrf, json={
            "full_name": "Invalid Commitment",
            "mobile_number": "+919876500001",
            "area_city": "Bengaluru",
            "monthly_contribution_paise": invalid,
        })
        assert result.status_code == 422, result.text


def test_250_receipt_reactivates_and_full_reversal_deactivates(policy_api):
    client, engine, csrf = policy_api
    person = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Sponsor Synthetic",
        "mobile_number": "+919876500002",
        "area_city": "Bengaluru",
    })
    assert person.status_code == 201, person.text
    profile = person.json()
    started = activate_with_test_otp(client, csrf, profile)
    assert started.status_code == 200, started.text
    profile = started.json()
    assert profile["monthly_contribution_paise"] == 25000
    current = month_start(ist_today())
    first = shift_month(current, -2)
    with Session(engine) as db:
        row = db.get(Prospect, uuid.UUID(profile["id"]))
        row.start_month = first
        agreement = db.scalars(select(SponsorshipRate).where(
            SponsorshipRate.prospect_id == row.id,
        )).one()
        agreement.effective_month = first
        db.commit()
    pre = client.get("/v1/accounting/overview")
    assert pre.json()["items"][0]["status"] == "inactive"
    payment = client.post("/v1/collections", headers=csrf, json={
        "request_id": str(uuid.uuid4()),
        "prospect_id": profile["id"],
        "period_month": first.isoformat(),  # late allocation does not block activation
        "received_on": ist_today().isoformat(),
        "amount_paise": 25000,
        "payment_method": "upi",
        "receipt_reference": "POLICYRECEIPT12345",
        "funds_confirmed": True,
    })
    assert payment.status_code == 201, payment.text
    assert payment.json()["sponsor_status"] == "active"
    assert client.get("/v1/prospects/" + profile["id"]).json()[
        "last_verified_payment_at"
    ] is not None
    assert client.get("/v1/accounting/overview").json()["items"][0]["status"] == "active"
    current_due = client.get("/v1/accounting/overview").json()
    assert current_due["due_paise"] == 25000
    assert current_due["verified_paise"] == 0  # credit allocated to first month
    assert current_due["outstanding_paise"] == 25000
    reversal = client.post(
        "/v1/collections/" + payment.json()["id"] + "/reverse",
        headers=csrf,
        json={
            "request_id": str(uuid.uuid4()),
            "reason_code": "wrong_amount",
            "confirmation": "REVERSE",
        },
    )
    assert reversal.status_code == 201, reversal.text
    assert reversal.json()["sponsor_status"] == "inactive"
    assert client.get("/v1/prospects/" + profile["id"]).json()[
        "last_verified_payment_at"
    ] is None
    assert client.get("/v1/accounting/overview").json()["items"][0]["status"] == "inactive"


def test_existing_500_commitment_stays_historically_effective(policy_api):
    client, engine, csrf = policy_api
    person = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Legacy Synthetic",
        "mobile_number": "+919876500003",
        "area_city": "Bengaluru",
        "monthly_contribution_paise": 50000,
    })
    assert person.status_code == 201, person.text
    row = person.json()
    update = client.patch("/v1/prospects/" + row["id"], headers=csrf, json={
        "version": row["version"], "monthly_contribution_paise": 75000,
    })
    assert update.status_code == 200, update.text
    with Session(engine) as db:
        rates = list(db.scalars(select(SponsorshipRate).where(
            SponsorshipRate.prospect_id == uuid.UUID(row["id"]),
        ).order_by(SponsorshipRate.effective_month)))
        assert len(rates) == 2
        assert rates[0].amount_paise == 50000
        assert rates[1].amount_paise == 75000


def test_legacy_sponsorship_can_edit_contacts_without_repricing(policy_api):
    client, engine, csrf = policy_api
    created = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Older Synthetic",
        "mobile_number": "+919876500004",
        "area_city": "Bengaluru",
        "monthly_contribution_paise": 50000,
    })
    assert created.status_code == 201, created.text
    item = created.json()
    with Session(engine) as db:
        person = db.get(Prospect, uuid.UUID(item["id"]))
        person.monthly_contribution_paise = 37500
        db.scalars(select(SponsorshipRate).where(
            SponsorshipRate.prospect_id == person.id,
        )).one().amount_paise = 37500
        org = db.get(OrganizationSettings, person.organization_id)
        org.default_contribution_paise = 37500
        db.commit()

    changed = client.patch("/v1/prospects/" + item["id"], headers=csrf, json={
        "version": item["version"], "notes": "Phone verified by Admin",
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()["monthly_contribution_paise"] == 37500
    day = client.patch("/v1/settings", headers=csrf, json={
        "sponsor_reminder_day": 6,
    })
    assert day.status_code == 200, day.text
    assert day.json()["default_contribution_paise"] == 37500
    # No new agreement may inherit an outdated non-tier legacy default.
    rejected = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "New Synthetic",
        "mobile_number": "+919876500005", "area_city": "Bengaluru",
    })
    assert rejected.status_code == 409, rejected.text
    with Session(engine) as db:
        rate = db.scalars(select(SponsorshipRate)).one()
        assert rate.amount_paise == 37500


def test_prospect_patch_rejects_new_off_tier_rates_and_keeps_legacy_identity(policy_api):
    client, engine, csrf = policy_api
    created = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Synthetic Signed Agreement",
        "mobile_number": "+919876500092",
        "area_city": "Bengaluru",
        "monthly_contribution_paise": 50000,
    })
    assert created.status_code == 201, created.text
    person = created.json()
    endpoint = "/v1/prospects/" + person["id"]
    for amount in (1, 12500, 37500, 70000):
        result = client.patch(endpoint, headers=csrf, json={
            "version": person["version"], "monthly_contribution_paise": amount,
        })
        assert result.status_code == 422, (amount, result.text)
    with Session(engine) as db:
        all_rates = list(db.scalars(select(SponsorshipRate).where(
            SponsorshipRate.prospect_id == uuid.UUID(person["id"]),
        )))
        assert len(all_rates) == 1
        assert all_rates[0].amount_paise == 50000
    success = client.patch(endpoint, headers=csrf, json={
        "version": person["version"], "monthly_contribution_paise": 75000,
    })
    assert success.status_code == 200, success.text
