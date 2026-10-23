"""Phase 10 reminder preparation: live IST eligibility, privacy and idempotency."""
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.bootstrap_admin import provision_admin
from app.main import app
from app.models import (
    AdminUser,
    AuditEvent,
    Base,
    MessageDispatch,
    MessageOutbox,
    Organization,
    OrganizationSettings,
    PromoterAssignment,
    Prospect,
    ReminderBatch,
    ReminderIntent,
    SponsorshipRate,
    VerifiedCredit,
)
from app.reminders import current_intent_eligible
from app.security import hash_password

OCT_5 = datetime(2026, 10, 5, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
OCT_20 = datetime(2026, 10, 20, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


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
            db, email="office@foundation.org",
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


def set_today(monkeypatch, value: datetime):
    monkeypatch.setattr("app.reminders.utc_now", lambda: value.astimezone(UTC))


def login(client, email="office@foundation.org",
          password="synthetic-long-admin-password"):
    response=client.post("/v1/auth/login", json={"email":email,"password":password})
    assert response.status_code==200, response.text
    return {"X-CSRF-Token":client.get("/v1/auth/session").json()["csrf_token"]}


def activate_for_financial_flow(client, csrf, record):
    """Older payment/reminder tests explicitly activate enrolled CRM prospects."""
    response = client.post("/v1/prospects/" + record["id"] + "/stage", headers=csrf, json={
        "version": record["version"], "stage": "active",
        "note": "Synthetic outreach completed for financial flow test",
    })
    assert response.status_code == 200, response.text
    return response.json()


def sponsor(client, csrf, index, consent=True):
    response=client.post("/v1/prospects", headers=csrf, json={
        "full_name":f"Sponsor {index:04d}",
        "mobile_number":f"+91987654{index:04d}",
        "area_city":"Bengaluru",
        "whatsapp_opt_in":consent,
        "monthly_contribution_paise":50000,
    })
    assert response.status_code==201,response.text
    return activate_for_financial_flow(client, csrf, response.json())


def promoter(client, csrf, index, consent=True, active=True):
    response=client.post("/v1/promoters", headers=csrf, json={
        "full_name":f"Promoter {index:04d}",
        "mobile_number":f"+91991122{index:04d}",
        "area_city":"Bengaluru",
        "whatsapp_opt_in":consent,
    })
    assert response.status_code==201,response.text
    result=response.json()
    if not active:
        response=client.patch("/v1/promoters/"+result["id"], headers=csrf,
                              json={"version":1,"is_active":False})
        assert response.status_code==200,response.text
    return result


def set_start(engine, identifier, start):
    with Session(engine) as db:
        record=db.get(Prospect,uuid.UUID(identifier))
        record.start_month=start
        rate=db.scalars(select(SponsorshipRate).where(
            SponsorshipRate.prospect_id==record.id,
        )).one()
        rate.effective_month=start
        db.commit()


def payment(engine, identifier, period, reference, amount=50000, at=OCT_5):
    with Session(engine) as db:
        prospect=db.get(Prospect,uuid.UUID(identifier))
        db.add(VerifiedCredit(
            organization_id=prospect.organization_id,
            prospect_id=prospect.id,period_month=period,
            amount_paise=amount,source_type="bank_reconciled",
            source_key=reference,verified_at=at.astimezone(UTC),
        ))
        db.commit()


def assign(engine, promoter_id, sponsor_id):
    with Session(engine) as db:
        target=db.get(Prospect,uuid.UUID(sponsor_id))
        db.add(PromoterAssignment(
            organization_id=target.organization_id,
            promoter_id=uuid.UUID(promoter_id),
            prospect_id=target.id,
        ))
        db.commit()


def prepare(client, csrf, kind, request=None):
    return client.post("/v1/reminders/prepare",headers=csrf,json={
        "kind":kind,"request_id":str(request or uuid.uuid4()),
    })


def test_guest_and_csrf_protected_no_delivery(system,monkeypatch):
    client,engine=system
    assert client.get("/v1/reminders/preview?kind=sponsor").status_code==401
    assert client.get("/v1/reminders/batches").status_code==401
    assert client.post("/v1/reminders/prepare",json={}).status_code==401
    csrf=login(client)
    sponsor(client,csrf,1)
    set_today(monkeypatch,OCT_5)
    response=client.get("/v1/reminders/preview?kind=sponsor")
    assert response.status_code==200,response.text
    assert response.json()["eligible_recipients"]==1
    assert response.json()["is_due_today"] is True
    assert client.post("/v1/reminders/prepare",json={
        "kind":"sponsor","request_id":str(uuid.uuid4()),
    }).status_code==403
    assert prepare(client,csrf,"sponsor").status_code==201
    assert client.get("/v1/reminders/batches?limit=55").status_code==422
    assert client.get("/v1/reminders/preview?kind=email").status_code==422
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(MessageOutbox))==0
        assert db.scalar(select(func.count()).select_from(ReminderBatch))==1


def test_sponsor_preview_excludes_paid_inactive_archived_and_no_consent(
    system,monkeypatch,
):
    client,engine=system
    csrf=login(client)
    set_today(monkeypatch,OCT_5)
    new=sponsor(client,csrf,10)
    active=sponsor(client,csrf,11)
    inactive=sponsor(client,csrf,12)
    paid=sponsor(client,csrf,13)
    opted_out=sponsor(client,csrf,14,consent=False)
    archived=sponsor(client,csrf,15)
    set_start(engine,new["id"],date(2026,10,1))
    for item in (active,inactive,paid,opted_out,archived):
        set_start(engine,item["id"],date(2026,8,1))
    payment(engine,active["id"],date(2026,9,1),"active-september")
    payment(engine,paid["id"],date(2026,10,1),"paid-october")
    payment(engine,paid["id"],date(2026,9,1),"paid-september")
    with Session(engine) as db:
        archived_row=db.get(Prospect,uuid.UUID(archived["id"]))
        archived_row.archived_at=OCT_5.astimezone(UTC)
        db.commit()
    preview=client.get("/v1/reminders/preview?kind=sponsor")
    assert preview.status_code==200,preview.text
    result=preview.json()
    ids={item["recipient_id"] for item in result["recipients"]}
    assert ids=={new["id"],active["id"]}
    assert result["eligible_recipients"]==2
    assert result["unpaid_sponsors"]==2
    assert result["total_outstanding_paise"]==100000
    assert "WhatsApp" in result["notice"]
    assert result["currency"]=="INR"
    assert result["timezone"]=="Asia/Kolkata"


def test_250_receipt_retains_outstanding_reminder_without_falsely_fully_paid(
    system,monkeypatch,
):
    client,engine=system
    csrf=login(client)
    set_today(monkeypatch,OCT_5)
    person=sponsor(client,csrf,20)
    set_start(engine,person["id"],date(2026,10,1))
    payment(engine,person["id"],date(2026,10,1),"tier250-current",amount=25000)
    result=client.get("/v1/reminders/preview?kind=sponsor").json()
    assert result["eligible_recipients"]==1
    assert result["total_outstanding_paise"]==25000
    assert result["recipients"][0]["outstanding_paise"]==25000


def test_two_missed_months_suppress_even_when_materialized_status_stale(
    system,monkeypatch,
):
    client,engine=system
    csrf=login(client)
    set_today(monkeypatch,OCT_5)
    person=sponsor(client,csrf,30)
    set_start(engine,person["id"],date(2026,8,1))
    with Session(engine) as db:
        target=db.get(Prospect,uuid.UUID(person["id"]))
        target.lifecycle_status="active"
        db.commit()
    result=client.get("/v1/reminders/preview?kind=sponsor").json()
    assert result["eligible_recipients"]==0


def test_promoter_preview_one_group_with_only_active_unpaid_assignments(
    system,monkeypatch,
):
    client,engine=system
    csrf=login(client)
    set_today(monkeypatch,OCT_20)
    first=promoter(client,csrf,1)
    no_consent=promoter(client,csrf,2,consent=False)
    inactive_promoter=promoter(client,csrf,3,active=False)
    people=[sponsor(client,csrf,i,consent=i!=43) for i in range(40,45)]
    for entry in people:
        set_start(engine,entry["id"],date(2026,10,1))
    assign(engine,first["id"],people[0]["id"])
    assign(engine,first["id"],people[1]["id"])
    assign(engine,first["id"],people[2]["id"])
    assign(engine,no_consent["id"],people[3]["id"])
    assign(engine,inactive_promoter["id"],people[4]["id"])
    payment(engine,people[2]["id"],date(2026,10,1),"fully-settled",at=OCT_20)
    preview=client.get("/v1/reminders/preview?kind=promoter")
    assert preview.status_code==200,preview.text
    result=preview.json()
    assert result["eligible_recipients"]==1
    assert result["unpaid_sponsors"]==2
    assert result["total_outstanding_paise"]==100000
    person=result["recipients"][0]
    assert person["recipient_id"]==first["id"]
    assert person["sponsor_count"]==2
    assert {x["prospect_id"] for x in person["unpaid_sponsors"]}=={
        people[0]["id"],people[1]["id"],
    }
    prepared=prepare(client,csrf,"promoter")
    assert prepared.status_code==201,prepared.text
    assert prepared.json()["recipient_count"]==1
    with Session(engine) as db:
        intents=db.scalars(select(ReminderIntent)).all()
        assert len(intents)==1
        assert intents[0].promoter_id==uuid.UUID(first["id"])
        assert intents[0].prospect_id is None
        assert intents[0].sponsor_count==2
        assert len(intents[0].sponsor_snapshot)==2
        assert intents[0].status=="prepared"
        assert db.scalar(select(func.count()).select_from(MessageOutbox))==0


def test_only_configured_ist_day_may_prepare_no_catchup(
    system,monkeypatch,
):
    client,engine=system
    csrf=login(client)
    person=sponsor(client,csrf,50)
    set_start(engine,person["id"],date(2026,10,1))
    set_today(monkeypatch,OCT_5.replace(day=6))
    result=client.get("/v1/reminders/preview?kind=sponsor").json()
    assert result["is_due_today"] is False
    assert result["scheduled_on"]=="2026-10-05"
    assert prepare(client,csrf,"sponsor").status_code==409
    with Session(engine) as db:
        org=db.scalars(select(OrganizationSettings)).one()
        org.sponsor_reminder_day=6
        db.commit()
    updated=client.get("/v1/reminders/preview?kind=sponsor").json()
    assert updated["is_due_today"] is True
    assert updated["scheduled_on"]=="2026-10-06"
    assert prepare(client,csrf,"sponsor").status_code==201


def test_prepare_idempotent_duplicate_and_audit_and_no_delivery(
    system,monkeypatch,
):
    client,engine=system
    csrf=login(client)
    set_today(monkeypatch,OCT_5)
    sponsor(client,csrf,60)
    request=uuid.uuid4()
    response=prepare(client,csrf,"sponsor",request)
    assert response.status_code==201,response.text
    same=prepare(client,csrf,"sponsor",request)
    assert same.status_code==200,same.text
    assert same.json()["id"]==response.json()["id"]
    assert same.json()["delivered_count"]==0
    assert prepare(client,csrf,"sponsor").status_code==409
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ReminderIntent))==1
        assert db.scalar(select(func.count()).select_from(ReminderBatch))==1
        audit=db.scalars(select(AuditEvent).where(
            AuditEvent.action=="reminder.batch_prepared",
        )).all()
        assert len(audit)==1
        assert audit[0].after_data["delivery_enabled"] is False


