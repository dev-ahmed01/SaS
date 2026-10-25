"""Optional, consent-gated Saasyto notice after a consumed OTP activation.

No OTP codes are sent through this adapter. A generic provider acceptance is
not a WhatsApp delivery/read receipt. No delivery or verification is retried.
"""
from sqlalchemy.orm import Session

from app.communication_consent import evaluate_recipients
from app.models import Prospect
from app.saasyto_client import send_text


def send_activation_notice(db: Session, cfg, person: Prospect, *, reactivated: bool) -> str:
    """Submit at most one post-activation notice, only with evidenced permission."""
    if not getattr(cfg, "otp_activation_notice_enabled", False):
        return "disabled"
    candidates = evaluate_recipients(
        db, person.organization_id, [person], "whatsapp", "update",
    )
    if not candidates or candidates[0][2] != "eligible":
        return "suppressed_no_general_consent"
    if not getattr(cfg, "saasyto_delivery_enabled", False):
        return "disabled"
    if not getattr(cfg, "saasyto_sender_approved", False):
        return "disabled"
    phone = person.whatsapp_number or person.mobile_number
    action = "reactivated" if reactivated else "activated"
    try:
        receipt = send_text(
            cfg, phone=phone,
            message=(
                f"Assalamu alaikum, {person.full_name}. "
                "Your Sponsor a Salah registration at Emlen Foundation is now "
                f"{action} after WhatsApp verification. "
                "This confirms your CRM registration status, not a payment. "
                "You can contact the Foundation to change message preferences."
            ),
        )
    except (ValueError, TypeError):
        return "unknown"
    return receipt.state
