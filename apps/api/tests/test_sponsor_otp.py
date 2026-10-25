"""Sponsor OTP: bounded challenge, tenant binding, no delivery claims or consent changes."""
import uuid
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Prospect, ProspectStageTransition, SponsorOtpChallenge

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


def test_valid_otp_activates_new_prospect_only_and_prevents_manual_bypass(
    api, monkeypatch,
):
    client, csrf, engine = api
    person = _create(client, csrf, "Activation", "+918100000021")
    phone = person["mobile_number"]
    out = []
    settings = SimpleNamespace(
        otp_delivery_enabled=True, otp_secret=SECRET,
        otp_activates_prospect=True, otp_activation_notice_enabled=True,
        saasyto_delivery_enabled=True, saasyto_sender_approved=True,
    )
    monkeypatch.setattr("app.sponsor_otp.get_settings", lambda: settings)
    monkeypatch.setattr("app.prospects.get_settings", lambda: SimpleNamespace(
        upi_match_secret="synthetic-key-for-otp-review-sufficient-length",
        otp_activates_prospect=True,
    ))
    monkeypatch.setattr("app.sponsor_otp._deliver",
                        lambda _cfg, number, code: out.append((number, code)))
    monkeypatch.setattr("app.sponsor_otp.send_text", lambda *_a, **_k:
                        (_ for _ in ()).throw(AssertionError("No consent: no message")))
    denied = client.post("/v1/prospects/" + person["id"] + "/stage",
                         headers=csrf, json={
        "version": person["version"], "stage": "active",
        "note": "Pre-OTP manual change",
    })
    assert denied.status_code == 409
    route = "/v1/prospects/" + person["id"] + "/otp"
    issued = client.post(route + "/request", headers=csrf)
    assert issued.status_code == 200
    assert out[0][0] == phone
    wrong = client.post(route + "/verify", headers=csrf, json={
        "challenge_id": issued.json()["challenge_id"],
        "code": "111111" if out[0][1] != "111111" else "222222",
    })
    assert wrong.status_code == 400
    assert client.get("/v1/prospects/" + person["id"]).json()["crm_stage"] == "inactive"
    verified = client.post(route + "/verify", headers=csrf, json={
        "challenge_id": issued.json()["challenge_id"], "code": out[0][1],
    })
    assert verified.status_code == 200, verified.text
    assert verified.json()["crm_stage"] == "active"
    assert verified.json()["activation_notice"] == "skipped_no_permission"
    prospect = client.get("/v1/prospects/" + person["id"]).json()
    assert prospect["crm_stage"] == "active"
    assert prospect["lifecycle_status"] == "new"
    assert prospect["whatsapp_opt_in"] is False
    assert client.post(route + "/verify", headers=csrf, json={
        "challenge_id": issued.json()["challenge_id"], "code": out[0][1],
    }).status_code == 400
    with Session(engine) as db:
        transitions = db.scalars(select(ProspectStageTransition)).all()
        assert len(transitions) == 1
        assert transitions[0].from_stage == "inactive"
        assert transitions[0].to_stage == "active"
        saved = db.get(Prospect, uuid.UUID(person["id"]))
        assert saved.last_verified_payment_at is None


def test_activation_notice_sent_once_only_after_documented_optin(api, monkeypatch):
    client, csrf, _engine = api
    person = _create(client, csrf, "Activation message", "+918100000022")
    consent = client.post("/v1/communication/consent-events", headers=csrf, json={
        "recipient_kind": "prospect", "recipient_id": person["id"],
        "channel": "whatsapp", "decision": "opted_in",
        "source": "recorded onboarding permission",
        "evidence_reference": "onboarding consent register 22",
    })
    assert consent.status_code == 201, consent.text
    sent_otp = []
    sent_notice = []
    settings = SimpleNamespace(
        otp_delivery_enabled=True, otp_secret=SECRET,
        otp_activates_prospect=True, otp_activation_notice_enabled=True,
        saasyto_delivery_enabled=True, saasyto_sender_approved=True,
    )
    monkeypatch.setattr("app.sponsor_otp.get_settings", lambda: settings)
    monkeypatch.setattr("app.sponsor_otp._deliver",
                        lambda _cfg, number, code: sent_otp.append(code))

    def fake_text(_cfg, *, phone, message):
        sent_notice.append((phone, message))
        return SimpleNamespace(state="accepted_unverified")

    monkeypatch.setattr("app.sponsor_otp.send_text", fake_text)
    route = "/v1/prospects/" + person["id"] + "/otp"
    issued = client.post(route + "/request", headers=csrf).json()
    verified = client.post(route + "/verify", headers=csrf, json={
        "challenge_id": issued["challenge_id"], "code": sent_otp[0],
    })
    assert verified.status_code == 200, verified.text
    assert verified.json()["crm_stage"] == "active"
    assert verified.json()["activation_notice"] == "accepted_unverified"
    assert len(sent_notice) == 1
    assert sent_notice[0][0] == person["mobile_number"]
    assert "registration" in sent_notice[0][1]
    assert "payment" in sent_notice[0][1]
    assert client.post(route + "/verify", headers=csrf, json={
        "challenge_id": issued["challenge_id"], "code": sent_otp[0],
    }).status_code == 400
    assert len(sent_notice) == 1