def test_prep_intent_rechecks_current_consent_and_paid_state(
    system,monkeypatch,
):
    client,engine=system
    csrf=login(client)
    set_today(monkeypatch,OCT_5)
    person=sponsor(client,csrf,70)
    batch=prepare(client,csrf,"sponsor")
    assert batch.status_code==201,batch.text
    with Session(engine) as db:
        admin=db.scalars(select(AdminUser)).one()
        intent=db.scalars(select(ReminderIntent)).one()
        assert current_intent_eligible(db,admin,intent,OCT_5.astimezone(UTC)) is True
    payment(engine,person["id"],date(2026,10,1),"paid-after-preview")
    with Session(engine) as db:
        admin=db.scalars(select(AdminUser)).one()
        intent=db.scalars(select(ReminderIntent)).one()
        assert current_intent_eligible(db,admin,intent,OCT_5.astimezone(UTC)) is False
        target=db.get(Prospect,uuid.UUID(person["id"]))
        target.whatsapp_opt_in=False
        db.commit()
    with Session(engine) as db:
        admin=db.scalars(select(AdminUser)).one()
        intent=db.scalars(select(ReminderIntent)).one()
        assert current_intent_eligible(db,admin,intent,OCT_5.astimezone(UTC)) is False


def test_promoter_pre_dispatch_rechecks_current_assignments(
    system,monkeypatch,
):
    client,engine=system
    csrf=login(client)
    set_today(monkeypatch,OCT_20)
    person=sponsor(client,csrf,80)
    liaison=promoter(client,csrf,7)
    assign(engine,liaison["id"],person["id"])
    result=prepare(client,csrf,"promoter")
    assert result.status_code==201,result.text
    with Session(engine) as db:
        admin=db.scalars(select(AdminUser)).one()
        intent=db.scalars(select(ReminderIntent)).one()
        assert current_intent_eligible(db,admin,intent,OCT_20.astimezone(UTC)) is True
        assigned=db.scalars(select(PromoterAssignment)).one()
        assigned.ended_at=OCT_20.astimezone(UTC)
        db.commit()
    with Session(engine) as db:
        admin=db.scalars(select(AdminUser)).one()
        intent=db.scalars(select(ReminderIntent)).one()
        assert current_intent_eligible(db,admin,intent,OCT_20.astimezone(UTC)) is False


