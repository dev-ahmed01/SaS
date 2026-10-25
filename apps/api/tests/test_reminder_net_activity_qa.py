"""Reminder eligibility must use current net-credit policy, not cached CRM labels.

Synthetic SQLite tenant + FastAPI requests only. No external sender is enabled.
"""
import uuid
from datetime import UTC, date, datetime

from activation_helper import activate_with_test_otp
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounting import ist_today, month_start, shift_month
from app.models import Prospect, SponsorshipRate

pytest_plugins = ("test_crm_review_2026_10",)


def _registered_active(client, csrf, engine, phone, start_month):
    created = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Reminder Policy Sponsor",
        "mobile_number": phone,
        "whatsapp_opt_in": True,
        "monthly_contribution_paise": 50000,
        "area_city": "Bengaluru",
    })
    assert created.status_code == 201, created.text
    person = created.json()
    stage = activate_with_test_otp(client, csrf, person)
    assert stage.status_code == 200, stage.text
    with Session(engine) as db:
        sponsor = db.get(Prospect, uuid.UUID(person["id"]))
        sponsor.start_month = start_month
        rate = db.scalars(select(SponsorshipRate).where(
            SponsorshipRate.prospect_id == sponsor.id,
        )).one()
        rate.effective_month = start_month
        db.commit()
    return stage.json()


def _audience(client, audience="prospects", segment="unpaid"):
    response = client.get("/v1/communication/audience", params={
        "audience": audience, "segment": segment,
        "channel": "whatsapp", "category": "reminder",
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_two_missed_months_exclude_sponsor_and_promoter_then_reactivate_after_credit(api):
    client, csrf, engine = api
    today = ist_today()
    month = month_start(today)
    sponsor = _registered_active(
        client, csrf, engine, "+918701001285", shift_month(month, -3),
    )
    promoter = client.post("/v1/promoters", headers=csrf, json={
        "full_name": "Reminder Policy Promoter",
        "mobile_number": "+918701002285",
        "whatsapp_opt_in": True,
        "area_city": "Bengaluru",
    })
    assert promoter.status_code == 201, promoter.text
    assigned = client.put(
        "/v1/promoters/" + promoter.json()["id"] + "/sponsors/" + sponsor["id"],
        headers={**csrf, "If-Match": str(sponsor["version"])},
    )
    assert assigned.status_code == 200, assigned.text

    # Materialized lifecycle was not refreshed: live eligibility must still
    # reject two completed months of zero net receipts.
    with Session(engine) as db:
        assert db.get(Prospect, uuid.UUID(sponsor["id"])).lifecycle_status == "new"
    assert _audience(client, segment="all")["eligible_count"] == 0
    assert _audience(client)["eligible_count"] == 0
    assert _audience(client, audience="promoters")["eligible_count"] == 0
    assert client.get("/v1/reminders/preview?kind=sponsor").json()["eligible_recipients"] == 0

    collection = client.post("/v1/collections", headers=csrf, json={
        "request_id": str(uuid.uuid4()),
        "prospect_id": sponsor["id"],
        "period_month": month.isoformat(),
        "received_on": today.isoformat(),
        "amount_paise": 25000,
        "payment_method": "upi",
        "receipt_reference": "REMINDER-REGRESSION-001",
        "funds_confirmed": True,
    })
    assert collection.status_code == 201, collection.text
    assert collection.json()["sponsor_status"] == "active"
    assert _audience(client)["eligible_count"] == 1
    assert _audience(client, audience="promoters")["eligible_count"] == 1
    assert client.get("/v1/reminders/preview?kind=sponsor").json()["eligible_recipients"] == 1

    reversed_receipt = client.post(
        "/v1/collections/" + collection.json()["id"] + "/reverse",
        headers=csrf, json={
            "request_id": str(uuid.uuid4()),
            "reason_code": "funds_not_received",
            "confirmation": "REVERSE",
        },
    )
    assert reversed_receipt.status_code == 201, reversed_receipt.text
    assert reversed_receipt.json()["sponsor_status"] == "inactive"
    assert _audience(client)["eligible_count"] == 0
    assert _audience(client, audience="promoters")["eligible_count"] == 0
    assert client.get("/v1/reminders/preview?kind=sponsor").json()["eligible_recipients"] == 0


def test_ist_midnight_changes_reminder_eligibility_without_manual_status_refresh(
    api, monkeypatch,
):
    client, csrf, engine = api
    _registered_active(
        client, csrf, engine, "+918701001286", shift_month(month_start(ist_today()), -1),
    )
    # Fix the historical enrollment for this controlled Sep->Nov transition.
    with Session(engine) as db:
        sponsor = db.scalars(select(Prospect)).one()
        sponsor.start_month = date(2026, 9, 1)
        rate = db.scalars(select(SponsorshipRate)).one()
        rate.effective_month = sponsor.start_month
        db.commit()

    monkeypatch.setattr(
        "app.communication.utc_now",
        lambda: datetime(2026, 10, 31, 18, 29, tzinfo=UTC),
    )
    before = _audience(client)
    assert before["eligible_count"] == 1  # Sep is the only completed missing month.

    monkeypatch.setattr(
        "app.communication.utc_now",
        lambda: datetime(2026, 10, 31, 18, 30, tzinfo=UTC),
    )
    after = _audience(client)
    assert after["eligible_count"] == 0  # Sep and Oct now both completed and missed.
