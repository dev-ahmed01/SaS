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