def test_opted_out_activation_notification_is_never_submitted(api, monkeypatch):
    client, csrf, _engine = api
    person = _create(client, csrf, "Declined notice", "+918100000023")
    choice = client.post("/v1/communication/consent-events", headers=csrf, json={
        "recipient_kind": "prospect", "recipient_id": person["id"],
        "channel": "whatsapp", "decision": "opted_out",
        "source": "documented opt-out",
    })
    assert choice.status_code == 201
    settings = SimpleNamespace(
        otp_delivery_enabled=True, otp_secret=SECRET,
        otp_activates_prospect=True, otp_activation_notice_enabled=True,
        saasyto_delivery_enabled=True, saasyto_sender_approved=True,
    )
    monkeypatch.setattr("app.sponsor_otp.get_settings", lambda: settings)
    codes = []
    monkeypatch.setattr("app.sponsor_otp._deliver",
                        lambda _cfg, _number, code: codes.append(code))
    monkeypatch.setattr("app.sponsor_otp.send_text", lambda *_a, **_k:
                        (_ for _ in ()).throw(AssertionError("Opt-out blocks notice")))
    url = "/v1/prospects/" + person["id"] + "/otp"
    issued = client.post(url + "/request", headers=csrf).json()
    confirmation = client.post(url + "/verify", headers=csrf, json={
        "challenge_id": issued["challenge_id"], "code": codes[0],
    })
    assert confirmation.status_code == 200, confirmation.text
    assert confirmation.json()["crm_stage"] == "active"
    assert confirmation.json()["activation_notice"] == "skipped_no_permission"


def test_verified_new_prospect_reverts_inactive_after_phone_change(api, monkeypatch):
    client, csrf, _engine = api
    person = _create(client, csrf, "Changed after activating", "+918100000024")
    cfg = SimpleNamespace(
        otp_delivery_enabled=True, otp_secret=SECRET, otp_activates_prospect=True,
        otp_activation_notice_enabled=False,
    )
    monkeypatch.setattr("app.sponsor_otp.get_settings", lambda: cfg)
    monkeypatch.setattr("app.prospects.get_settings", lambda: SimpleNamespace(
        upi_match_secret="synthetic-upi-hmac-for-otp-change-test-value",
        otp_activates_prospect=True,
    ))
    delivered = []
    monkeypatch.setattr("app.sponsor_otp._deliver",
                        lambda _cfg, _phone, code: delivered.append(code))
    endpoint = "/v1/prospects/" + person["id"] + "/otp"
    issued = client.post(endpoint + "/request", headers=csrf).json()
    done = client.post(endpoint + "/verify", headers=csrf, json={
        "challenge_id": issued["challenge_id"], "code": delivered[0],
    })
    assert done.status_code == 200 and done.json()["crm_stage"] == "active"
    current = client.get("/v1/prospects/" + person["id"]).json()
    changed = client.patch("/v1/prospects/" + person["id"], headers=csrf, json={
        "version": current["version"], "mobile_number": "+918100000025",
        "whatsapp_number": "+918100000025",
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()["crm_stage"] == "inactive"
    assert changed.json()["whatsapp_opt_in"] is False
    assert client.get(endpoint + "/status").json()["verified"] is False
    without_code = client.post("/v1/prospects/" + person["id"] + "/stage",
                               headers=csrf, json={
        "version": changed.json()["version"], "stage": "active",
        "note": "Manual override after address change",
    })
    assert without_code.status_code == 409


def test_secondary_mobile_edit_preserves_verified_whatsapp_and_then_revokes_on_change(
    api, monkeypatch,
):
    client, csrf, _engine = api
    person = _create(client, csrf, "Secondary mobile", "+918100000031")
    alternate = "+918100000032"
    p = client.patch("/v1/prospects/" + person["id"], headers=csrf, json={
        "version": person["version"], "whatsapp_number": alternate,
    })
    assert p.status_code == 200, p.text
    cfg = SimpleNamespace(
        otp_delivery_enabled=True, otp_secret=SECRET,
        otp_activates_prospect=True, otp_activation_notice_enabled=False,
    )
    monkeypatch.setattr("app.sponsor_otp.get_settings", lambda: cfg)
    monkeypatch.setattr("app.prospects.get_settings", lambda: SimpleNamespace(
        upi_match_secret="synthetic-upi-key-for-otp-secondary-contact",
        otp_activates_prospect=True,
    ))
    out = []
    monkeypatch.setattr("app.sponsor_otp._deliver",
                        lambda _cfg, phone, code: out.append((phone, code)))
    endpoint = "/v1/prospects/" + person["id"] + "/otp"
    issued = client.post(endpoint + "/request", headers=csrf).json()
    assert out[0][0] == alternate
    verified = client.post(endpoint + "/verify", headers=csrf, json={
        "challenge_id": issued["challenge_id"], "code": out[0][1],
    })
    assert verified.status_code == 200 and verified.json()["crm_stage"] == "active"
    updated = client.get("/v1/prospects/" + person["id"]).json()
    secondary = client.patch("/v1/prospects/" + person["id"], headers=csrf, json={
        "version": updated["version"], "mobile_number": "+918100000033",
    })
    assert secondary.status_code == 200, secondary.text
    assert secondary.json()["crm_stage"] == "active"
    assert client.get(endpoint + "/status").json()["verified"] is True
    primary = client.patch("/v1/prospects/" + person["id"], headers=csrf, json={
        "version": secondary.json()["version"],
        "whatsapp_number": "+918100000034",
    })
    assert primary.status_code == 200, primary.text
    assert primary.json()["crm_stage"] == "inactive"
    assert client.get(endpoint + "/status").json()["verified"] is False
