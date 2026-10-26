"""Sponsor OTP: bounded challenge, tenant binding, no delivery claims or consent changes."""
import uuid
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CommunicationConsentEvent, ProspectStageTransition, SponsorOtpChallenge
from app.saasyto_client import Submission
from app.sponsor_otp import OtpDeliveryUnconfirmed, _deliver

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
        lambda _cfg, phone, code, *_extra: delivered.append((phone, code)),
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
    assert len(sent[0][1]) == 4
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
        "challenge_id": challenge["challenge_id"], "code": "0000"
        if sent[0][1] != "0000" else "9999",
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
            "code": "1111" if sent[0][1] != "1111" else "2222",
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
        "code": "0000" if sent[-1][1] != "0000" else "1111",
    })
    assert wrong.status_code == 400
    assert client.get(root).json()["crm_stage"] == "inactive"
    activated = client.post(root + "/otp/activate", headers=csrf, json={
        "version": person["version"], "challenge_id": challenge,
        "code": sent[-1][1],
    })
    assert activated.status_code == 200, activated.text
    assert activated.json() == {"status": "active", "reactivation": False,
                                "activation_notice": "disabled"}
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
        _deliver(config, "+918100000011", "6543")
    assert len(sent) == 1
    monkeypatch.setattr(
        "app.sponsor_otp.send_text",
        lambda _cfg, *, phone, message: Submission("unknown", "provider_timeout"),
    )
    with pytest.raises(OtpDeliveryUnconfirmed, match="outcome unknown"):
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
        lambda _cfg, phone, code, *_extra: sent.append((phone, code)),
    )
    response = client.post("/v1/prospects/" + person["id"] + "/otp/request", headers=csrf)
    assert response.status_code == 403, response.text
    assert sent == []
    with Session(engine) as db:
        assert db.scalars(select(SponsorOtpChallenge)).all() == []


def test_four_digits_two_minutes_and_session_resume(api, monkeypatch):
    client, csrf, engine = api
    delivered = []
    _enable(monkeypatch, delivered)
    prospect = _create(client, csrf, "Four Digits", "+918100000014")
    root = "/v1/prospects/" + prospect["id"] + "/otp"
    issued = client.post(root + "/request", headers=csrf)
    assert issued.status_code == 200, issued.text
    assert len(delivered) == 1
    assert delivered[0][1].isdigit() and len(delivered[0][1]) == 4
    with Session(engine) as db:
        entry = db.get(SponsorOtpChallenge, uuid.UUID(issued.json()["challenge_id"]))
        assert entry.expires_at - entry.created_at == timedelta(minutes=2)
    resumed = client.get(root + "/status")
    assert resumed.status_code == 200
    assert resumed.json()["challenge_id"] == issued.json()["challenge_id"]
    assert resumed.json()["expires_at"] == issued.json()["expires_at"]
    assert "code" not in resumed.json()
    from app.security import utc_now
    after_expiry = utc_now() + timedelta(minutes=3)
    monkeypatch.setattr("app.sponsor_otp.utc_now", lambda: after_expiry)
    assert client.get(root + "/status").json()["challenge_id"] is None
    invalid = client.post(root + "/activate", headers=csrf, json={
        "version": prospect["version"], "challenge_id": issued.json()["challenge_id"],
        "code": delivered[0][1],
    })
    assert invalid.status_code == 400
    assert client.get("/v1/prospects/" + prospect["id"]).json()["crm_stage"] == "inactive"


def test_next_otp_differs_and_invalidates_previous(api, monkeypatch):
    client, csrf, engine = api
    delivered = []
    _enable(monkeypatch, delivered)
    monkeypatch.setattr("app.sponsor_otp.COOLDOWN_SECONDS", 0)
    prospect = _create(client, csrf, "Fresh Code", "+918100000015")
    base = "/v1/prospects/" + prospect["id"] + "/otp"
    old = client.post(base + "/request", headers=csrf)
    new = client.post(base + "/request", headers=csrf)
    assert old.status_code == 200 and new.status_code == 200
    assert old.json()["challenge_id"] != new.json()["challenge_id"]
    assert delivered[0][1] != delivered[1][1]
    with Session(engine) as db:
        previous = db.get(SponsorOtpChallenge, uuid.UUID(old.json()["challenge_id"]))
        assert previous.status == "superseded"
    old_code = client.post(base + "/activate", headers=csrf, json={
        "version": prospect["version"], "challenge_id": old.json()["challenge_id"],
        "code": delivered[0][1],
    })
    assert old_code.status_code == 400
    current = client.post(base + "/activate", headers=csrf, json={
        "version": prospect["version"], "challenge_id": new.json()["challenge_id"],
        "code": delivered[1][1],
    })
    assert current.status_code == 200, current.text
    assert current.json()["status"] == "active"


