"""Synthetic OTP transport for CRM tests; never available from the application."""

from types import SimpleNamespace
from unittest.mock import patch

TEST_SECRET = "synthetic-activation-otp-secret-at-least-32-characters"


def activate_with_test_otp(client, csrf, person, *, reason=None):
    """Exercise real request/activate APIs with a fake outbound WhatsApp provider.

    Return the updated prospect GET response so older business-flow tests keep
    asserting payment, routing, and financial consequences, not transport.
    """
    delivered = []
    base = "/v1/prospects/" + person["id"]
    config = SimpleNamespace(otp_delivery_enabled=True, otp_secret=TEST_SECRET)
    with (
        patch("app.sponsor_otp.get_settings", return_value=config),
        patch("app.sponsor_otp._deliver",
              side_effect=lambda _cfg, phone, code, *_extra: delivered.append(code)),
        patch("app.sponsor_otp.COOLDOWN_SECONDS", 0),
    ):
        issued = client.post(base + "/otp/request", headers=csrf)
        assert issued.status_code == 200, issued.text
        assert len(delivered) == 1
        activated = client.post(base + "/otp/activate", headers=csrf, json={
            "version": person["version"],
            "challenge_id": issued.json()["challenge_id"],
            "code": delivered[0],
            "reactivation_reason": reason,
        })
    if activated.status_code != 200:
        return activated
    return client.get(base)