def test_empty_reminder_batch_has_no_intents_and_still_idempotent(
    system,monkeypatch,
):
    client,engine=system
    csrf=login(client)
    set_today(monkeypatch,OCT_5)
    result=prepare(client,csrf,"sponsor")
    assert result.status_code==201,result.text
    assert result.json()["recipient_count"]==0
    assert result.json()["delivered_count"]==0
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ReminderBatch))==1
        assert db.scalar(select(func.count()).select_from(ReminderIntent))==0


def test_capacity_guard_fails_closed_without_partial_preparation(
    system,monkeypatch,
):
    client,engine=system
    csrf=login(client)
    set_today(monkeypatch,OCT_5)
    for index in range(90,93):
        sponsor(client,csrf,index)
    monkeypatch.setattr("app.reminders.MAX_SPONSORS",2)
    response=prepare(client,csrf,"sponsor")
    assert response.status_code==409,response.text
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ReminderBatch))==0
        assert db.scalar(select(func.count()).select_from(ReminderIntent))==0


def test_tenant_isolation_and_forged_batch_request_id(
    system,monkeypatch,
):
    client,engine=system
    csrf=login(client)
    set_today(monkeypatch,OCT_5)
    sponsor(client,csrf,99)
    original=prepare(client,csrf,"sponsor")
    assert original.status_code==201
    with Session(engine) as db:
        second=Organization(name="Other Synthetic Foundation")
        db.add(second)
        db.flush()
        db.add(AdminUser(
            organization_id=second.id,email="second@foundation.org",
            password_hash=hash_password("synthetic-secondary-password"),
            is_active=True,
        ))
        db.add(OrganizationSettings(
            organization_id=second.id,currency_code="INR",timezone="Asia/Kolkata",
            default_contribution_paise=50000,sponsor_reminder_day=5,
            promoter_reminder_day=20,inactivity_months=2,automation_enabled=False,
        ))
        db.commit()
    other=login(client,"second@foundation.org","synthetic-secondary-password")
    assert client.get("/v1/reminders/preview?kind=sponsor").json()["eligible_recipients"]==0
    assert client.get("/v1/reminders/batches").json()["total"]==0
    assert prepare(client,other,"sponsor").status_code==201
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ReminderBatch))==2


