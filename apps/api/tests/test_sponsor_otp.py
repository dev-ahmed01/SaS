"""Sponsor OTP: bounded challenge, tenant binding, no delivery claims or consent changes."""
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CommunicationConsentEvent, ProspectStageTransition, SponsorOtpChallenge
from app.saasyto_client import Submission
from app.sponsor_otp import _deliver

pytest_plugins = ("test_crm_review_2026_10",)
SECRET = "test-only-sponsor-otp-secret-that-is-long-enough"


def _create(client, csrf, suffix, phone):
    response = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "OTP Test " + suffix, "mobile_number": phone, "area_city": "Bengaluru",
    })
    assert response.status_code == 201, response.text
    return response.json()


def _enable(monkeypatch, delivered):
    monkeypatch.setattr("app.sponsor_otp.get_settings", lambda: SimpleNamespace(
        otp_delivery_enabled=True, otp_secret=SECRET,
    ))
    monkeypatch.setattr(
        "app.sponsor_otp._deliver",
        lambda _cfg, phone, code: delivered.append((phone, code)),
    )


def test_default_off_never_sends(api, monkeypatch):
    monkeypatch.setattr("app.sponsor_otp.get_settings", lambda: SimpleNamespace(
        otp_delivery_enabled=False, otp_secret=None,
    ))
    client, csrf, engine = api
    person = _create(client, csrf, "Disabled", "+918100000001")
    status = client.get("/v1/prospects/" + person["id"] + "/otp/status")
    assert status.status_code == 200
    assert status.json()["delivery_enabled"] is False
    response = client.post("/v1/prospects/" + person["id"] + "/otp/request", headers=csrf)
    assert response.status_code == 503
    with Session(engine) as db:
        assert db.scalars(select(SponsorOtpChallenge)).all() == []


def test_success_and_replay_without_crm_or_consent_side_effects(api, monkeypatch):
    client, csrf, engine = api
    sent = []
    _enable(monkeypatch, sent)
    person = _create(client, csrf, "Valid", "+918100000002")
    url = "/v1/prospects/" + person["id"] + "/otp"
    forbidden = client.post(url + "/request")
    assert forbidden.status_code in (401, 403)
    requested = client.post(url + "/request", headers=csrf)
    assert requested.status_code == 200, requested.text
    challenge = requested.json()
    assert challenge["status"] == "accepted_by_provider"
    assert "code" not in challenge
    assert len(sent) == 1
    assert sent[0][0] == person["mobile_number"]
    assert len(sent[0][1]) == 6
    with Session(engine) as db:
        record = db.get(SponsorOtpChallenge, uuid.UUID(challenge["challenge_id"]))
        assert record is not None
        assert record.code_digest != sent[0][1]
        assert person["mobile_number"] not in repr(record.code_digest)
    other = _create(client, csrf, "Unrelated", "+918100000003")
    wrong_person = client.post(
        "/v1/prospects/" + other["id"] + "/otp/verify", headers=csrf, json={
            "challenge_id": challenge["challenge_id"], "code": sent[0][1],
        },
    )
    assert wrong_person.status_code == 400
    wrong = client.post(url + "/verify", headers=csrf, json={
        "challenge_id": challenge["challenge_id"], "code": "000000"
        if sent[0][1] != "000000" else "999999",
    })
    assert wrong.status_code == 400
    valid = client.post(url + "/verify", headers=csrf, json={
        "challenge_id": challenge["challenge_id"], "code": sent[0][1],
    })
    assert valid.status_code == 200, valid.text
    assert valid.json()["status"] == "verified"
    replay = client.post(url + "/verify", headers=csrf, json={
        "challenge_id": challenge["challenge_id"], "code": sent[0][1],
    })
    assert replay.status_code == 400
    current = client.get("/v1/prospects/" + person["id"]).json()
    assert current["whatsapp_opt_in"] is False
    assert current["crm_stage"] == "inactive"
    assert current["lifecycle_status"] == "new"
    state = client.get(url + "/status").json()
    assert state["verified"] is True and state["verified_at"] is not None
    changed = client.patch("/v1/prospects/" + person["id"], headers=csrf, json={
        "version": current["version"], "mobile_number": "+918100000004",
        "whatsapp_number": "+918100000004",
    })
    assert changed.status_code == 200, changed.text
    assert client.get(url + "/status").json()["verified"] is False


