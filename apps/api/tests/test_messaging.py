"""Phase 11: closed-by-default delivery, signed receipts and live eligibility."""
import hashlib
import hmac
import json
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from activation_helper import activate_with_test_otp
from app.accounting import ist_today, month_start
from app.bootstrap_admin import provision_admin
from app.main import app
from app.models import (
    Base,
    MessageDispatch,
    Organization,
    OrganizationSettings,
    Promoter,
    PromoterAssignment,
    Prospect,
    VerifiedCredit,
)
from app.security import utc_now

RUNNER="synthetic-runner-key-more-than-32-characters"
CALLBACK="synthetic-callback-key-more-than-32-characters"
HMAC_SECRET="synthetic-webhook-hmac-key-more-than-32-characters"


@pytest.fixture
def system(monkeypatch):
    engine=create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread":False},poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        provision_admin(
            db,email="admin@foundation.org",
            password="synthetic-long-admin-password",
            organization_name="Emlen Foundation",
            amount_paise=50000,
        )
    monkeypatch.setattr("app.auth.get_engine",lambda:engine)
    monkeypatch.setattr(
        "app.auth.get_settings",
        lambda:SimpleNamespace(
            auth_secret="synthetic-auth-secret-more-than-thirty-two-characters",
            app_env="test",
        ),
    )
    monkeypatch.setattr(
        "app.prospects.get_settings",
        lambda:SimpleNamespace(
            upi_match_secret="synthetic-independent-upi-hmac-key-for-tests",
        ),
    )
    with TestClient(app) as client:
        yield client,engine
    engine.dispose()


def config(enabled=True,cutoff=None,disclosure=False):
    return SimpleNamespace(
        messaging_delivery_enabled=enabled,
        messaging_sender_approved=True,
        messaging_enable_after=cutoff or utc_now()-timedelta(hours=1),
        messaging_runner_secret=RUNNER,
        messaging_callback_secret=CALLBACK,
        pabbly_signature_secret=HMAC_SECRET,
        pabbly_webhook_url="https://connect.pabbly.com/workflow/sendwebhookdata/synthetic",
        whatsapp_template_payment="sas_payment_recorded",
        whatsapp_template_sponsor="sas_unpaid_sponsor",
        whatsapp_template_promoter="sas_promoter_summary",
        promoter_disclosure_approved=disclosure,
    )


def login(client):
    r=client.post("/v1/auth/login",json={
        "email":"admin@foundation.org",
        "password":"synthetic-long-admin-password",
    })
    assert r.status_code==200,r.text
    return {"X-CSRF-Token":client.get("/v1/auth/session").json()["csrf_token"]}


def activate_for_financial_flow(client, csrf, record):
    """Older payment/reminder tests explicitly activate enrolled CRM prospects."""
    response = activate_with_test_otp(client, csrf, record)
    assert response.status_code == 200, response.text
    return response.json()


def sponsor(client,csrf,number=1,consent=True):
    r=client.post("/v1/prospects",headers=csrf,json={
        "full_name":f"Sponsor {number:02}",
        "mobile_number":f"+9198765400{number:02}",
        "area_city":"Bengaluru",
        "monthly_contribution_paise":50000,
        "whatsapp_opt_in":consent,
    })
    assert r.status_code==201,r.text
    return activate_for_financial_flow(client, csrf, r.json())


def collection(client,csrf,prospect,ref="TESTMSG001"):
    today=ist_today()
    r=client.post("/v1/collections",headers=csrf,json={
        "request_id":str(uuid.uuid4()),
        "prospect_id":prospect["id"],
        "period_month":month_start(today).isoformat(),
        "received_on":today.isoformat(),
        "amount_paise":50000,
        "payment_method":"upi",
        "receipt_reference":ref,
        "funds_confirmed":True,
    })
    assert r.status_code==201,r.text
    return r.json()


def enable_org(engine,sponsor_reminder=False,promoter_reminder=False):
    with Session(engine) as db:
        row=db.scalars(select(OrganizationSettings)).one()
        row.automation_enabled=True
        # Keep the two independent schedules disjoint in tests; around the
        # 5th/20th IST a default reminder day can otherwise accidentally run.
        today=ist_today().day
        other=1 if today!=1 else 2
        row.sponsor_reminder_day=today if sponsor_reminder else other
        row.promoter_reminder_day=today if promoter_reminder else other
        db.commit()


