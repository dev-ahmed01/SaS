"""Tests for optional consent-gated activation notices."""
from types import SimpleNamespace

from app.saasyto_client import Submission

pytest_plugins = ("test_crm_review_2026_10",)


def test_activation_notice_is_sent_once_after_verified_activation(api, monkeypatch):
    client, csrf, _ = api
    contact = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "New sponsor", "mobile_number": "+918100000081",
        "area_city": "Bengaluru",
    }).json()
    consent = client.post("/v1/communication/consent-events", headers=csrf, json={
        "recipient_kind": "prospect", "recipient_id": contact["id"],
        "channel": "whatsapp", "decision": "opted_in",
        "source": "onboarding permission",
        "evidence_reference": "documented-permission-81",
    })
    assert consent.status_code == 201
    cfg = SimpleNamespace(
        otp_delivery_enabled=True,
        otp_secret="synthetic-otp-test-secret-more-than-thirty-two-characters",
        otp_activation_notice_enabled=True,
        saasyto_delivery_enabled=True,
        saasyto_sender_approved=True,
    )
    codes = []
    messages = []
    monkeypatch.setattr("app.sponsor_otp.get_settings", lambda: cfg)
    monkeypatch.setattr("app.sponsor_otp._deliver",
                        lambda _cfg, phone, code: codes.append(code))
    monkeypatch.setattr("app.activation_notice.send_text",
                        lambda _cfg, *, phone, message:
                        (messages.append((phone, message)), Submission("accepted_unverified"))[1])
    url = "/v1/prospects/" + contact["id"] + "/otp"
    issued = client.post(url + "/request", headers=csrf)
    assert issued.status_code == 200, issued.text
    body = {"challenge_id": issued.json()["challenge_id"], "code": codes[0],
            "version": contact["version"], "reactivation_reason": None}
    activated = client.post(url + "/activate", headers=csrf, json=body)
    assert activated.status_code == 200, activated.text
    assert activated.json()["activation_notice"] == "accepted_unverified"
    assert len(messages) == 1
    assert messages[0][0] == contact["mobile_number"]
    assert "payment" in messages[0][1]
    assert client.post(url + "/activate", headers=csrf, json=body).status_code in (400, 409)
    assert len(messages) == 1


def test_activation_notice_never_sends_after_optout(api, monkeypatch):
    client, csrf, _ = api
    person = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Opted out sponsor", "mobile_number": "+918100000082",
        "area_city": "Bengaluru",
    }).json()
    declined = client.post("/v1/communication/consent-events", headers=csrf, json={
        "recipient_kind": "prospect", "recipient_id": person["id"],
        "channel": "whatsapp", "decision": "opted_out",
        "source": "requested no outreach",
    })
    assert declined.status_code == 201, declined.text
    cfg = SimpleNamespace(
        otp_delivery_enabled=True,
        otp_secret="synthetic-otp-test-secret-more-than-thirty-two-characters",
        otp_activation_notice_enabled=True,
        saasyto_delivery_enabled=True,
        saasyto_sender_approved=True,
    )
    codes = []
    monkeypatch.setattr("app.sponsor_otp.get_settings", lambda: cfg)
    monkeypatch.setattr("app.sponsor_otp._deliver",
                        lambda _cfg, _phone, code: codes.append(code))
    monkeypatch.setattr("app.activation_notice.send_text",
                        lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(AssertionError("Opt out must block notice")))
    base = "/v1/prospects/" + person["id"] + "/otp"
    issued = client.post(base + "/request", headers=csrf)
    assert issued.status_code == 200, issued.text
    result = client.post(base + "/activate", headers=csrf, json={
        "challenge_id": issued.json()["challenge_id"], "code": codes[0],
        "version": person["version"], "reactivation_reason": None,
    })
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "active"
    assert result.json()["activation_notice"] == "suppressed_no_general_consent"


def test_activation_notice_does_not_infer_consent_from_verified_phone(api, monkeypatch):
    client, csrf, _ = api
    person = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "No permission sponsor", "mobile_number": "+918100000083",
        "area_city": "Bengaluru", "whatsapp_opt_in": False,
    }).json()
    cfg = SimpleNamespace(
        otp_delivery_enabled=True,
        otp_secret="synthetic-otp-test-secret-more-than-thirty-two-characters",
        otp_activation_notice_enabled=True,
        saasyto_delivery_enabled=True,
        saasyto_sender_approved=True,
    )
    codes = []
    monkeypatch.setattr("app.sponsor_otp.get_settings", lambda: cfg)
    monkeypatch.setattr("app.sponsor_otp._deliver",
                        lambda _cfg, _phone, code: codes.append(code))
    monkeypatch.setattr("app.activation_notice.send_text",
                        lambda *_args, **_kw:
                        (_ for _ in ()).throw(AssertionError("No consent")))
    base = "/v1/prospects/" + person["id"] + "/otp"
    issue = client.post(base + "/request", headers=csrf)
    assert issue.status_code == 200, issue.text
    confirmation = client.post(base + "/activate", headers=csrf, json={
        "version": person["version"], "challenge_id": issue.json()["challenge_id"],
        "code": codes[0], "reactivation_reason": None,
    })
    assert confirmation.status_code == 200, confirmation.text
    assert confirmation.json()["status"] == "active"
    assert confirmation.json()["activation_notice"] == "suppressed_no_general_consent"