def test_cooldown_and_lockout(api, monkeypatch):
    client, csrf, _ = api
    sent = []
    _enable(monkeypatch, sent)
    person = _create(client, csrf, "Throttle", "+918100000005")
    url = "/v1/prospects/" + person["id"] + "/otp"
    first = client.post(url + "/request", headers=csrf)
    assert first.status_code == 200, first.text
    second = client.post(url + "/request", headers=csrf)
    assert second.status_code == 429
    assert len(sent) == 1
    for _ in range(5):
        response = client.post(url + "/verify", headers=csrf, json={
            "challenge_id": first.json()["challenge_id"],
            "code": "111111" if sent[0][1] != "111111" else "222222",
        })
        assert response.status_code == 400
    valid_after_lock = client.post(url + "/verify", headers=csrf, json={
        "challenge_id": first.json()["challenge_id"], "code": sent[0][1],
    })
    assert valid_after_lock.status_code == 400


def test_phone_change_invalidates_issued_code(api, monkeypatch):
    client, csrf, _ = api
    sent = []
    _enable(monkeypatch, sent)
    person = _create(client, csrf, "Changed", "+918100000006")
    url = "/v1/prospects/" + person["id"] + "/otp"
    req = client.post(url + "/request", headers=csrf)
    assert req.status_code == 200
    current = client.get("/v1/prospects/" + person["id"]).json()
    updated = client.patch("/v1/prospects/" + person["id"], headers=csrf, json={
        "version": current["version"], "mobile_number": "+918100000007",
        "whatsapp_number": "+918100000007",
    })
    assert updated.status_code == 200, updated.text
    old = client.post(url + "/verify", headers=csrf, json={
        "challenge_id": req.json()["challenge_id"], "code": sent[0][1],
    })
    assert old.status_code == 400


def test_first_activation_and_reactivation_are_otp_gated(api, monkeypatch):
    client, csrf, engine = api
    sent = []
    _enable(monkeypatch, sent)
    monkeypatch.setattr("app.sponsor_otp.COOLDOWN_SECONDS", 0)
    created = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "First Activation Sponsor",
        "mobile_number": "+918100000008", "area_city": "Bengaluru",
        "whatsapp_opt_in": True,  # Explicit Admin attestation at registration.
    })
    assert created.status_code == 201, created.text
    person = created.json()
    root = "/v1/prospects/" + person["id"]
    assert client.post(root + "/stage", headers=csrf, json={
        "version": person["version"], "stage": "active",
    }).status_code == 409
    before = client.get(root).json()
    assert before["crm_stage"] == "inactive"
    with Session(engine) as db:
        consent = db.scalars(select(CommunicationConsentEvent).where(
            CommunicationConsentEvent.recipient_id == uuid.UUID(person["id"]),
        )).all()
        assert len(consent) == 1
        assert consent[0].decision == "opted_in"
        assert consent[0].evidence_reference

    request = client.post(root + "/otp/request", headers=csrf)
    assert request.status_code == 200, request.text
    challenge = request.json()["challenge_id"]
    wrong = client.post(root + "/otp/activate", headers=csrf, json={
        "version": person["version"], "challenge_id": challenge,
        "code": "000000" if sent[-1][1] != "000000" else "111111",
    })
    assert wrong.status_code == 400
    assert client.get(root).json()["crm_stage"] == "inactive"
    activated = client.post(root + "/otp/activate", headers=csrf, json={
        "version": person["version"], "challenge_id": challenge,
        "code": sent[-1][1],
    })
    assert activated.status_code == 200, activated.text
    assert activated.json() == {"status": "active", "reactivation": False}
    assert client.get(root).json()["crm_stage"] == "active"
    assert client.post(root + "/otp/activate", headers=csrf, json={
        "version": person["version"], "challenge_id": challenge,
        "code": sent[-1][1],
    }).status_code in (400, 409)
    current = client.get(root).json()
    inactive = client.post(root + "/stage", headers=csrf, json={
        "version": current["version"], "stage": "inactive",
        "reason": "timing",
    })
    assert inactive.status_code == 200, inactive.text
    current = inactive.json()
    assert current["crm_stage"] == "inactive"
    assert client.post(root + "/stage", headers=csrf, json={
        "version": current["version"], "stage": "active",
        "note": "This must not bypass OTP",
    }).status_code == 409
    request_again = client.post(root + "/otp/request", headers=csrf)
    assert request_again.status_code == 200, request_again.text
    challenge_again = request_again.json()["challenge_id"]
    missing_reason = client.post(root + "/otp/activate", headers=csrf, json={
        "version": current["version"], "challenge_id": challenge_again,
        "code": sent[-1][1],
    })
    assert missing_reason.status_code == 422
    valid = client.post(root + "/otp/activate", headers=csrf, json={
        "version": current["version"], "challenge_id": challenge_again,
        "code": sent[-1][1], "reactivation_reason": "Sponsor wishes to return",
    })
    assert valid.status_code == 200, valid.text
    assert valid.json()["reactivation"] is True
    after = client.get(root).json()
    assert after["crm_stage"] == "active"
    assert len(after["stage_history"]) == 3
    assert after["stage_history"][-1]["note"] == "Sponsor wishes to return"
    assert after["whatsapp_opt_in"] is True
    with Session(engine) as db:
        assert db.scalars(select(ProspectStageTransition).where(
            ProspectStageTransition.prospect_id == uuid.UUID(person["id"]),
        )).all()