def send(client):
    return client.post(
        "/internal/messaging/dispatch",
        headers={"X-Delivery-Runner-Token":RUNNER},
    )


def test_no_delivery_without_explicit_global_enable(system,monkeypatch):
    client,engine=system
    csrf=login(client)
    candidate=sponsor(client,csrf)
    collection(client,csrf,candidate)
    enable_org(engine)
    monkeypatch.setattr("app.messaging.get_settings",lambda:config(enabled=False))
    assert client.get("/v1/messaging/status").json()["delivery_enabled"] is False
    assert send(client).status_code==503
    assert client.post("/internal/messaging/dispatch").status_code==401
    with Session(engine) as db:
        assert db.scalars(select(MessageDispatch)).all()==[]


def test_consent_gated_outbox_provider_acceptance_and_signed_receipt(
    system,monkeypatch,
):
    client,engine=system
    csrf=login(client)
    candidate=sponsor(client,csrf)
    collection(client,csrf,candidate)
    enable_org(engine)
    monkeypatch.setattr("app.messaging.get_settings",lambda:config())
    sent=[]
    def fake_post(url,**kwargs):
        assert url.startswith("https://connect.pabbly.com/")
        body=kwargs["content"]
        signature=kwargs["headers"]["X-SaS-Signature"]
        expected="sha256="+hmac.new(HMAC_SECRET.encode(),body,hashlib.sha256).hexdigest()
        assert signature==expected
        sent.append(json.loads(body))
        return SimpleNamespace(status_code=200)
    monkeypatch.setattr("app.messaging.httpx.post",fake_post)
    r=send(client)
    assert r.status_code==200,r.text
    assert r.json()["attempted"]==1
    assert r.json()["accepted"]==1
    assert len(sent)==1
    assert sent[0]["template"]=="sas_payment_recorded"
    assert sent[0]["recipient_phone"]=="+919876540001"
    assert "TESTMSG001" not in json.dumps(sent[0])
    assert send(client).json()["attempted"]==0
    status=client.get("/v1/messaging/status").json()
    assert status["accepted_by_provider"]==1
    assert status["delivered_confirmed"]==0
    # Accepted is neither awaiting first dispatch nor actually delivered.
    assert status["awaiting_confirmation_intents"]==0
    assert client.get("/v1/dashboard/overview").json()[
        "acknowledgments_awaiting_setup"
    ] == 0
    with Session(engine) as db:
        record=db.scalars(select(MessageDispatch)).one()
        identifier=str(record.id)
        assert record.status=="accepted"
    callback={
        "event_id":"PABBLYDELIVERY00001",
        "dispatch_id":identifier,
        "provider_message_id":"wamid.synthetic.001",
        "status":"delivered",
    }
    body=json.dumps(callback,separators=(",",":")).encode()
    assert client.post("/internal/messaging/callback",content=body).status_code==401
    token="sha256="+hmac.new(CALLBACK.encode(),body,hashlib.sha256).hexdigest()
    valid=client.post("/internal/messaging/callback",content=body,headers={
        "X-SaS-Callback-Signature":token,
    })
    assert valid.status_code==200,valid.text
    assert valid.json()["status"]=="recorded"
    repeat=client.post("/internal/messaging/callback",content=body,headers={
        "X-SaS-Callback-Signature":token,
    })
    assert repeat.status_code==200
    assert repeat.json()["status"]=="already_recorded"
    assert client.get("/v1/messaging/status").json()["delivered_confirmed"]==1


def test_opt_out_and_reversed_collections_cannot_send(system,monkeypatch):
    client,engine=system
    csrf=login(client)
    eligible=sponsor(client,csrf,1)
    opted_out=sponsor(client,csrf,2,consent=False)
    first=collection(client,csrf,eligible,"TESTMSGREV001")
    collection(client,csrf,opted_out,"TESTMSGOPT002")
    r=client.post("/v1/collections/"+first["id"]+"/reverse",headers=csrf,json={
        "request_id":str(uuid.uuid4()),
        "reason_code":"funds_not_received","confirmation":"REVERSE",
    })
    assert r.status_code==201,r.text
    enable_org(engine)
    monkeypatch.setattr("app.messaging.get_settings",lambda:config())
    calls=[]
    monkeypatch.setattr("app.messaging.httpx.post",lambda *args,**kwargs:calls.append(1))
    result=send(client)
    assert result.status_code==200,result.text
    assert result.json()["attempted"]==0
    assert calls==[]


