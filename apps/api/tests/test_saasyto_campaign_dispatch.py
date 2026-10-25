"""Contract tests for approval, unique claims, consent rechecks and sender gating."""
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from test_communication import activate_for_communication, create_campaign, login

from app.bootstrap_admin import provision_admin
from app.main import app
from app.models import Base, Prospect, SaasytoCampaignRecipient, SaasytoCampaignRun
from app.saasyto_client import Submission
from app.security import utc_now

RUNNER = "synthetic-saasyto-runner-secret-exactly-long-enough"


@pytest.fixture
def dispatch_system(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        provision_admin(
            db, email="office@foundation.org",
            password="synthetic-long-admin-password",
            organization_name="Emlen Foundation",
        )
    monkeypatch.setattr("app.auth.get_engine", lambda: engine)
    monkeypatch.setattr(
        "app.auth.get_settings", lambda: SimpleNamespace(
            auth_secret="synthetic-secure-auth-key-longer-than-thirty-two",
            app_env="test",
        ),
    )
    monkeypatch.setattr(
        "app.prospects.get_settings", lambda: SimpleNamespace(
            upi_match_secret="synthetic-unique-hmac-secret-for-communication-test",
        ),
    )
    with TestClient(app) as client:
        yield client, engine
    engine.dispose()


def _cfg(enabled=True, cutoff=None):
    return SimpleNamespace(
        saasyto_delivery_enabled=enabled,
        saasyto_sender_approved=True,
        saasyto_enable_after=cutoff or utc_now()-timedelta(minutes=5),
        saasyto_runner_secret=SecretStr(RUNNER),
    )


def _person(client, csrf, suffix):
    result = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Saasyto Test " + suffix,
        "mobile_number": "+91989900" + suffix,
        "area_city": "Bengaluru",
        "whatsapp_opt_in": True,
    })
    assert result.status_code == 201, result.text
    return activate_for_communication(client, csrf, result.json())


def _consent(client, csrf, person, decision):
    body = {
        "recipient_kind": "prospect", "recipient_id": person["id"],
        "channel": "whatsapp", "decision": decision,
        "source": "synthetic consent ledger event",
    }
    if decision == "opted_in":
        body["evidence_reference"] = "test-consent-reference"
    response = client.post("/v1/communication/consent-events", headers=csrf, json=body)
    assert response.status_code == 201, response.text


def _approved(client, csrf, name):
    campaign = create_campaign(client, csrf, title=name)
    assert campaign.status_code == 201, campaign.text
    cid = campaign.json()["id"]
    base = "/v1/communication/campaigns/" + cid
    prepared = client.post(base + "/preparations", headers=csrf, json={
        "request_id": str(uuid.uuid4()), "simulation_only": True,
    })
    assert prepared.status_code == 201, prepared.text
    ready = prepared.json()
    assert ready["eligible_count"] > 0
    approval = client.post(base + "/saasyto", headers=csrf, json={
        "preparation_id": ready["id"], "expected_eligible": ready["eligible_count"],
        "confirm_send": True,
    })
    assert approval.status_code == 201, approval.text
    return cid, approval.json()


def test_no_approval_or_claim_when_provider_off(dispatch_system, monkeypatch):
    client, engine = dispatch_system
    csrf = login(client)
    person = _person(client, csrf, "1001")
    _consent(client, csrf, person, "opted_in")
    campaign = create_campaign(client, csrf).json()
    base = "/v1/communication/campaigns/" + campaign["id"]
    preflight = client.post(base + "/preparations", headers=csrf, json={
        "request_id": str(uuid.uuid4()), "simulation_only": True,
    }).json()
    monkeypatch.setattr("app.saasyto_campaigns.get_settings", lambda: _cfg(False))
    denied = client.post(base + "/saasyto", headers=csrf, json={
        "preparation_id": preflight["id"], "expected_eligible": 1,
        "confirm_send": True,
    })
    assert denied.status_code == 503
    assert client.post("/internal/saasyto/dispatch", headers={
        "X-Saasyto-Runner-Token": RUNNER,
    }).status_code == 503
    with Session(engine) as db:
        assert db.scalar(select(func.count(SaasytoCampaignRun.id))) == 0


