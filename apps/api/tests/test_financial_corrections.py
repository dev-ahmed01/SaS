"""Phase 08 financial corrections: append-only voids and net accounting integrity."""
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.accounting import effective_credits, ist_today, month_start, shift_month
from app.bootstrap_admin import provision_admin
from app.main import app
from app.models import (
    AdminUser,
    AuditEvent,
    Base,
    ManualCollection,
    ManualCollectionReversal,
    MessageOutbox,
    Organization,
    OrganizationSettings,
    Prospect,
    SponsorshipRate,
    VerifiedCredit,
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
            upi_match_secret="synthetic-independent-upi-hmac-key-for-tests"
        ),
    )
    with TestClient(app) as client:
        yield client, engine
    engine.dispose()


def login(client, email="admin@foundation.org",
          password="synthetic-long-admin-password"):
    response = client.post(
        "/v1/auth/login", json={"email":email, "password":password}
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token":client.get("/v1/auth/session").json()["csrf_token"]}


def sponsor(client, headers, phone="+919876543210", consent=True):
    response = client.post("/v1/prospects", headers=headers, json={
        "full_name":"Synthetic Reversal Sponsor",
        "mobile_number":phone, "area_city":"Bengaluru",
        "whatsapp_opt_in":consent,
        "monthly_contribution_paise":50000,
    })
    assert response.status_code == 201, response.text
    return response.json()


def pay(client, headers, prospect_id, reference="REVERSALREF001",
        amount_paise=50000):
    today=ist_today()
    response=client.post("/v1/collections",headers=headers,json={
        "request_id":str(uuid.uuid4()),
        "prospect_id":prospect_id,
        "period_month":month_start(today).isoformat(),
        "received_on":today.isoformat(),
        "amount_paise":amount_paise,
        "payment_method":"upi",
        "receipt_reference":reference,
        "funds_confirmed":True,
    })
    assert response.status_code==201,response.text
    return response.json()


def reverse(client, headers, collection_id, request_id=None,
            reason="wrong_amount", confirmation="REVERSE"):
    return client.post(
        "/v1/collections/"+collection_id+"/reverse",
        headers=headers,
        json={
            "request_id":str(request_id or uuid.uuid4()),
            "reason_code":reason,
            "confirmation":confirmation,
        },
    )


def test_reversal_restores_dues_and_suppresses_unsent_message(system):
    client, engine=system
    csrf=login(client)
    person=sponsor(client,csrf)
    receipt=pay(client,csrf,person["id"])
    assert receipt["sponsor_status"]=="active"
    assert client.get("/v1/accounting/overview").json()["verified_paise"]==50000

    response=reverse(client,csrf,receipt["id"])
    assert response.status_code==201,response.text
    result=response.json()
    assert result["reversed"] is True
    assert result["message_status"]=="suppressed"
    assert result["sponsor_status"]=="new"
    ledger=client.get("/v1/accounting/overview").json()
    assert ledger["due_paise"]==50000
    assert ledger["verified_paise"]==0
    assert ledger["outstanding_paise"]==50000
    assert ledger["fully_paid_sponsors"]==0
    collection=client.get("/v1/collections").json()["items"][0]
    assert collection["reversed"] is True
    assert collection["reversal_reason"]=="wrong_amount"
    assert collection["message_status"]=="suppressed"
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(VerifiedCredit))==1
        assert db.scalar(select(func.count()).select_from(ManualCollection))==1
        assert db.scalar(select(func.count()).select_from(ManualCollectionReversal))==1
        assert db.scalars(select(MessageOutbox)).one().suppress_reason=="collection_reversed"
        assert db.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action=="collection.manual_reversed"
            )
        )==1
        record=db.get(Prospect, uuid.UUID(person["id"]))
        assert record.lifecycle_status=="new"


def test_reversal_preserves_other_250_tier_collection_records(system):
    client, engine=system
    csrf=login(client)
    person=sponsor(client,csrf)
    first=pay(client,csrf,person["id"],"MULTIINSTALMENT001",25000)
    second=pay(client,csrf,person["id"],"MULTIINSTALMENT002",25000)
    before=client.get("/v1/accounting/overview").json()
    assert before["verified_paise"]==50000
    assert before["fully_paid_sponsors"]==1
    assert reverse(client,csrf,first["id"]).status_code==201
    balance=client.get("/v1/accounting/overview").json()
    assert balance["verified_paise"]==25000
    assert balance["outstanding_paise"]==25000
    assert balance["fully_paid_sponsors"]==0
    with Session(engine) as db:
        org_id=db.get(Prospect,uuid.UUID(person["id"])).organization_id
        credits=effective_credits(db,org_id,sponsor_id=uuid.UUID(person["id"]))
        assert len(credits)==1
        assert credits[0].amount_paise==25000
    assert reverse(client,csrf,second["id"]).status_code==201
    assert client.get("/v1/accounting/overview").json()["verified_paise"]==0