def test_meta_otp_payload_is_addressed_to_selected_prospect_only(monkeypatch):
    """Official AUTHENTICATION delivery uses the current recipient, not a test allowlist."""
    sent = []
    real_client = httpx.Client

    def handler(request):
        assert request.method == "POST"
        assert request.url == "https://graph.facebook.com/v23.0/1122334455/messages"
        assert request.headers["Authorization"] == "Bearer "+("synthetic-meta-token-"+"x"*24)
        payload = __import__("json").loads(request.content)
        sent.append(payload)
        return httpx.Response(200, json={"messages": [{"id": "wamid.synthetic"}]})

    monkeypatch.setattr("app.sponsor_otp.httpx.Client", lambda **kwargs:
                        real_client(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr("app.sponsor_otp.send_text", lambda *_a, **_kw:
                        (_ for _ in ()).throw(AssertionError("Meta OTP may not use Saasyto")))
    cfg = SimpleNamespace(
        otp_local_pilot_enabled=False,
        otp_meta_access_token="synthetic-meta-token-"+"x"*24,
        otp_meta_phone_number_id="1122334455",
        otp_meta_template_name="sponsor_activation_code",
        otp_meta_template_language="en_US",
        otp_meta_graph_version="v23.0",
    )
    for number, code in (
        ("+918100000021", "1042"),
        ("+918100000022", "2356"),
        ("+918100000023", "9812"),
    ):
        _deliver(cfg, number, code)

    assert [item["to"] for item in sent] == [
        "918100000021", "918100000022", "918100000023",
    ]
    for payload, code in zip(sent, ("1042", "2356", "9812"), strict=True):
        assert payload["messaging_product"] == "whatsapp"
        assert payload["type"] == "template"
        assert payload["template"]["name"] == cfg.otp_meta_template_name
        components = payload["template"]["components"]
        assert components[0]["parameters"] == [{"type": "text", "text": code}]
        assert components[1]["parameters"] == [{"type": "text", "text": code}]
        assert components[1]["sub_type"] == "url"


@pytest.mark.parametrize("http_status,receipt", [
    (403, {"error": {"message": "invalid token"}}),
    (200, {"messages": []}),
    (200, {"messages": [{}]}),
])
def test_meta_otp_never_claims_acceptance_for_invalid_reply(
    monkeypatch, http_status, receipt,
):
    real_client = httpx.Client
    monkeypatch.setattr("app.sponsor_otp.httpx.Client", lambda **kwargs:
                        real_client(transport=httpx.MockTransport(
                            lambda _request: httpx.Response(http_status, json=receipt)
                        ), **kwargs))
    cfg = SimpleNamespace(
        otp_local_pilot_enabled=False,
        otp_meta_access_token="synthetic-meta-token-"+"x"*24,
        otp_meta_phone_number_id="1122334455",
        otp_meta_template_name="sponsor_activation_code",
        otp_meta_template_language="en_US", otp_meta_graph_version="v23.0",
    )
    with pytest.raises(ValueError, match="provider|acceptance"):
        _deliver(cfg, "+918100000021", "5732")


def test_production_meta_sender_requires_independent_credentials():
    from app.config import Settings

    base = {
        "app_env": "production",
        "database_url": "postgresql+psycopg://user:password@db.example.org:5432/sas?sslmode=require",
        "auth_secret": "a"*48,
        "upi_match_secret": "b"*48,
        "otp_secret": "c"*48,
        "otp_meta_access_token": "synthetic-meta-token-"+"x"*24,
        "otp_meta_phone_number_id": "1122334455",
        "otp_meta_template_name": "sponsor_activation_code",
        "otp_meta_template_language": "en_US",
        "otp_meta_graph_version": "v23.0",
        "otp_delivery_enabled": True,
        "otp_local_pilot_enabled": False,
        "saasyto_delivery_enabled": False,
        "saasyto_local_test_enabled": False,
        "local_demo_login_enabled": False,
    }
    cfg = Settings(_env_file=None, **base)
    assert cfg.otp_delivery_enabled is True
    assert cfg.saasyto_delivery_enabled is False
    assert cfg.saasyto_local_test_phone is None
    # An official Meta OTP setup never needs an allowlisted test recipient.
    with pytest.raises(ValueError, match="Meta WhatsApp OTP access token required"):
        Settings(_env_file=None, **{**base, "otp_meta_access_token": ""})
    with pytest.raises(ValueError, match="Local OTP requires approved"):
        Settings(_env_file=None, **{**base, "otp_local_pilot_enabled": True})
    # Enabling Saasyto production campaigns is a separately reviewed switch.
    with pytest.raises(ValueError, match="Saasyto"):
        Settings(_env_file=None, **{**base, "saasyto_delivery_enabled": True})


def test_saasyto_production_otp_sends_to_only_selected_registered_prospect(
    api, monkeypatch,
):
    """Each admin activation is one message to that prospect, never a broadcast."""
    client, csrf, _engine = api
    first = _create(client, csrf, "Own Number 1", "+918100000031")
    second = _create(client, csrf, "Own Number 2", "+918100000032")
    third = _create(client, csrf, "Not Selected", "+918100000033")
    numbers = []
    codes = []

    def send_prospect(_cfg, *, phone, message):
        numbers.append(phone)
        import re
        code = re.search(r"authentication code to register this sponsorship: ([0-9]{4})", message)
        assert code and "Valid for 2 minutes" in message
        codes.append(code.group(1))
        return Submission("accepted_unverified")

    monkeypatch.setattr("app.sponsor_otp.get_settings", lambda: SimpleNamespace(
        otp_delivery_enabled=False,
        otp_saasyto_enabled=True,
        otp_local_pilot_enabled=False,
        otp_secret=SECRET,
    ))
    monkeypatch.setattr("app.sponsor_otp.send_text", send_prospect)
    one = client.post("/v1/prospects/"+first["id"]+"/otp/request", headers=csrf)
    assert one.status_code == 200, one.text
    assert numbers == [first["mobile_number"]]
    assert third["mobile_number"] not in numbers
    assert "code" not in one.json()
    two = client.post("/v1/prospects/"+second["id"]+"/otp/request", headers=csrf)
    assert two.status_code == 200, two.text
    assert numbers == [first["mobile_number"], second["mobile_number"]]
    assert len(codes) == 2 and all(len(code) == 4 for code in codes)
    assert client.get("/v1/prospects/"+third["id"]).json()["crm_stage"] == "inactive"
    confirmed = client.post("/v1/prospects/"+first["id"]+"/otp/activate", headers=csrf,
        json={"version": first["version"], "challenge_id": one.json()["challenge_id"],
              "code": codes[0]})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "active"
    assert client.get("/v1/prospects/"+second["id"]).json()["crm_stage"] == "inactive"
    assert numbers == [first["mobile_number"], second["mobile_number"]]


def test_saasyto_production_otp_outcomes_never_claim_verified_delivery(monkeypatch):
    """Provider accept only starts an OTP challenge; reject/unknown block activation."""
    selected = "+918100000034"
    cfg = SimpleNamespace(
        otp_local_pilot_enabled=False, otp_saasyto_enabled=True,
    )
    seen = []
    monkeypatch.setattr("app.sponsor_otp.send_text", lambda _cfg, *, phone, message:
                        seen.append((phone, message)) or Submission("accepted_unverified"))
    _deliver(cfg, selected, "1234")
    assert len(seen) == 1 and seen[0][0] == selected
    assert "1234" in seen[0][1]
    monkeypatch.setattr("app.sponsor_otp.send_text", lambda *_a, **_kw:
                        Submission("rejected"))
    with pytest.raises(ValueError, match="declined"):
        _deliver(cfg, selected, "2345")
    monkeypatch.setattr("app.sponsor_otp.send_text", lambda *_a, **_kw:
                        Submission("unknown"))
    with pytest.raises(OtpDeliveryUnconfirmed, match="unknown"):
        _deliver(cfg, selected, "3456")


def test_saasyto_only_production_config_needs_no_meta_subscription():
    from app.config import Settings

    base = {
        "app_env": "production",
        "database_url": "postgresql+psycopg://tester:pw@db.example.com:5432/sas?sslmode=require",
        "auth_secret": "A"*48,
        "upi_match_secret": "B"*48,
        "otp_secret": "C"*48,
        "local_demo_login_enabled": False,
        "saasyto_delivery_enabled": True,
        "saasyto_sender_approved": True,
        "saasyto_instance_id": "sas-instance-01",
        "saasyto_access_token": "saasyto-synthetic-token-value",
        "saasyto_enable_after": "2026-11-01T00:00:00+05:30",
        "saasyto_runner_secret": "D"*48,
        "saasyto_local_test_enabled": False,
        "otp_saasyto_enabled": True,
        "otp_delivery_enabled": False,
        "otp_local_pilot_enabled": False,
        "otp_activation_notice_enabled": False,
    }
    cfg = Settings(_env_file=None, **base)
    assert cfg.otp_saasyto_enabled is True
    assert cfg.otp_meta_access_token is None
    assert cfg.otp_meta_phone_number_id is None
    assert cfg.saasyto_local_test_phone is None
    with pytest.raises(ValueError, match="Saasyto"):
        Settings(_env_file=None, **{**base, "app_env": "development"})
    with pytest.raises(ValueError, match="Saasyto"):
        Settings(_env_file=None, **{**base, "saasyto_local_test_enabled": True})
    with pytest.raises(ValueError, match="Saasyto production OTP"):
        Settings(_env_file=None, **{**base, "otp_delivery_enabled": True})
    with pytest.raises(ValueError, match="Saasyto production OTP"):
        Settings(_env_file=None, **{**base, "saasyto_delivery_enabled": False})
    with pytest.raises(ValueError, match="OTP_SECRET"):
        Settings(_env_file=None, **{**base, "otp_secret": ""})


def test_guarded_two_phone_pilot_otp_activates_only_selected_prospect(api, monkeypatch):
    client, csrf, _engine = api
    first = _create(client, csrf, "Pilot A", "+918100000041")
    second = _create(client, csrf, "Pilot B", "+918100000042")
    third = _create(client, csrf, "Not Authorized", "+918100000043")
    cfg = SimpleNamespace(
        otp_delivery_enabled=False, otp_local_pilot_enabled=True, otp_secret=SECRET,
        saasyto_local_test_phone=first["mobile_number"],
        saasyto_local_test_phone_2=second["mobile_number"],
    )
    outgoing = []

    def mock_send(_cfg, *, phone, message):
        import re
        match = re.search(r"authentication code to register this sponsorship: ([0-9]{4})", message)
        assert match is not None
        outgoing.append((phone, match.group(1)))
        return Submission("accepted_unverified")

    monkeypatch.setattr("app.sponsor_otp.get_settings", lambda: cfg)
    monkeypatch.setattr("app.sponsor_otp.send_text", mock_send)
    def request(person):
        return client.post("/v1/prospects/"+person["id"]+"/otp/request", headers=csrf)
    one = request(first)
    two = request(second)
    denied = request(third)
    assert one.status_code == 200 and two.status_code == 200
    assert denied.status_code == 403
    assert outgoing[0][0] == first["mobile_number"]
    assert outgoing[1][0] == second["mobile_number"]
    assert len(outgoing) == 2
    assert client.get("/v1/prospects/"+first["id"]).json()["crm_stage"] == "inactive"
    activated = client.post("/v1/prospects/"+first["id"]+"/otp/activate",
                            headers=csrf, json={
        "version": first["version"],
        "challenge_id": one.json()["challenge_id"],
        "code": outgoing[0][1],
    })
    assert activated.status_code == 200, activated.text
    assert client.get("/v1/prospects/"+first["id"]).json()["crm_stage"] == "active"
    assert client.get("/v1/prospects/"+second["id"]).json()["crm_stage"] == "inactive"
    assert client.get("/v1/prospects/"+third["id"]).json()["crm_stage"] == "inactive"
    assert len(outgoing) == 2


def test_saasyto_otp_uses_editable_template_and_real_250_multiple(api, monkeypatch):
    from app.sponsor_otp_copy import DEFAULT_OTP_BODY

    client, csrf, engine = api
    a = _create(client, csrf, "Unit One", "+918100000085")
    b = _create(client, csrf, "Unit Two", "+918100000086")
    assert a["monthly_contribution_paise"] == 25_000
    update = client.patch("/v1/prospects/"+b["id"], headers=csrf, json={
        "version": b["version"], "monthly_contribution_paise": 50_000,
    })
    assert update.status_code == 200, update.text
    body = DEFAULT_OTP_BODY.replace("Thank you for taking this step", "JazakAllahu Khairan")
    saved = client.post("/v1/communication/otp-template", headers=csrf, json={
        "version": 0, "body": body,
    })
    assert saved.status_code == 200, saved.text
    monkeypatch.setattr("app.sponsor_otp.get_settings", lambda: SimpleNamespace(
        otp_delivery_enabled=False, otp_saasyto_enabled=True,
        otp_local_pilot_enabled=False, otp_secret=SECRET,
    ))
    sent = []

    def fake_send(_cfg, *, phone, message):
        sent.append((phone, message))
        return Submission("accepted_unverified")

    monkeypatch.setattr("app.sponsor_otp.send_text", fake_send)
    for person in (a,b):
        response = client.post("/v1/prospects/"+person["id"]+"/otp/request", headers=csrf)
        assert response.status_code == 200, response.text
        assert "code" not in response.json()
    assert len(sent) == 2
    assert sent[0][0] == a["mobile_number"]
    assert sent[1][0] == b["mobile_number"]
    assert "₹250 per month" in sent[0][1]
    assert "₹500 per month (2 units at ₹250 each)" in sent[1][1]
    assert "JazakAllahu Khairan" in sent[0][1]
    assert "by the 7th" in sent[1][1]
    assert "{{code}}" not in sent[0][1]
    with Session(engine) as db:
        records = db.scalars(select(SponsorOtpChallenge)).all()
        assert len(records) == 2
        for number, message in sent:
            assert number not in [str(record.code_digest) for record in records]
            assert message not in str(records)


def test_legacy_375_commitment_receives_actual_amount_in_activation_otp(
    api, monkeypatch,
):
    from app.models import Prospect

    client, csrf, engine = api
    person = _create(client, csrf, "Legacy Amount", "+918100000087")
    with Session(engine) as db:
        row = db.get(Prospect, uuid.UUID(person["id"]))
        row.monthly_contribution_paise = 37_500
        db.commit()
    monkeypatch.setattr("app.sponsor_otp.get_settings", lambda: SimpleNamespace(
        otp_delivery_enabled=False, otp_saasyto_enabled=True,
        otp_local_pilot_enabled=False, otp_secret=SECRET,
    ))
    sent = []
    monkeypatch.setattr(
        "app.sponsor_otp.send_text",
        lambda _cfg, *, phone, message:
        sent.append((phone, message)) or Submission("accepted_unverified"),
    )
    response = client.post("/v1/prospects/"+person["id"]+"/otp/request", headers=csrf)
    assert response.status_code == 200, response.text
    assert sent[0][0] == person["mobile_number"]
    assert "₹375 per month" in sent[0][1]
    assert "units at ₹250" not in sent[0][1]
    assert len(sent) == 1


def test_oversized_existing_otp_copy_is_rejected_without_consuming_a_code(
    api, monkeypatch,
):
    from app.models import CommunicationTemplate, Prospect
    from app.sponsor_otp_copy import DEFAULT_OTP_BODY, OTP_TEMPLATE_KEY

    client, csrf, engine = api
    person = _create(client, csrf, "Too Long", "+918100000088")
    monkeypatch.setattr("app.sponsor_otp.get_settings", lambda: SimpleNamespace(
        otp_delivery_enabled=False, otp_saasyto_enabled=True,
        otp_local_pilot_enabled=False, otp_secret=SECRET,
    ))
    # Model stale data that predates the new expansion-size check.
    with Session(engine) as db:
        sponsor = db.get(Prospect, uuid.UUID(person["id"]))
        db.add(CommunicationTemplate(
            organization_id=sponsor.organization_id,
            name="Sponsorship registration OTP", name_key=OTP_TEMPLATE_KEY,
            channel="whatsapp", category="other", subject=None,
            body=DEFAULT_OTP_BODY + " {{name}}" * 8,
            provider_template_id=None, version=1,
        ))
        db.commit()
    called = []
    monkeypatch.setattr(
        "app.sponsor_otp.send_text",
        lambda _cfg, *, phone, message:
        called.append(phone) or Submission("accepted_unverified"),
    )
    response = client.post("/v1/prospects/"+person["id"]+"/otp/request", headers=csrf)
    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "Activation message cannot be prepared"
    assert called == []
    with Session(engine) as db:
        assert db.scalars(select(SponsorOtpChallenge)).all() == []