def test_approval_is_explicit_idempotent_and_runner_rechecks_opt_out(dispatch_system, monkeypatch):
    client, engine = dispatch_system
    csrf = login(client)
    person = _person(client, csrf, "1002")
    _consent(client, csrf, person, "opted_in")
    monkeypatch.setattr("app.saasyto_campaigns.get_settings", lambda: _cfg())
    cid, approved = _approved(client, csrf, "Opt-out stops approved delivery")
    assert approved["queued"] == 1
    assert client.post("/v1/communication/campaigns/"+cid+"/saasyto",
        headers=csrf, json={
            "preparation_id": str(uuid.uuid4()), "expected_eligible": 1,
            "confirm_send": True,
        }).status_code == 409
    assert client.get("/v1/communication/campaigns/"+cid+"/saasyto").json()["queued"] == 1
    _consent(client, csrf, person, "opted_out")
    monkeypatch.setattr("app.saasyto_campaigns.send_text", lambda *_a, **_kw:
                        (_ for _ in ()).throw(AssertionError("must never send opted out")))
    run = client.post("/internal/saasyto/dispatch", headers={
        "X-Saasyto-Runner-Token": RUNNER,
    })
    assert run.status_code == 200, run.text
    assert run.json()["suppressed"] == 1
    assert client.post("/internal/saasyto/dispatch", headers={
        "X-Saasyto-Runner-Token": RUNNER,
    }).json() == {}
    summary = client.get("/v1/communication/campaigns/"+cid+"/saasyto").json()
    assert summary["status"] == "completed"
    assert summary["suppressed_after_approval"] == 1
    with Session(engine) as db:
        assert db.scalar(select(func.count(SaasytoCampaignRecipient.id))) == 1


def test_one_attempt_unknown_outcome_is_never_replayed(dispatch_system, monkeypatch):
    client, _ = dispatch_system
    csrf = login(client)
    person = _person(client, csrf, "1003")
    _consent(client, csrf, person, "opted_in")
    monkeypatch.setattr("app.saasyto_campaigns.get_settings", lambda: _cfg())
    cid, _ = _approved(client, csrf, "Uncertain send case")
    hits = []
    def fake_send(_cfg, *, phone, message):
        hits.append((phone, message))
        return Submission("unknown")
    monkeypatch.setattr("app.saasyto_campaigns.send_text", fake_send)
    headers = {"X-Saasyto-Runner-Token": RUNNER}
    assert client.post("/internal/saasyto/dispatch", headers=headers).json()["unknown"] == 1
    assert client.post("/internal/saasyto/dispatch", headers=headers).json() == {}
    assert len(hits) == 1
    assert hits[0][0] == "+919899001003"
    assert "Saasyto Test 1003" in hits[0][1]
    result = client.get("/v1/communication/campaigns/"+cid+"/saasyto").json()
    assert result["unknown"] == 1 and result["status"] == "completed"


def test_cross_tenant_auth_and_cancellation(dispatch_system, monkeypatch):
    client, _ = dispatch_system
    csrf = login(client)
    monkeypatch.setattr("app.saasyto_campaigns.get_settings", lambda: _cfg())
    assert client.get("/v1/communication/campaigns/"+str(uuid.uuid4())+"/saasyto"
                      ).status_code == 404
    assert client.post("/internal/saasyto/dispatch", headers={
        "X-Saasyto-Runner-Token": "wrong",
    }).status_code == 401
    _consent(client, csrf, _person(client, csrf, "1004"), "opted_in")
    monkeypatch.setattr("app.saasyto_campaigns.get_settings", lambda: _cfg())
    cid, _ = _approved(client, csrf, "Cancel queued campaign")
    route = "/v1/communication/campaigns/"+cid+"/saasyto"
    assert client.post(route+"/cancel", json={}).status_code == 403
    stopped = client.post(route+"/cancel", headers=csrf, json={})
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "cancelled"
    assert stopped.json()["suppressed_after_approval"] == 1
    assert client.post("/internal/saasyto/dispatch", headers={
        "X-Saasyto-Runner-Token": RUNNER,
    }).json() == {}