def test_activation_without_marketing_permission_does_not_invent_consent(api, monkeypatch):
    client, csrf, engine = api
    sent = []
    _enable(monkeypatch, sent)
    person = _create(client, csrf, "No Auto Optin", "+918100000009")
    base = "/v1/prospects/" + person["id"]
    issued = client.post(base + "/otp/request", headers=csrf)
    assert issued.status_code == 200
    approved = client.post(base + "/otp/activate", headers=csrf, json={
        "version": person["version"], "challenge_id": issued.json()["challenge_id"],
        "code": sent[-1][1],
    })
    assert approved.status_code == 200, approved.text
    after = client.get(base).json()
    assert after["crm_stage"] == "active"
    assert after["whatsapp_opt_in"] is False
    with Session(engine) as db:
        assert db.scalars(select(CommunicationConsentEvent).where(
            CommunicationConsentEvent.recipient_id == uuid.UUID(person["id"]),
        )).all() == []


def test_local_otp_uses_allowlisted_phone_only_and_does_not_claim_delivery(monkeypatch):
    allowed = "+918100000010"
    config = SimpleNamespace(otp_local_pilot_enabled=True, saasyto_local_test_phone=allowed)
    sent = []

    def fake_send(_cfg, *, phone, message):
        sent.append((phone, message))
        return Submission("accepted_unverified")

    monkeypatch.setattr("app.sponsor_otp.send_text", fake_send)
    _deliver(config, allowed, "123456")
    assert len(sent) == 1 and sent[0][0] == allowed
    assert "123456" in sent[0][1]
    with pytest.raises(ValueError, match="allowlisted"):
        _deliver(config, "+918100000011", "654321")
    assert len(sent) == 1
    monkeypatch.setattr(
        "app.sponsor_otp.send_text",
        lambda _cfg, *, phone, message: Submission("unknown", "provider_timeout"),
    )
    with pytest.raises(ValueError, match="acceptance"):
        _deliver(config, allowed, "123456")


def test_local_otp_request_refuses_other_prospect_before_provider_call(api, monkeypatch):
    client, csrf, engine = api
    sent = []
    person = _create(client, csrf, "Other phone", "+918100000012")
    monkeypatch.setattr("app.sponsor_otp.get_settings", lambda: SimpleNamespace(
        otp_delivery_enabled=False, otp_local_pilot_enabled=True,
        otp_secret=SECRET, saasyto_local_test_phone="+918100000013",
    ))
    monkeypatch.setattr(
        "app.sponsor_otp._deliver",
        lambda _cfg, phone, code: sent.append((phone, code)),
    )
    response = client.post("/v1/prospects/" + person["id"] + "/otp/request", headers=csrf)
    assert response.status_code == 403, response.text
    assert sent == []
    with Session(engine) as db:
        assert db.scalars(select(SponsorOtpChallenge)).all() == []
