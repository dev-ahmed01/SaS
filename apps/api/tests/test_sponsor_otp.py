"""Sponsor OTP: bounded challenge, tenant binding, no delivery claims or consent changes."""
from types import SimpleNamespace

from app.models import SponsorOtpChallenge
from sqlalchemy import select
from sqlalchemy.orm import Session

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


def test_default_off_never_sends(api):
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
        record = db.get(SponsorOtpChallenge, challenge["challenge_id"])
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