def test_approval_requires_fresh_review_and_new_campaign(dispatch_system, monkeypatch):
    client, _ = dispatch_system
    csrf = login(client)
    person = _person(client, csrf, "1005")
    _consent(client, csrf, person, "opted_in")
    monkeypatch.setattr("app.saasyto_campaigns.get_settings", lambda:
                        _cfg(cutoff=utc_now()+timedelta(minutes=1)))
    row = create_campaign(client, csrf).json()
    base = "/v1/communication/campaigns/"+row["id"]
    preflight = client.post(base+"/preparations", headers=csrf, json={
        "request_id": str(uuid.uuid4()), "simulation_only": True,
    }).json()
    response = client.post(base+"/saasyto", headers=csrf, json={
        "preparation_id": preflight["id"], "expected_eligible": 1,
        "confirm_send": True,
    })
    assert response.status_code == 409


def test_campaign_results_include_excluded_contacts_and_mask_numbers(dispatch_system):
    client, _ = dispatch_system
    csrf = login(client)
    allowed = _person(client, csrf, "1101")
    missing_general_consent = _person(client, csrf, "1102")
    _consent(client, csrf, allowed, "opted_in")
    campaign = create_campaign(client, csrf, title="Recipient results review")
    assert campaign.status_code == 201
    cid = campaign.json()["id"]
    base = "/v1/communication/campaigns/" + cid
    check = client.post(base + "/preparations", headers=csrf, json={
        "request_id": str(uuid.uuid4()), "simulation_only": True,
    })
    assert check.status_code == 201
    assert check.json()["eligible_count"] == 1
    assert check.json()["suppressed_count"] == 1

    detail = client.get(base + "/results")
    assert detail.status_code == 200, detail.text
    assert detail.headers["cache-control"] == "no-store"
    record = detail.json()
    assert record["summary"]["run_status"] == "not_approved"
    assert record["summary"]["submitted_unverified"] == 0
    assert record["summary"]["delivered"] is None
    assert record["summary"]["read"] is None
    assert record["excluded_reasons"] == {"no_general_consent": 1}
    assert len(record["excluded_recipients"]) == 1
    excluded = record["excluded_recipients"][0]
    assert excluded["recipient_id"] == missing_general_consent["id"]
    assert excluded["name"] == missing_general_consent["full_name"]
    assert excluded["phone_masked"] == "•••• 1102"
    assert excluded["status"] == "excluded"
    assert "+919899001102" not in detail.text
    all_summaries = client.get("/v1/communication/campaigns/results").json()
    assert all_summaries[0]["run_status"] == "not_approved"
    assert all_summaries[0]["excluded_in_review"] == 1
    assert client.get("/v1/communication/campaigns/"+str(uuid.uuid4())+
                      "/results").status_code == 404