def test_old_confirmation_backlog_never_released(system,monkeypatch):
    client,engine=system
    csrf=login(client)
    person=sponsor(client,csrf)
    collection(client,csrf,person)
    enable_org(engine)
    future=utc_now()+timedelta(seconds=2)
    monkeypatch.setattr("app.messaging.get_settings",lambda:config(cutoff=future))
    assert send(client).status_code==409
    monkeypatch.setattr("app.messaging.utc_now",lambda:future+timedelta(minutes=1))
    assert send(client).json()["attempted"]==0
    with Session(engine) as db:
        assert db.scalars(select(MessageDispatch)).all()==[]


def test_prepared_unpaid_reminder_revalidates_and_skips_after_payment(
    system,monkeypatch,
):
    client,engine=system
    csrf=login(client)
    person=sponsor(client,csrf)
    enable_org(engine,sponsor_reminder=True)
    r=client.post("/v1/reminders/prepare",headers=csrf,json={
        "kind":"sponsor","request_id":str(uuid.uuid4()),
    })
    assert r.status_code==201,r.text
    with Session(engine) as db:
        record=db.get(Prospect,uuid.UUID(person["id"]))
        db.add(VerifiedCredit(
            organization_id=record.organization_id,
            prospect_id=record.id,
            period_month=month_start(ist_today()),
            amount_paise=50000,
            source_type="bank_reconciled",
            source_key="synthetic-completed-after-prepare",
            verified_at=utc_now(),
        ))
        db.commit()
    monkeypatch.setattr("app.messaging.get_settings",lambda:config())
    calls=[]
    monkeypatch.setattr("app.messaging.httpx.post",lambda *a,**k:calls.append(1))
    result=send(client)
    assert result.status_code==200,result.text
    assert result.json()["cancelled"]==1
    assert calls==[]
    with Session(engine) as db:
        assert db.scalars(select(MessageDispatch)).one().status=="cancelled"


def test_promoter_disclosure_requires_separate_approval(system,monkeypatch):
    client,engine=system
    csrf=login(client)
    person=sponsor(client,csrf,5)
    enable_org(engine,promoter_reminder=True)
    with Session(engine) as db:
        prospect=db.get(Prospect,uuid.UUID(person["id"]))
        promoter=Promoter(
            organization_id=prospect.organization_id,
            full_name="Promoter Guardian",
            mobile_number="+919911220099",
            area_city="Bengaluru",
            whatsapp_opt_in=True,is_active=True,version=1,
        )
        db.add(promoter)
        db.flush()
        db.add(PromoterAssignment(
            organization_id=prospect.organization_id,
            promoter_id=promoter.id,prospect_id=prospect.id,
        ))
        db.commit()
    r=client.post("/v1/reminders/prepare",headers=csrf,json={
        "kind":"promoter","request_id":str(uuid.uuid4()),
    })
    assert r.status_code==201,r.text
    assert r.json()["recipient_count"]==1
    monkeypatch.setattr("app.messaging.get_settings",lambda:config(disclosure=False))
    calls=[]
    monkeypatch.setattr("app.messaging.httpx.post",lambda *a,**k:calls.append(1))
    result=send(client)
    assert result.status_code==200,result.text
    assert result.json()["cancelled"]==1
    assert calls==[]


def test_timeouts_are_unknown_and_never_retried(system,monkeypatch):
    client,engine=system
    csrf=login(client)
    person=sponsor(client,csrf)
    collection(client,csrf,person)
    enable_org(engine)
    monkeypatch.setattr("app.messaging.get_settings",lambda:config())
    def fail(*_args,**_kwargs):
        raise __import__("httpx").ReadTimeout("unknown provider state")
    monkeypatch.setattr("app.messaging.httpx.post",fail)
    result=send(client)
    assert result.status_code==200,result.text
    assert result.json()["unknown"]==1
    assert send(client).json()["attempted"]==0
    with Session(engine) as db:
        assert db.scalars(select(MessageDispatch)).one().status=="unknown"


