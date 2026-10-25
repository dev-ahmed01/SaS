"""Promoter assignment lists must agree with read-only IST financial status.

All fixtures are synthetic and tenant-scoped; no real payment or message is sent.
"""
import uuid
from datetime import UTC, date, datetime

from activation_helper import activate_with_test_otp
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Prospect, SponsorshipRate, VerifiedCredit

pytest_plugins = ("test_crm_review_2026_10",)


def _new_sponsor(client, csrf, *, name: str, phone: str):
    response = client.post("/v1/prospects", headers=csrf, json={
        "full_name": name, "mobile_number": phone,
        "area_city": "Bengaluru", "monthly_contribution_paise": 50000,
    })
    assert response.status_code == 201, response.text
    return response.json()


def _enrol_since(engine, person, month: date):
    with Session(engine) as db:
        sponsor = db.get(Prospect, uuid.UUID(person["id"]))
        sponsor.start_month = month
        rate = db.scalars(select(SponsorshipRate).where(
            SponsorshipRate.organization_id == sponsor.organization_id,
            SponsorshipRate.prospect_id == sponsor.id,
        )).one()
        rate.effective_month = month
        db.commit()


def _assigned(client, csrf, promoter, person):
    response = client.put(
        f"/v1/promoters/{promoter['id']}/sponsors/{person['id']}",
        headers={**csrf, "If-Match": str(person["version"])},
    )
    assert response.status_code == 200, response.text


def _view(client, promoter, kind=None, limit=20, offset=0):
    response = client.get(f"/v1/promoters/{promoter['id']}/sponsors", params={
        **({"kind": kind} if kind else {}),
        "limit": limit, "offset": offset,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_promoter_tabs_use_ist_live_status_and_keep_reads_side_effect_free(api, monkeypatch):
    client, csrf, engine = api
    promoter_response = client.post("/v1/promoters", headers=csrf, json={
        "full_name": "Boundary QA Promoter",
        "mobile_number": "+918701004201", "area_city": "Bengaluru",
    })
    assert promoter_response.status_code == 201, promoter_response.text
    promoter = promoter_response.json()
    overdue = _new_sponsor(
        client, csrf, name="A Unpaid Prospect", phone="+918701004211",
    )
    received = _new_sponsor(
        client, csrf, name="B Paid Sponsor", phone="+918701004212",
    )
    for person in (overdue, received):
        _enrol_since(engine, person, date(2026, 9, 1))
        _assigned(client, csrf, promoter, person)

    with Session(engine) as db:
        sponsor = db.get(Prospect, uuid.UUID(received["id"]))
        db.add(VerifiedCredit(
            organization_id=sponsor.organization_id, prospect_id=sponsor.id,
            period_month=date(2026, 10, 1), amount_paise=25000,
            source_type="bank_reconciled",
            source_key="synthetic-promoter-status-paid-2026-10",
            verified_at=datetime(2026, 10, 15, 8, tzinfo=UTC),
        ))
        db.commit()
        before_audit = db.scalar(select(func.count(AuditEvent.id)))
        versions = {p.id: p.version for p in db.scalars(select(Prospect)).all()}
        # Deliberately stale lifecycle cache for the paid sponsor.
        assert sponsor.lifecycle_status == "new"

    # 31 October 23:59 IST: only September is a fully missed month.
    monkeypatch.setattr(
        "app.prospects.utc_now",
        lambda: datetime(2026, 10, 31, 18, 29, tzinfo=UTC),
    )
    prospect_tab = _view(client, promoter, "prospects")
    sponsor_tab = _view(client, promoter, "sponsors")
    assert prospect_tab["total"] == 1
    assert prospect_tab["items"][0]["prospect_id"] == overdue["id"]
    assert prospect_tab["items"][0]["lifecycle_status"] == "new"
    assert sponsor_tab["total"] == 1
    assert sponsor_tab["items"][0]["prospect_id"] == received["id"]
    assert sponsor_tab["items"][0]["lifecycle_status"] == "active"

    # Exactly at midnight IST, both September and October are completed
    # unpaid months for the first record. It must move tabs automatically.
    monkeypatch.setattr(
        "app.prospects.utc_now",
        lambda: datetime(2026, 10, 31, 18, 30, tzinfo=UTC),
    )
    assert _view(client, promoter, "prospects")["total"] == 0
    page1 = _view(client, promoter, "sponsors", limit=1, offset=0)
    page2 = _view(client, promoter, "sponsors", limit=1, offset=1)
    assert page1["total"] == page2["total"] == 2
    assert {page1["items"][0]["prospect_id"], page2["items"][0]["prospect_id"]} == {
        overdue["id"], received["id"],
    }
    all_rows = _view(client, promoter)
    status = {x["prospect_id"]: x["lifecycle_status"] for x in all_rows["items"]}
    assert status == {overdue["id"]: "inactive", received["id"]: "active"}
    details = client.get("/v1/prospects/" + overdue["id"]).json()
    assert details["lifecycle_status"] == "inactive"

    # GET requests must never silently mutate the audited materialized state.
    with Session(engine) as db:
        assert {p.id: p.version for p in db.scalars(select(Prospect))} == versions
        assert db.scalar(select(func.count(AuditEvent.id))) == before_audit
        assert db.get(Prospect, uuid.UUID(overdue["id"])).lifecycle_status == "new"


def test_payment_reversal_projection_agrees_across_promoter_and_prospect(api, monkeypatch):
    client, csrf, engine = api
    promoter_response = client.post("/v1/promoters", headers=csrf, json={
        "full_name": "Reversal QA Promoter",
        "mobile_number": "+918701004202",
    })
    assert promoter_response.status_code == 201, promoter_response.text
    promoter = promoter_response.json()
    person = _new_sponsor(
        client, csrf, name="Reversal Sponsor", phone="+918701004213",
    )
    _enrol_since(engine, person, date(2026, 9, 1))
    _assigned(client, csrf, promoter, person)
    path = "/v1/prospects/" + person["id"]
    activation = activate_with_test_otp(client, csrf, client.get(path).json())
    assert activation.status_code == 200, activation.text
    simulated = datetime(2026, 10, 31, 18, 33, tzinfo=UTC)
    monkeypatch.setattr("app.prospects.utc_now", lambda: simulated)
    monkeypatch.setattr("app.collections.utc_now", lambda: simulated)
    monkeypatch.setattr("app.collections.ist_today", lambda now=None: date(2026, 11, 1))
    assert _view(client, promoter, "sponsors")["items"][0]["lifecycle_status"] == "inactive"

    recorded = client.post("/v1/collections", headers=csrf, json={
        "request_id": str(uuid.uuid4()), "prospect_id": person["id"],
        "period_month": "2026-11-01", "received_on": "2026-11-01",
        "amount_paise": 25000, "payment_method": "upi",
        "receipt_reference": "PROMOTER-QA-NOV-250",
        "funds_confirmed": True,
    })
    assert recorded.status_code == 201, recorded.text
    assert recorded.json()["sponsor_status"] == "active"
    assert _view(client, promoter, "sponsors")["items"][0]["lifecycle_status"] == "active"

    reversal = client.post(
        "/v1/collections/" + recorded.json()["id"] + "/reverse",
        headers=csrf,
        json={"request_id": str(uuid.uuid4()), "reason_code": "wrong_amount",
              "confirmation": "REVERSE"},
    )
    assert reversal.status_code == 201, reversal.text
    assert reversal.json()["sponsor_status"] == "inactive"
    assert _view(client, promoter, "sponsors")["items"][0]["lifecycle_status"] == "inactive"
    assert client.get(path).json()["lifecycle_status"] == "inactive"