def test_campaign_results_distinguish_submission_rejection_unknown_and_no_webhook(
    dispatch_system, monkeypatch,
):
    client, _ = dispatch_system
    csrf = login(client)
    person = _person(client, csrf, "1103")
    _consent(client, csrf, person, "opted_in")
    monkeypatch.setattr("app.saasyto_campaigns.get_settings", lambda: _cfg())
    cid, _ = _approved(client, csrf, "Provider rejected test")
    monkeypatch.setattr("app.saasyto_campaigns.send_text",
                        lambda *_a, **_k: Submission("rejected"))
    headers = {"X-Saasyto-Runner-Token": RUNNER}
    assert client.post("/internal/saasyto/dispatch", headers=headers).json()[
        "rejected"
    ] == 1
    detail = client.get("/v1/communication/campaigns/"+cid+"/results").json()
    assert detail["summary"]["rejected"] == 1
    assert detail["summary"]["submitted_unverified"] == 0
    assert detail["summary"]["delivered"] is None
    assert detail["summary"]["read"] is None
    assert detail["recipients"][0]["status"] == "rejected"
    assert detail["recipients"][0]["phone_masked"] == "•••• 1103"
    assert "test-consent-reference" not in str(detail)
    row = next(x for x in client.get("/v1/communication/campaigns/results").json()
               if x["campaign_id"] == cid)
    assert row["rejected"] == 1 and row["read"] is None

    cid2, _ = _approved(client, csrf, "Provider unknown test")
    monkeypatch.setattr("app.saasyto_campaigns.send_text",
                        lambda *_a, **_k: Submission("unknown"))
    assert client.post("/internal/saasyto/dispatch", headers=headers).json()[
        "unknown"
    ] == 1
    unknown = client.get("/v1/communication/campaigns/"+cid2+"/results").json()
    assert unknown["summary"]["unknown"] == 1
    assert unknown["summary"]["rejected"] == 0
    assert unknown["summary"]["delivered"] is None
    assert unknown["recipients"][0]["status"] == "unknown"
    # The read-only results endpoint never resets the queue or retries.
    assert client.post("/internal/saasyto/dispatch", headers=headers).json() == {}


def test_production_approval_rejects_same_count_swapped_database_contacts(
    dispatch_system, monkeypatch,
):
    """One existing Active contact replaced by another must require fresh review."""
    client, engine = dispatch_system
    csrf = login(client)
    first = _person(client, csrf, "2101")
    second = _person(client, csrf, "2102")
    _consent(client, csrf, first, "opted_in")
    _consent(client, csrf, second, "opted_in")
    with Session(engine) as db:
        person = db.get(Prospect, uuid.UUID(second["id"]))
        person.crm_stage = "inactive"
        person.version += 1
        db.commit()
    monkeypatch.setattr("app.saasyto_campaigns.get_settings", lambda: _cfg())
    row = create_campaign(client, csrf, title="Existing and newly registered sponsors")
    assert row.status_code == 201, row.text
    base = "/v1/communication/campaigns/" + row.json()["id"]
    check = client.post(base + "/preparations", headers=csrf, json={
        "request_id": str(uuid.uuid4()), "simulation_only": True,
    })
    assert check.status_code == 201
    assert check.json()["eligible_count"] == 1
    assert client.get(base + "/saasyto/readiness").json()["ready"] is True
    with Session(engine) as db:
        original = db.get(Prospect, uuid.UUID(first["id"]))
        replacement = db.get(Prospect, uuid.UUID(second["id"]))
        original.crm_stage = "inactive"
        replacement.crm_stage = "active"
        original.version += 1
        replacement.version += 1
        db.commit()
    # Active/consented count remains unchanged while actual audience differs.
    readiness = client.get(base + "/saasyto/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["eligible_count"] == 1
    assert readiness.json()["code"] == "audience_changed"
    rejected = client.post(base + "/saasyto", headers=csrf, json={
        "preparation_id": check.json()["id"],
        "expected_eligible": 1, "confirm_send": True,
    })
    assert rejected.status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count(SaasytoCampaignRun.id))) == 0
    fresh = client.post(base + "/preparations", headers=csrf, json={
        "request_id": str(uuid.uuid4()), "simulation_only": True,
    })
    assert fresh.status_code == 201 and fresh.json()["eligible_count"] == 1
    approved = client.post(base + "/saasyto", headers=csrf, json={
        "preparation_id": fresh.json()["id"],
        "expected_eligible": 1, "confirm_send": True,
    })
    assert approved.status_code == 201, approved.text
    with Session(engine) as db:
        recipients = db.scalars(select(SaasytoCampaignRecipient)).all()
        assert len(recipients) == 1
        assert recipients[0].recipient_id == uuid.UUID(second["id"])