def test_worker_auto_prepares_one_unpaid_sponsor_batch_only_on_due_day(
    system,monkeypatch,
):
    client,engine=system
    csrf=login(client)
    sponsor(client,csrf,7)
    enable_org(engine,sponsor_reminder=True)
    monkeypatch.setattr("app.messaging.get_settings",lambda:config())
    transmitted=[]
    def capture(_url,**kwargs):
        transmitted.append(json.loads(kwargs["content"]))
        return SimpleNamespace(status_code=200)
    monkeypatch.setattr("app.messaging.httpx.post",capture)
    result=send(client)
    assert result.status_code==200,result.text
    assert result.json()["accepted"]==1
    assert len(transmitted)==1
    assert transmitted[0]["template"]=="sas_unpaid_sponsor"
    assert transmitted[0]["recipient_phone"]=="+919876540007"
    history=client.get("/v1/reminders/batches").json()
    assert history["total"]==1
    assert history["items"][0]["kind"]=="sponsor"
    assert history["items"][0]["recipient_count"]==1
    assert send(client).json()["attempted"]==0
    assert client.get("/v1/reminders/batches").json()["total"]==1


def test_auto_promoter_followup_is_one_consolidated_message(
    system,monkeypatch,
):
    client,engine=system
    csrf=login(client)
    first=sponsor(client,csrf,8)
    second=sponsor(client,csrf,9)
    enable_org(engine,promoter_reminder=True)
    with Session(engine) as db:
        persons=[
            db.get(Prospect,uuid.UUID(first["id"])),
            db.get(Prospect,uuid.UUID(second["id"])),
        ]
        messenger=Promoter(
            organization_id=persons[0].organization_id,
            full_name="Synthetic Coordinator",
            mobile_number="+919911224400",area_city="Bengaluru",
            whatsapp_opt_in=True,is_active=True,version=1,
        )
        db.add(messenger)
        db.flush()
        for person in persons:
            db.add(PromoterAssignment(
                organization_id=person.organization_id,
                promoter_id=messenger.id,prospect_id=person.id,
            ))
        db.commit()
    monkeypatch.setattr("app.messaging.get_settings",
                        lambda:config(disclosure=True))
    transmitted=[]
    def capture(_url,**kwargs):
        transmitted.append(json.loads(kwargs["content"]))
        return SimpleNamespace(status_code=200)
    monkeypatch.setattr("app.messaging.httpx.post",capture)
    result=send(client)
    assert result.status_code==200,result.text
    assert result.json()["accepted"]==1
    assert len(transmitted)==1
    msg=transmitted[0]
    assert msg["template"]=="sas_promoter_summary"
    assert msg["variables"]["sponsor_count"]=="2"
    assert "Sponsor 08" in msg["variables"]["sponsor_summary"]
    assert "Sponsor 09" in msg["variables"]["sponsor_summary"]
    assert send(client).json()["attempted"]==0


def test_more_than_twenty_enabled_organizations_do_not_block_confirmations(
    system, monkeypatch,
):
    """A large tenant count must not return 409 before even selecting outbox."""
    client, engine = system
    csrf = login(client)
    record = sponsor(client, csrf)
    collection(client, csrf, record, ref="LARGEORGS001")
    enable_org(engine)
    not_today = 1 if ist_today().day != 1 else 2
    with Session(engine) as db:
        for index in range(20):
            other = Organization(name=f"Synthetic Foundation {index}")
            db.add(other)
            db.flush()
            db.add(OrganizationSettings(
                organization_id=other.id, currency_code="INR",
                timezone="Asia/Kolkata", default_contribution_paise=50000,
                sponsor_reminder_day=not_today,
                promoter_reminder_day=not_today,
                inactivity_months=2, automation_enabled=True,
            ))
        db.commit()
    monkeypatch.setattr("app.messaging.get_settings", lambda: config())
    calls = []
    def fake_post(url, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=200)
    monkeypatch.setattr("app.messaging.httpx.post", fake_post)
    outcome = send(client)
    assert outcome.status_code == 200, outcome.text
    assert outcome.json()["accepted"] == 1
    assert len(calls) == 1
    assert send(client).json()["attempted"] == 0


def test_messaging_status_respects_future_activation_date(system, monkeypatch):
    client, engine = system
    login(client)
    enable_org(engine)
    monkeypatch.setattr(
        "app.messaging.get_settings",
        lambda: config(cutoff=utc_now() + timedelta(days=1)),
    )
    status = client.get("/v1/messaging/status")
    assert status.status_code == 200, status.text
    assert status.json()["delivery_enabled"] is True
    assert status.json()["operationally_enabled"] is False
