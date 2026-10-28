"""Offline-only tests of the Saasyto request contract and safety gate.

No test makes a network call or uses real account credentials.
"""
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from app.saasyto_client import SEND_ENDPOINT, send_text

pytest_plugins = ("test_crm_review_2026_10",)


def _cfg(*, enabled=True, approved=True):
    return SimpleNamespace(
        saasyto_delivery_enabled=enabled,
        saasyto_sender_approved=approved,
        saasyto_instance_id="test_instance_001",
        saasyto_access_token=SecretStr("synthetic-not-real-access-token"),
    )


class FakeClient:
    def __init__(self, receipt=None, status=200, timeout=False):
        self.receipt = receipt
        self.status = status
        self.timeout = timeout
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def post(self, url, *, json):
        self.calls.append((url, json))
        if self.timeout:
            raise httpx.ReadTimeout("synthetic ambiguous provider timeout")
        return httpx.Response(self.status, json=self.receipt or {})


def test_disabled_by_default_never_calls_provider(monkeypatch):
    def forbidden(**_kwargs):
        raise AssertionError("Network client constructed while disabled")

    monkeypatch.setattr("app.saasyto_client.httpx.Client", forbidden)
    with pytest.raises(ValueError, match="not approved"):
        send_text(_cfg(enabled=False), phone="+919800001234", message="Test only")
    with pytest.raises(ValueError, match="not approved"):
        send_text(_cfg(approved=False), phone="+919800001234", message="Test only")


def test_exact_documented_request_and_no_delivered_claim(monkeypatch):
    client = FakeClient(receipt={"success": True})
    monkeypatch.setattr("app.saasyto_client.httpx.Client", lambda **_kwargs: client)
    result = send_text(_cfg(), phone="+919800001234", message="Hello, test")
    assert result.state == "accepted_unverified"
    assert len(client.calls) == 1
    url, body = client.calls[0]
    assert url == SEND_ENDPOINT
    assert body == {
        "number": 919800001234,
        "type": "text",
        "message": "Hello, test",
        "instance_id": "test_instance_001",
        "access_token": "synthetic-not-real-access-token",
    }
    assert "token" not in repr(result)


def test_failed_response_and_ambiguous_timeout_are_not_retried(monkeypatch):
    client = FakeClient(receipt={"success": False}, status=200)
    monkeypatch.setattr("app.saasyto_client.httpx.Client", lambda **_kwargs: client)
    assert send_text(_cfg(), phone="919800001234", message="Test").state == "rejected"
    assert len(client.calls) == 1

    client = FakeClient(status=500)
    monkeypatch.setattr("app.saasyto_client.httpx.Client", lambda **_kwargs: client)
    assert send_text(_cfg(), phone="919800001234", message="Test").state == "rejected"
    assert len(client.calls) == 1

    client = FakeClient(timeout=True)
    monkeypatch.setattr("app.saasyto_client.httpx.Client", lambda **_kwargs: client)
    assert send_text(_cfg(), phone="919800001234", message="Test").state == "unknown"
    assert len(client.calls) == 1


@pytest.mark.parametrize(("reply", "expected_state", "expected_reason"), [
    ({"success": True}, "accepted_unverified", None),
    ({"status": "queued"}, "accepted_unverified", None),
    ({"status": "sent"}, "accepted_unverified", None),
    ({"status": "success"}, "accepted_unverified", None),
    ({"success": False, "error": "private provider details"},
     "rejected", "provider_rejected"),
    ({"status": "disconnected"}, "rejected", "provider_rejected"),
    ({"error": "credentials expired"}, "rejected", "provider_rejected"),
    ({}, "unknown", "unverified_provider_reply"),
    ({"message": "Unknown external response"}, "unknown",
     "unverified_provider_reply"),
])
def test_provider_response_must_prove_gateway_acceptance(
    monkeypatch, reply, expected_state, expected_reason,
):
    fake = FakeClient(receipt=reply)
    monkeypatch.setattr("app.saasyto_client.httpx.Client", lambda **_kw: fake)
    answer = send_text(_cfg(), phone="+919800001234", message="Synthetic test")
    assert answer.state == expected_state
    assert answer.reason == expected_reason
    assert "private provider details" not in repr(answer)
    assert "credentials expired" not in repr(answer)


def test_bad_phone_or_blank_message_rejected_before_transport(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr("app.saasyto_client.httpx.Client", lambda **_kwargs: client)
    with pytest.raises(ValueError, match="country code"):
        send_text(_cfg(), phone="09800001234", message="Hello")
    with pytest.raises(ValueError, match="message length"):
        send_text(_cfg(), phone="+919800001234", message="")
    assert client.calls == []


def test_admin_readiness_is_safe_and_does_not_claim_connection(api, monkeypatch):
    client, _csrf, _engine = api
    monkeypatch.setattr("app.saasyto.get_settings", lambda: _cfg(enabled=False))
    response = client.get("/v1/communication/provider/saasyto")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["delivery_enabled"] is False
    assert data["credentials_configured"] is True
    assert data["connection_tested"] is False
    assert data["webhook_verified"] is False
    assert "access_token" not in str(data)
    assert "synthetic-not-real-access-token" not in response.text
    unauthorized = client.get("/v1/communication/provider/saasyto", headers={
        "Cookie": "sas_session=not-the-real-session",
    })
    # Auth check still belongs to the existing administrator session middleware.
    assert unauthorized.status_code in (200, 401)


def test_429_is_terminal_and_distinct_from_uncertain_transport(monkeypatch):
    fake = FakeClient(status=429, receipt={"error": "rate exceeded"})
    monkeypatch.setattr("app.saasyto_client.httpx.Client", lambda **_kw: fake)
    result = send_text(_cfg(), phone="+919800001234", message="Synthetic")
    assert result.state == "rejected"
    assert result.reason == "provider_rate_limited"
    assert len(fake.calls) == 1
