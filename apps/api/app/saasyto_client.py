"""Saasyto direct-text API adapter.

Only the authenticated API server may call the fixed HTTPS endpoint. Nothing in
this module sends without a caller explicitly invoking send_text and providing
a configuration that passed the separate, default-off production approval gate.

Saasyto's public JSON example documents the request fields but not the reply
schema or idempotency guarantees. HTTP 2xx is only submission at the gateway;
it is NOT evidence of a WhatsApp delivery or recipient read.
"""
import hmac
import re
from dataclasses import dataclass
from typing import Literal

import httpx

from app.config import Settings

SEND_ENDPOINT = "https://web.saasyto.com/api/send"
SendState = Literal["accepted_unverified", "rejected", "unknown"]
PHONE = re.compile(r"^\+?[1-9][0-9]{7,14}$")


@dataclass(frozen=True)
class Submission:
    state: SendState
    """An unverified submission state, never a delivery receipt."""
    reason: str | None = None  # Constant diagnostic; never raw provider JSON.


def local_pilot_phones(cfg: Settings) -> tuple[str, ...]:
    """Explicitly authorized test contacts; never derive from the CRM audience."""
    first = getattr(cfg, "saasyto_local_test_phone", None)
    second = getattr(cfg, "saasyto_local_test_phone_2", None)
    return tuple(phone for phone in (first, second) if phone)


def local_pilot_permits(cfg: Settings, phone: str) -> bool:
    """Check exact, normalized E.164 digits without substring matching."""
    actual = phone.lstrip("+")
    return any(
        hmac.compare_digest(actual, allowed.lstrip("+"))
        for allowed in local_pilot_phones(cfg)
    )


def send_text(cfg: Settings, *, phone: str, message: str) -> Submission:
    """Submit one approved text, never automatically retry timeouts or errors.

    Avoid returning/logging provider JSON: it may contain account identifiers,
    tokens, phone numbers or message content. A 2xx cannot mean delivered.
    """
    if not cfg.saasyto_delivery_enabled or not cfg.saasyto_sender_approved:
        raise ValueError("Saasyto sending not approved")
    if not cfg.saasyto_instance_id or not cfg.saasyto_access_token:
        raise ValueError("Saasyto sender credentials unavailable")
    if not PHONE.fullmatch(phone):
        raise ValueError("Recipient number must be E.164 with a country code")
    if getattr(cfg, "saasyto_local_test_enabled", False):
        if not local_pilot_permits(cfg, phone):
            raise ValueError("Local pilot recipient is not allowlisted")
    if not message or len(message) > 1200:
        raise ValueError("Invalid outgoing message length")
    token = cfg.saasyto_access_token.get_secret_value()
    payload = {
        "number": int(phone.lstrip("+")),
        "type": "text",
        "message": message,
        "instance_id": cfg.saasyto_instance_id,
        "access_token": token,
    }
    try:
        with httpx.Client(
            timeout=httpx.Timeout(5.0),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.post(SEND_ENDPOINT, json=payload)
    except httpx.TimeoutException:
        # Provider may already have accepted the attempt. No blind retry.
        return Submission("unknown", "provider_timeout")
    except httpx.TransportError:
        return Submission("unknown", "network_error")
    if not 200 <= response.status_code < 300:
        return Submission("rejected", "provider_http_error")
    try:
        receipt = response.json()
    except (ValueError, TypeError):
        return Submission("unknown", "unverified_provider_reply")
    if not isinstance(receipt, dict):
        return Submission("unknown", "unverified_provider_reply")
    # A 2xx HTML page, a truthy error field, or a soft-fail JSON object must
    # NEVER be displayed as "successfully submitted" in the CRM.
    state = str(receipt.get("status", "")).strip().lower()
    success = receipt.get("success")
    if (success is False or success == 0 or
            state in ("error", "failed", "failure", "rejected",
                      "disconnected", "invalid") or
            bool(receipt.get("error"))):
        return Submission("rejected", "provider_rejected")
    if success is True or state in (
        "success", "submitted", "accepted", "queued", "pending", "sent",
    ):
        # Still no proof of WhatsApp delivery or reads.
        return Submission("accepted_unverified")
    return Submission("unknown", "unverified_provider_reply")
