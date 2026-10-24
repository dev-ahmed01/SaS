"""Contract tests for approval, unique claims, consent rechecks and sender gating."""
import uuid
from datetime import timedelta
from types import SimpleNamespace

from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_communication import activate_for_communication, create_campaign, login

from app.models import SaasytoCampaignRecipient, SaasytoCampaignRun
from app.saasyto_client import Submission
from app.security import utc_now

pytest_plugins = ("test_communication",)
RUNNER = "synthetic-saasyto-runner-secret-exactly-long-enough"


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


def test_no_approval_or_claim_when_provider_off(system, monkeypatch):
    client, engine = system
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


def test_approval_is_explicit_idempotent_and_runner_rechecks_opt_out(system, monkeypatch):
    client, engine = system
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


def test_one_attempt_unknown_outcome_is_never_replayed(system, monkeypatch):
    client, _ = system
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


def test_cross_tenant_auth_and_cancellation(system, monkeypatch):
    client, _ = system
    csrf = login(client)
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


def test_approval_requires_fresh_review_and_new_campaign(system, monkeypatch):
    client, _ = system
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
