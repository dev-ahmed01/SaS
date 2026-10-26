"""Optional one-time Saasyto acknowledgement after verified CRM activation.

This is a general WhatsApp update, not an OTP or a payment receipt.
Recipient permission is re-evaluated at send time. Saasyto acceptance does
not prove delivery or reading; uncertain outcomes are never retried here.
"""

from sqlalchemy.orm import Session

from app.communication_consent import evaluate_recipients
from app.models import Prospect
from app.saasyto_client import local_pilot_permits, send_text
from app.security import as_utc, utc_now


def send_activation_notice(db: Session, cfg, person: Prospect, *, reactivated: bool) -> str:
    """Return an honest submission state, never claim an unverified delivery."""
    if not getattr(cfg, "otp_activation_notice_enabled", False):
        return "disabled"
    if not (
        getattr(cfg, "saasyto_delivery_enabled", False)
        and getattr(cfg, "saasyto_sender_approved", False)
    ):
        return "disabled"
    cutoff = getattr(cfg, "saasyto_enable_after", None)
    if cutoff is None or as_utc(cutoff) > utc_now():
        return "before_sender_activation"

    # A verified number and Active CRM state alone NEVER grant opt-in.
    try:
        decision = evaluate_recipients(
            db, person.organization_id, [person], "whatsapp", "update",
        )
        if len(decision) != 1 or decision[0][2] != "eligible":
            return "suppressed_no_general_consent"
        number = person.whatsapp_number or person.mobile_number
        if getattr(cfg, "saasyto_local_test_enabled", False):
            if not local_pilot_permits(cfg, number):
                return "suppressed_local_test_number"

        action = "reactivated" if reactivated else "activated"
        receipt = send_text(
            cfg, phone=number,
            message=(
                f"Assalamu alaikum, {person.full_name}. "
                f"Your Sponsor a Salah registration with Emlen Foundation is now {action}. "
                "Your WhatsApp number has been verified. "
                "This is a registration update, not a payment confirmation. "
                "Contact the Foundation if you wish to change your message preferences."
            ),
        )
        return receipt.state
    except Exception:
        # Once OTP is consumed and activation committed, a message exception
        # must not turn a successful activation into a misleading HTTP 500.
        return "unknown"