def test_reversal_requires_admin_csrf_literal_confirmation_and_one_void(system):
    client,engine=system
    csrf=login(client)
    person=sponsor(client,csrf)
    receipt=pay(client,csrf,person["id"])
    path="/v1/collections/"+receipt["id"]+"/reverse"
    assert client.post(path,json={
        "request_id":str(uuid.uuid4()),
        "reason_code":"wrong_sponsor","confirmation":"REVERSE",
    }).status_code==403
    for payload in [
        {"reason_code":"wrong_sponsor","confirmation":"reverse"},
        {"reason_code":"wrong_sponsor","confirmation":"YES"},
        {"reason_code":"not_a_reason","confirmation":"REVERSE"},
    ]:
        assert client.post(path,headers=csrf,json={
            "request_id":str(uuid.uuid4()),**payload,
        }).status_code==422
    key=uuid.uuid4()
    assert reverse(client,csrf,receipt["id"],key,"wrong_sponsor").status_code==201
    assert reverse(client,csrf,receipt["id"],key,"wrong_sponsor").status_code==200
    assert reverse(client,csrf,receipt["id"],key,"wrong_amount").status_code==409
    assert reverse(client,csrf,receipt["id"]).status_code==409
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ManualCollectionReversal))==1
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action=="collection.manual_reversed"
        ))==1


def test_reversal_works_after_sponsor_archived_without_unarchiving(system):
    client,engine=system
    csrf=login(client)
    person=sponsor(client,csrf)
    receipt=pay(client,csrf,person["id"])
    version=client.get("/v1/prospects/"+person["id"]).json()["version"]
    result=client.delete(
        "/v1/prospects/"+person["id"],
        headers={**csrf,"If-Match":str(version)},
    )
    assert result.status_code==204,result.text
    reversal=reverse(client,csrf,receipt["id"])
    assert reversal.status_code==201,reversal.text
    with Session(engine) as db:
        p=db.get(Prospect,uuid.UUID(person["id"]))
        assert p.archived_at is not None
        assert db.scalar(select(func.count()).select_from(ManualCollectionReversal))==1
    assert client.get("/v1/accounting/overview").json()["verified_paise"]==0


def test_cross_organization_record_and_reversal_are_inaccessible(system):
    client,engine=system
    csrf=login(client)
    person=sponsor(client,csrf)
    receipt=pay(client,csrf,person["id"])
    with Session(engine) as db:
        other=Organization(name="Other Synthetic Foundation")
        db.add(other)
        db.flush()
        db.add(AdminUser(
            organization_id=other.id,email="second@foundation.org",
            password_hash=hash_password("synthetic-secondary-password"),is_active=True,
        ))
        db.add(OrganizationSettings(
            organization_id=other.id,currency_code="INR",timezone="Asia/Kolkata",
            default_contribution_paise=50000,sponsor_reminder_day=5,
            promoter_reminder_day=20,inactivity_months=2,automation_enabled=False,
        ))
        db.commit()
    csrf2=login(client,"second@foundation.org","synthetic-secondary-password")
    assert client.post("/v1/collections/"+receipt["id"]+"/reverse",headers=csrf2,json={
        "request_id":str(uuid.uuid4()),"reason_code":"wrong_amount",
        "confirmation":"REVERSE",
    }).status_code==404
    assert client.get("/v1/collections").json()["total"]==0
    assert client.get("/v1/accounting/overview").json()["total_sponsors"]==0
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ManualCollectionReversal))==0


def test_prior_period_reversal_recomputes_current_ist_lifecycle(system,monkeypatch):
    client,engine=system
    csrf=login(client)
    person=sponsor(client,csrf)
    with Session(engine) as db:
        p=db.get(Prospect,uuid.UUID(person["id"]))
        older=shift_month(month_start(ist_today()),-2)
        p.start_month=older
        rate=db.scalars(select(SponsorshipRate).where(
            SponsorshipRate.prospect_id==p.id
        )).one()
        rate.effective_month=older
        db.commit()
    today=ist_today()
    # A sponsor with only current month paid remains active; voiding it
    # exposes two completed consecutive unpaid months.
    receipt=pay(client,csrf,person["id"])
    assert receipt["sponsor_status"]=="active"
    result=reverse(client,csrf,receipt["id"],reason="funds_not_received")
    assert result.status_code==201,result.text
    assert result.json()["sponsor_status"]=="inactive"
    summary=client.get("/v1/accounting/overview").json()
    assert summary["inactive_sponsors"]==1
    assert summary["period_month"]==month_start(today).isoformat()