def test_newly_registered_nonseeded_contact_can_enter_production_queue(
    dispatch_system, monkeypatch,
):
    """Real registration, not demo seed, supplies the WhatsApp recipient."""
    client, engine = dispatch_system
    csrf = login(client)
    registered = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "New registered supporter",
        "mobile_number": "+919899002211",
        "area_city": "Bengaluru",
        "whatsapp_opt_in": False,
    })
    assert registered.status_code == 201, registered.text
    person = registered.json()
    assert person["crm_stage"] == "inactive"
    _consent(client, csrf, person, "opted_in")
    # Active intentionally excludes brand-new CRM records; All includes them.
    active = create_campaign(client, csrf, title="Active only", segment="active")
    assert active.status_code == 201
    check_active = client.post(
        "/v1/communication/campaigns/" + active.json()["id"] + "/preparations",
        headers=csrf, json={"request_id": str(uuid.uuid4()), "simulation_only": True},
    )
    assert check_active.status_code == 201
    assert check_active.json()["eligible_count"] == 0
    broad = create_campaign(client, csrf, title="Welcome new signup", segment="all")
    assert broad.status_code == 201, broad.text
    base = "/v1/communication/campaigns/" + broad.json()["id"]
    preflight = client.post(base + "/preparations", headers=csrf, json={
        "request_id": str(uuid.uuid4()), "simulation_only": True,
    })
    assert preflight.status_code == 201 and preflight.json()["eligible_count"] == 1
    monkeypatch.setattr("app.saasyto_campaigns.get_settings", lambda: _cfg())
    approval = client.post(base + "/saasyto", headers=csrf, json={
        "preparation_id": preflight.json()["id"], "expected_eligible": 1,
        "confirm_send": True,
    })
    assert approval.status_code == 201, approval.text
    hits = []
    monkeypatch.setattr("app.saasyto_campaigns.send_text",
                        lambda cfg, *, phone, message:
                        (hits.append(phone), Submission("accepted_unverified"))[1])
    attempt = client.post("/internal/saasyto/dispatch", headers={
        "X-Saasyto-Runner-Token": RUNNER,
    })
    assert attempt.status_code == 200
    assert attempt.json()["accepted_unverified"] == 1
    assert hits == ["+919899002211"]
    with Session(engine) as db:
        recipient = db.scalars(select(SaasytoCampaignRecipient)).one()
        assert recipient.recipient_id == uuid.UUID(person["id"])
        assert recipient.status == "accepted_unverified"


def test_production_batch_uses_multiple_registered_contacts_and_honors_late_optout(
    dispatch_system, monkeypatch,
):
    """Approving a multi-contact batch never bypasses last-minute STOP."""
    client, engine = dispatch_system
    csrf = login(client)
    people = [_person(client, csrf, suffix) for suffix in ("2201", "2202", "2203")]
    for person in people:
        _consent(client, csrf, person, "opted_in")
    monkeypatch.setattr("app.saasyto_campaigns.get_settings", lambda: _cfg())
    cid, approved = _approved(client, csrf, "Approved real CRM group")
    assert approved["eligible_count"] == approved["queued"] == 3
    _consent(client, csrf, people[1], "opted_out")

    hits = []

    def fake_send(_settings, *, phone, message):
        hits.append((phone, message))
        return Submission("accepted_unverified")

    monkeypatch.setattr("app.saasyto_campaigns.send_text", fake_send)
    headers = {"X-Saasyto-Runner-Token": RUNNER}
    result = client.post("/internal/saasyto/dispatch", headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["accepted_unverified"] == 2
    assert result.json()["suppressed"] == 1
    assert sorted(phone for phone, _message in hits) == [
        "+919899002201", "+919899002203",
    ]
    assert client.post("/internal/saasyto/dispatch", headers=headers).json() == {}
    summary = client.get("/v1/communication/campaigns/" + cid + "/saasyto")
    assert summary.status_code == 200
    assert summary.json()["status"] == "completed"
    assert summary.json()["accepted_unverified"] == 2
    assert summary.json()["suppressed_after_approval"] == 1
    with Session(engine) as db:
        assert db.scalar(select(func.count(SaasytoCampaignRecipient.id))) == 3
