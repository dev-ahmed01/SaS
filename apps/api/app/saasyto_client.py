"""Saasyto direct-text API adapter.

Only the authenticated API server may call the fixed HTTPS endpoint. Nothing in
this module sends without a caller explicitly invoking send_text and providing
a configuration that passed the separate, default-off production approval gate.

Saasyto's public JSON example documents the request fields but not the reply
schema or idempotency guarantees. HTTP 2xx is only submission at the gateway;
it is NOT evidence of a WhatsApp delivery or recipient read.
"""
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
        allowed = (cfg.saasyto_local_test_phone or "").lstrip("+")
        if not allowed or phone.lstrip("+") != allowed:
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
    except (httpx.TimeoutException, httpx.TransportError):
        # Server may have accepted a timed-out request. No blind retry.
        return Submission("unknown")
    if not 200 <= response.status_code < 300:
        return Submission("rejected")
    try:
        receipt = response.json()
    except (ValueError, TypeError):
        # Provider response format not documented. Never infer delivery.
        return Submission("accepted_unverified")
    if isinstance(receipt, dict):
        if receipt.get("success") is False or receipt.get("status") in (
            "error", "failed", "rejected",
        ):
            return Submission("rejected")
    return Submission("accepted_unverified")