def test_ist_midnight_sponsor_day_uses_kolkata_not_utc(
    system,monkeypatch,
):
    client,engine=system
    csrf=login(client)
    person=sponsor(client,csrf,120)
    set_start(engine,person["id"],date(2026,10,1))
    set_today(monkeypatch,datetime(2026,10,4,18,29,tzinfo=UTC))
    before=client.get("/v1/reminders/preview?kind=sponsor").json()
    assert before["today_ist"]=="2026-10-04"
    assert before["is_due_today"] is False
    set_today(monkeypatch,datetime(2026,10,4,18,30,tzinfo=UTC))
    after=client.get("/v1/reminders/preview?kind=sponsor").json()
    assert after["today_ist"]=="2026-10-05"
    assert after["is_due_today"] is True


def test_pre_dispatch_blocks_catchup_after_configured_date(system, monkeypatch):
    client, engine = system
    csrf = login(client)
    set_today(monkeypatch, OCT_5)
    sponsor(client, csrf, 160)
    prepared = prepare(client, csrf, "sponsor")
    assert prepared.status_code == 201, prepared.text
    with Session(engine) as db:
        admin = db.scalars(select(AdminUser)).one()
        intent = db.scalars(select(ReminderIntent)).one()
        assert current_intent_eligible(db, admin, intent, OCT_5.astimezone(UTC))
        assert not current_intent_eligible(
            db, admin, intent, OCT_5.replace(day=6).astimezone(UTC),
        )
        db.get(OrganizationSettings, admin.organization_id).sponsor_reminder_day = 6
        db.commit()
    with Session(engine) as db:
        admin = db.scalars(select(AdminUser)).one()
        intent = db.scalars(select(ReminderIntent)).one()
        assert not current_intent_eligible(
            db, admin, intent, OCT_5.replace(day=6).astimezone(UTC),
        )


