"""Saasyto-only 5th/20th IST automations; no legacy provider calls."""

import uuid
from datetime import UTC, date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from test_reminders import (
    OCT_5,
    OCT_20,
    assign,
    login,
    promoter,
    set_start,
    sponsor,
)

from app.bootstrap_admin import provision_admin
from app.main import app
from app.models import (
    Base,
    CommunicationCampaign,
    MessageDispatch,
    OrganizationSettings,
    Prospect,
    ReminderBatch,
    SaasytoCampaignRecipient,
    SaasytoCampaignRun,
)
from app.saasyto_client import Submission
from app.saasyto_monthly_reminders import (
    _request_id,
    expire_overdue_reminders,
    live_monthly_message,
    prepare_due_saasyto_reminders,
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


def config(when=OCT_5, *, enabled=True, disclose=True):
    return SimpleNamespace(
        saasyto_auto_reminders_enabled=enabled,
        saasyto_delivery_enabled=True,
        saasyto_sender_approved=True,
        saasyto_worker_enabled=True,
        saasyto_enable_after=when.astimezone(UTC) - timedelta(minutes=10),
        saasyto_runner_secret=SecretStr("synthetic-saasyto-only-worker-secret-123456"),
        promoter_disclosure_approved=disclose,
        saasyto_local_test_enabled=False,
        saasyto_campaign_batch_size=10,
        saasyto_campaign_max_per_minute=10,
        saasyto_campaign_min_interval_seconds=90,
    )


def enable_automation(engine, day=5, promoter_day=20):
    with Session(engine) as db:
        settings = db.scalars(select(OrganizationSettings)).one()
        settings.automation_enabled = True
        settings.sponsor_reminder_day = day
        settings.promoter_reminder_day = promoter_day
        db.commit()


def test_legacy_pabbly_endpoints_are_unmounted(system):
    client, _engine = system
    assert client.post("/internal/messaging/dispatch").status_code == 404
    assert client.post("/internal/messaging/callback").status_code == 404
    assert client.get("/v1/messaging/status").status_code == 404


def test_standing_monthly_approval_off_by_default(system):
    client, engine = system
    csrf = login(client)
    person = sponsor(client, csrf, 3001)
    set_start(engine, person["id"], date(2026, 10, 1))
    enable_automation(engine)
    with Session(engine) as db:
        assert prepare_due_saasyto_reminders(
            db, config(enabled=False), OCT_5.astimezone(UTC)
        ) == 0
        assert db.scalar(select(func.count()).select_from(SaasytoCampaignRun)) == 0


def test_sponsor_reminder_is_queued_once_and_rechecks_live_balance(
    system, monkeypatch,
):
    client, engine = system
    csrf = login(client)
    person = sponsor(client, csrf, 3002)
    set_start(engine, person["id"], date(2026, 10, 1))
    enable_automation(engine)
    cfg = config()
    now = OCT_5.astimezone(UTC)
    monkeypatch.setattr("app.saasyto_campaigns.get_settings", lambda: cfg)
    with Session(engine) as db:
        assert prepare_due_saasyto_reminders(db, cfg, now) == 1
        assert prepare_due_saasyto_reminders(db, cfg, now) == 0
        campaign = db.scalars(select(CommunicationCampaign).where(
            CommunicationCampaign.provider_template_id == "sas_auto_sponsor_v1",
        )).one()
        item = db.scalars(select(SaasytoCampaignRecipient)).one()
        sponsor_record = db.get(Prospect, uuid.UUID(person["id"]))
        assert campaign.request_id == _request_id(
            sponsor_record.organization_id, "sponsor", date(2026, 10, 1),
        )
        assert item.status == "queued"
        body = live_monthly_message(db, campaign, sponsor_record, now, cfg)
        assert "₹500.00" in body
        assert "Sponsor 3002" in body
        assert live_monthly_message(
            db, campaign, sponsor_record, now + timedelta(days=1), cfg,
        ) is None
        assert live_monthly_message(
            db, campaign, sponsor_record, now, config(enabled=False),
        ) is None
        # Before actual network submission, a newly paid bill must suppress.
        from app.models import VerifiedCredit

        db.add(VerifiedCredit(
            organization_id=sponsor_record.organization_id,
            prospect_id=sponsor_record.id,
            period_month=date(2026, 10, 1),
            amount_paise=50000,
            source_type="bank_reconciled",
            source_key="synthetic-paid-after-schedule",
            verified_at=now,
        ))
        db.commit()
        assert live_monthly_message(db, campaign, sponsor_record, now, cfg) is None


def test_promoter_combines_multiple_sponsors_and_disclosure_gate(system):
    client, engine = system
    csrf = login(client)
    a = sponsor(client, csrf, 3003)
    b = sponsor(client, csrf, 3004)
    agent = promoter(client, csrf, 3005)
    set_start(engine, a["id"], date(2026, 10, 1))
    set_start(engine, b["id"], date(2026, 10, 1))
    assign(engine, agent["id"], a["id"])
    assign(engine, agent["id"], b["id"])
    enable_automation(engine)
    now = OCT_20.astimezone(UTC)
    cfg = config(OCT_20)
    with Session(engine) as db:
        assert prepare_due_saasyto_reminders(db, cfg, now) == 1
        run = db.scalars(select(SaasytoCampaignRun)).one()
        assert run.eligible_count == 1
        campaign = db.get(CommunicationCampaign, run.campaign_id)
        from app.models import Promoter

        promoter_record = db.get(Promoter, uuid.UUID(agent["id"]))
        body = live_monthly_message(db, campaign, promoter_record, now, cfg)
        assert "Sponsor 3003" in body
        assert "Sponsor 3004" in body
        assert "₹1,000.00" in body
        assert live_monthly_message(
            db, campaign, promoter_record, now,
            config(OCT_20, disclose=False),
        ) is None


def test_prepared_legacy_batch_blocks_duplicate_saasyto_send(system):
    client, engine = system
    csrf = login(client)
    person = sponsor(client, csrf, 3006)
    set_start(engine, person["id"], date(2026, 10, 1))
    enable_automation(engine)
    with Session(engine) as db:
        settings = db.scalars(select(OrganizationSettings)).one()
        db.add(ReminderBatch(
            organization_id=settings.organization_id,
            request_id=uuid.uuid4(),
            kind="sponsor",
            period_month=date(2026, 10, 1),
            scheduled_on=date(2026, 10, 5),
            recipient_count=0,
        ))
        db.commit()
        assert prepare_due_saasyto_reminders(
            db, config(), OCT_5.astimezone(UTC),
        ) == 0
        assert db.scalar(select(func.count()).select_from(CommunicationCampaign)) == 0
        assert db.scalar(select(func.count()).select_from(MessageDispatch)) == 0



def test_overdue_queue_is_suppressed_and_not_reattempted(system):
    client, engine = system
    csrf = login(client)
    person = sponsor(client, csrf, 3007)
    set_start(engine, person["id"], date(2026, 10, 1))
    enable_automation(engine)
    with Session(engine) as db:
        assert prepare_due_saasyto_reminders(
            db, config(), OCT_5.astimezone(UTC),
        ) == 1
        assert expire_overdue_reminders(
            db, OCT_5.astimezone(UTC) + timedelta(days=1),
        ) == 1
        item = db.scalars(select(SaasytoCampaignRecipient)).one()
        run = db.scalars(select(SaasytoCampaignRun)).one()
        assert item.status == "suppressed"
        assert item.reason == "reminder_day_expired"
        assert item.claimed_at is None
        assert run.status == "completed"
        assert expire_overdue_reminders(
            db, OCT_5.astimezone(UTC) + timedelta(days=1),
        ) == 0



@pytest.mark.parametrize("when,kind", [
    (OCT_5, "sponsor"),
    (OCT_20, "promoter"),
])
def test_actual_cron_http_entrypoint_creates_and_sends_one_monthly_message(
    system, monkeypatch, when, kind,
):
    """Walk Admin contact -> standing policy -> HTTP cron -> provider adapter.

    The Saasyto transport is mocked; this is NOT an external WhatsApp send.
    A later cron tick cannot replay the same recipient.
    """
    client, engine = system
    csrf = login(client)
    owner = sponsor(client, csrf, 3091)
    set_start(engine, owner["id"], date(2026, 10, 1))
    if kind == "promoter":
        agent = promoter(client, csrf, 3092)
        assign(engine, agent["id"], owner["id"])
    enable_automation(engine)
    now = when.astimezone(UTC)
    cfg = config(when)
    cfg.app_env = "production"
    token = cfg.saasyto_runner_secret.get_secret_value()
    monkeypatch.setattr("app.saasyto_campaigns.get_settings", lambda: cfg)
    monkeypatch.setattr("app.saasyto_campaigns.utc_now", lambda: now)
    monkeypatch.setattr("app.saasyto_monthly_reminders.utc_now", lambda: now)
    outgoing = []

    def fake_send(_cfg, *, phone, message):
        outgoing.append((phone, message))
        return Submission("accepted_unverified")

    monkeypatch.setattr("app.saasyto_campaigns.send_text", fake_send)
    path = "/internal/saasyto/dispatch"
    assert client.post(path).status_code == 401
    result = client.post(path, headers={
        "X-Saasyto-Runner-Token": token,
    })
    assert result.status_code == 200, result.text
    assert result.json().get("accepted_unverified") == 1
    assert len(outgoing) == 1
    assert "Sponsor a Salah" in outgoing[0][1]
    if kind == "promoter":
        assert "Sponsor 3091" in outgoing[0][1]
    else:
        assert "₹500.00" in outgoing[0][1]
    with Session(engine) as db:
        row = db.scalars(select(CommunicationCampaign)).one()
        assert row.provider_template_id == (
            "sas_auto_sponsor_v1" if kind == "sponsor"
            else "sas_auto_promoter_v1"
        )
        attempt = db.scalars(select(SaasytoCampaignRecipient)).one()
        assert attempt.status == "accepted_unverified"
    again = client.post(path, headers={"X-Saasyto-Runner-Token": token})
    assert again.status_code == 200
    assert len(outgoing) == 1


def test_manual_reminder_cannot_reserve_month_when_saasyto_auto_is_on(
    system, monkeypatch,
):
    client, engine = system
    csrf = login(client)
    enable_automation(engine)
    cfg = config()
    cfg.app_env = "production"
    monkeypatch.setattr("app.reminders.get_settings", lambda: cfg)
    monkeypatch.setattr(
        "app.reminders.utc_now", lambda: OCT_5.astimezone(UTC),
    )
    manual = client.post("/v1/reminders/prepare", headers=csrf, json={
        "kind": "sponsor", "request_id": str(uuid.uuid4()),
    })
    assert manual.status_code == 409, manual.text
    assert "scheduled through Saasyto" in manual.json()["detail"]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ReminderBatch)) == 0



def test_production_http_cron_respects_worker_kill_switch(system, monkeypatch):
    client, engine = system
    csrf = login(client)
    person = sponsor(client, csrf, 3093)
    set_start(engine, person["id"], date(2026, 10, 1))
    enable_automation(engine)
    cfg = config()
    cfg.app_env = "production"
    cfg.saasyto_worker_enabled = False
    monkeypatch.setattr("app.saasyto_campaigns.get_settings", lambda: cfg)
    monkeypatch.setattr(
        "app.saasyto_campaigns.utc_now", lambda: OCT_5.astimezone(UTC),
    )
    token = cfg.saasyto_runner_secret.get_secret_value()
    denied = client.post("/internal/saasyto/dispatch", headers={
        "X-Saasyto-Runner-Token": token,
    })
    assert denied.status_code == 503, denied.text
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(CommunicationCampaign)) == 0
        assert db.scalar(select(func.count()).select_from(SaasytoCampaignRun)) == 0
