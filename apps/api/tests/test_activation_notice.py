"""After-OTP activation acknowledgements: consent, cutoff, replay, and failure."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditEvent
from app.saasyto_client import Submission
from app.security import utc_now

pytest_plugins = ("test_crm_review_2026_10",)
SECRET = "synthetic-otp-notice-secret-long-enough-for-tests"


def setup(monkeypatch, *, allowed=True, local=False, cutoff=None, error=False):
    codes = []
    messages = []
    settings = SimpleNamespace(
        otp_delivery_enabled=not local,
        otp_local_pilot_enabled=local,
        otp_secret=SECRET,
        otp_activation_notice_enabled=True,
        saasyto_delivery_enabled=True,
        saasyto_sender_approved=True,
        saasyto_enable_after=cutoff or (utc_now() - timedelta(minutes=5)),
        saasyto_local_test_enabled=local,
        saasyto_local_test_phone="+918100005501" if local else None,
    )
    monkeypatch.setattr("app.sponsor_otp.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.sponsor_otp._deliver",
        lambda _cfg, phone, code: codes.append(code),
    )

    def submit(_cfg, *, phone, message):
        messages.append((phone, message))
        if error:
            raise ValueError("synthetic provider error")
        return Submission("accepted_unverified")

    monkeypatch.setattr("app.activation_notice.send_text", submit)
    return codes, messages


def create(client, csrf, phone, consent):
    response = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Activation Notice Candidate",
        "mobile_number": phone, "whatsapp_number": phone,
        "area_city": "Bengaluru", "whatsapp_opt_in": consent,
    })
    assert response.status_code == 201, response.text
    return response.json()


def activate(client, csrf, person, code, challenge_id):
    return client.post("/v1/prospects/" + person["id"] + "/otp/activate",
                       headers=csrf, json={
        "version": person["version"], "challenge_id": challenge_id, "code": code,
    })


def request(client, csrf, person):
    return client.post("/v1/prospects/" + person["id"] + "/otp/request", headers=csrf)


def test_acknowledgement_once_for_registration_consented_sponsor(api, monkeypatch):
    client, csrf, engine = api
    codes, messages = setup(monkeypatch)
    person = create(client, csrf, "+918100005501", True)
    issued = request(client, csrf, person)
    assert issued.status_code == 200, issued.text
    challenge = issued.json()["challenge_id"]
    result = activate(client, csrf, person, codes[0], challenge)
    assert result.status_code == 200, result.text
    assert result.json()["activation_notice"] == "accepted_unverified"
    assert len(messages) == 1
    assert messages[0][0] == person["mobile_number"]
    assert "activated" in messages[0][1]
    assert "not a payment confirmation" in messages[0][1]
    assert "123456" not in messages[0][1]
    replay = activate(client, csrf, person, codes[0], challenge)
    assert replay.status_code in (400, 409)
    assert len(messages) == 1
    with Session(engine) as db:
        assert db.scalar(select(func.count(AuditEvent.id)).where(
            AuditEvent.action == "prospect.activation_notice_attempt",
        )) == 1


def test_acknowledgement_suppressed_on_explicit_optout(api, monkeypatch):
    client, csrf, _ = api
    codes, messages = setup(monkeypatch)
    person = create(client, csrf, "+918100005502", True)
    revoked = client.post("/v1/communication/consent-events", headers=csrf, json={
        "recipient_kind": "prospect", "recipient_id": person["id"],
        "channel": "whatsapp", "decision": "opted_out",
        "source": "sponsor requested stop",
    })
    assert revoked.status_code == 201, revoked.text
    person = client.get("/v1/prospects/" + person["id"]).json()
    issued = request(client, csrf, person)
    assert issued.status_code == 200
    result = activate(client, csrf, person, codes[0], issued.json()["challenge_id"])
    assert result.status_code == 200, result.text
    assert result.json()["activation_notice"] == "suppressed_no_general_consent"
    assert messages == []


def test_otp_is_not_consent_even_after_active(api, monkeypatch):
    client, csrf, _ = api
    codes, messages = setup(monkeypatch)
    person = create(client, csrf, "+918100005503", False)
    issued = request(client, csrf, person)
    assert issued.status_code == 200
    result = activate(client, csrf, person, codes[0], issued.json()["challenge_id"])
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "active"
    assert result.json()["activation_notice"] == "suppressed_no_general_consent"
    assert messages == []


@pytest.mark.parametrize("local,phone,expected", [
    (True, "+918100005501", "accepted_unverified"),
    (True, "+918100005504", "suppressed_local_test_number"),
    (False, "+918100005505", "accepted_unverified"),
])
def test_notice_scope_for_local_and_standard_otp(api, monkeypatch, local, phone, expected):
    client, csrf, _ = api
    codes, messages = setup(monkeypatch, local=local)
    person = create(client, csrf, phone, True)
    issued = request(client, csrf, person)
    # Fake OTP transport only; this verifies notification's own allowlist.
    assert issued.status_code in (200, 403)
    if issued.status_code == 403:
        assert local and expected == "suppressed_local_test_number"
        return
    result = activate(client, csrf, person, codes[0], issued.json()["challenge_id"])
    assert result.status_code == 200, result.text
    assert result.json()["activation_notice"] == expected
    assert len(messages) == (1 if expected == "accepted_unverified" else 0)


def test_activation_not_rolled_back_if_confirmation_provider_fails(api, monkeypatch):
    client, csrf, _ = api
    codes, messages = setup(monkeypatch, error=True)
    person = create(client, csrf, "+918100005506", True)
    issued = request(client, csrf, person)
    response = activate(client, csrf, person, codes[0], issued.json()["challenge_id"])
    assert response.status_code == 200, response.text
    assert response.json()["activation_notice"] == "unknown"
    assert client.get("/v1/prospects/" + person["id"]).json()["crm_stage"] == "active"
    assert len(messages) == 1


def test_activation_notice_respects_sender_cutoff(api, monkeypatch):
    client, csrf, _ = api
    codes, messages = setup(monkeypatch, cutoff=utc_now() + timedelta(days=1))
    person = create(client, csrf, "+918100005507", True)
    issued = request(client, csrf, person)
    response = activate(client, csrf, person, codes[0], issued.json()["challenge_id"])
    assert response.status_code == 200, response.text
    assert response.json()["activation_notice"] == "before_sender_activation"
    assert messages == []