def test_exact_reminder_request_replay_after_ist_midnight(system, monkeypatch):
    client, engine = system
    csrf = login(client)
    set_today(monkeypatch, OCT_5)
    sponsor(client, csrf, 217)
    request = uuid.uuid4()
    created = prepare(client, csrf, "sponsor", request)
    assert created.status_code == 201, created.text
    set_today(monkeypatch, OCT_5.replace(day=6))
    replay = prepare(client, csrf, "sponsor", request)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == created.json()["id"]
    assert prepare(client, csrf, "sponsor").status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ReminderBatch)) == 1


def test_reminder_history_reflects_confirmed_deliveries(system, monkeypatch):
    client, engine = system
    csrf = login(client)
    set_today(monkeypatch, OCT_5)
    sponsor(client, csrf, 218)
    sponsor(client, csrf, 219)
    result = prepare(client, csrf, "sponsor")
    assert result.status_code == 201, result.text
    assert result.json()["recipient_count"] == 2
    assert result.json()["status"] == "prepared"
    with Session(engine) as db:
        first, second = db.scalars(
            select(ReminderIntent).order_by(ReminderIntent.prospect_id)
        ).all()
        second_org, second_id = second.organization_id, second.id
        db.add(MessageDispatch(
            organization_id=first.organization_id,
            reminder_intent_id=first.id, status="delivered",
            category="sponsor_reminder",
        ))
        db.commit()
    partial = client.get("/v1/reminders/batches").json()["items"][0]
    assert partial["status"] == "partially_delivered"
    assert partial["delivered_count"] == 1
    with Session(engine) as db:
        db.add(MessageDispatch(
            organization_id=second_org,
            reminder_intent_id=second_id, status="delivered",
            category="sponsor_reminder",
        ))
        db.commit()
    done = client.get("/v1/reminders/batches").json()["items"][0]
    assert done["status"] == "delivered"
    assert done["delivered_count"] == 2
