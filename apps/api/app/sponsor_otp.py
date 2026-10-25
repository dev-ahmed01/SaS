"""Admin-mediated sponsor WhatsApp OTP, independent of marketing consent.

Production uses approved Meta AUTHENTICATION templates. An explicit, single-
number development pilot may use Saasyto; never as a production OTP sender.
Provider acceptance is not delivery. Plaintext OTP is never persisted.
"""
import hashlib
import hmac
import re
import secrets
import uuid
from datetime import timedelta
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import db_session, get_admin, require_csrf
from app.config import Settings, get_settings
from app.models import (
    AdminSession,
    AdminUser,
    AuditEvent,
    Prospect,
    ProspectStageTransition,
    SponsorOtpChallenge,
)
from app.saasyto_client import send_text
from app.security import as_utc, utc_now

router = APIRouter(prefix="/v1/prospects", tags=["Sponsor WhatsApp verification"])
OTP_MINUTES = 10
COOLDOWN_SECONDS = 60
MAX_ISSUES_PER_DAY = 5
MAX_ATTEMPTS = 5


class OtpConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: uuid.UUID
    code: str = Field(pattern=r"^[0-9]{6}$")


class OtpActivate(OtpConfirm):
    version: int = Field(ge=1)
    reactivation_reason: str | None = Field(default=None, max_length=500)


def _phone(prospect: Prospect) -> str:
    return prospect.whatsapp_number or prospect.mobile_number


def _digest(secret: str, data: str) -> str:
    return hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()


def _code_digest(secret: str, challenge_id: uuid.UUID, phone: str, code: str) -> str:
    return _digest(secret, f"otp:v1:{challenge_id}:{phone}:{code}")


def _load(db: Session, admin: AdminUser, prospect_id: uuid.UUID) -> Prospect:
    record = db.scalars(select(Prospect).where(
        Prospect.organization_id == admin.organization_id,
        Prospect.id == prospect_id,
        Prospect.archived_at.is_(None),
    ).with_for_update()).one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Prospect not found")
    return record


def _enabled(cfg: Settings) -> bool:
    return bool(
        cfg.otp_delivery_enabled or getattr(cfg, "otp_local_pilot_enabled", False)
    )


def _deliver(cfg: Settings, phone: str, code: str) -> None:
    """Deliver only through approved Meta, or one allowlisted local pilot phone."""
    if getattr(cfg, "otp_local_pilot_enabled", False):
        allowed = cfg.saasyto_local_test_phone or ""
        if not allowed or not hmac.compare_digest(phone, allowed):
            raise ValueError("Local OTP recipient is not the allowlisted test phone")
        submission = send_text(
            cfg, phone=phone,
            message=(
                f"Your Sponsor a Salah activation code is {code}. "
                "Valid for 10 minutes. Do not share unless you requested activation."
            ),
        )
        if submission.state != "accepted_unverified":
            raise ValueError("Local OTP provider did not confirm acceptance")
        return
    payload = {
        "messaging_product": "whatsapp",
        "to": phone.lstrip("+"),
        "type": "template",
        "template": {
            "name": cfg.otp_meta_template_name,
            "language": {"code": cfg.otp_meta_template_language},
            "components": [
                {"type": "body", "parameters": [{"type": "text", "text": code}]},
                {
                    "type": "button", "sub_type": "url", "index": "0",
                    "parameters": [{"type": "text", "text": code}],
                },
            ],
        },
    }
    url = (
        "https://graph.facebook.com/" + cfg.otp_meta_graph_version + "/"
        + str(cfg.otp_meta_phone_number_id) + "/messages"
    )
    # Never serialize request payload, phone, code, auth token or provider error.
    with httpx.Client(timeout=httpx.Timeout(8.0)) as client:
        result = client.post(url, json=payload, headers={
            "Authorization": "Bearer " + str(cfg.otp_meta_access_token),
            "Content-Type": "application/json",
        })
    if result.status_code not in (200, 201):
        raise ValueError("OTP provider declined the message")
    try:
        receipt = result.json()
        messages = receipt.get("messages")
        if not isinstance(messages, list) or not messages or not messages[0].get("id"):
            raise ValueError("Missing provider acceptance identifier")
    except (TypeError, AttributeError, IndexError, ValueError) as exc:
        raise ValueError("OTP provider acceptance was not confirmed") from exc


@router.get("/{prospect_id}/otp/status")
def status(
    prospect_id: uuid.UUID,
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
) -> dict[str, bool | str | None]:
    admin = context[0]
    person = _load(database, admin, prospect_id)
    cfg = get_settings()
    response.headers["Cache-Control"] = "no-store"
    return {
        "delivery_enabled": _enabled(cfg),
        "verified": person.whatsapp_verified_at is not None,
        "verified_at": person.whatsapp_verified_at.isoformat()
        if person.whatsapp_verified_at else None,
    }


@router.post("/{prospect_id}/otp/request")
def request_otp(
    prospect_id: uuid.UUID,
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
) -> dict[str, str]:
    cfg = get_settings()
    if not _enabled(cfg) or not cfg.otp_secret:
        raise HTTPException(status_code=503, detail="WhatsApp verification is not configured")
    admin = context[0]
    person = _load(database, admin, prospect_id)
    number = _phone(person)
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", number):
        raise HTTPException(status_code=422, detail="Prospect needs a valid WhatsApp number")
    if getattr(cfg, "otp_local_pilot_enabled", False) and not hmac.compare_digest(
        number, cfg.saasyto_local_test_phone or ""
    ):
        raise HTTPException(
            status_code=403,
            detail="Local OTP pilot permits only the configured test phone",
        )
    now = utc_now()
    phone_digest = _digest(cfg.otp_secret, number)
    # Rate-limit the actual phone across records as well as this sponsor.
    rows = database.scalars(select(SponsorOtpChallenge).where(
        SponsorOtpChallenge.organization_id == admin.organization_id,
        SponsorOtpChallenge.phone_digest == phone_digest,
        SponsorOtpChallenge.created_at >= now - timedelta(days=1),
    ).order_by(SponsorOtpChallenge.created_at.desc()).with_for_update()).all()
    if len(rows) >= MAX_ISSUES_PER_DAY:
        raise HTTPException(status_code=429, detail="Verification limit reached today")
    if rows and as_utc(rows[0].created_at) > now - timedelta(seconds=COOLDOWN_SECONDS):
        raise HTTPException(status_code=429, detail="Retry after the verification cooldown")
    challenge_id = uuid.uuid4()
    code = f"{secrets.randbelow(1000000):06d}"
    record = SponsorOtpChallenge(
        id=challenge_id, organization_id=admin.organization_id,
        prospect_id=prospect_id, phone_digest=phone_digest,
        code_digest=_code_digest(cfg.otp_secret, challenge_id, number, code),
        status="pending", attempts=0,
        created_at=now, expires_at=now + timedelta(minutes=OTP_MINUTES),
    )
    database.add(record)
    database.commit()
    # In a timeout, the provider may have received the request. Do not auto-retry.
    try:
        _deliver(cfg, number, code)
    except httpx.TimeoutException:
        record.status = "unknown"
        database.commit()
        raise HTTPException(status_code=503, detail="OTP delivery outcome unconfirmed") from None
    except (httpx.HTTPError, ValueError):
        record.status = "failed"
        database.commit()
        raise HTTPException(
            status_code=502, detail="WhatsApp provider could not accept OTP"
        ) from None
    record.status = "accepted"
    database.add(AuditEvent(
        organization_id=admin.organization_id, actor_admin_id=admin.id,
        action="prospect.otp_requested", entity_type="prospect",
        entity_id=str(prospect_id), after_data={"challenge_id": str(challenge_id)},
    ))
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"challenge_id": str(challenge_id), "expires_at": record.expires_at.isoformat(),
            "status": "accepted_by_provider"}


@router.post("/{prospect_id}/otp/verify")
def verify_otp(
    prospect_id: uuid.UUID,
    payload: OtpConfirm,
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
) -> dict[str, str]:
    cfg = get_settings()
    if not _enabled(cfg) or not cfg.otp_secret:
        raise HTTPException(status_code=503, detail="WhatsApp verification is not configured")
    admin = context[0]
    person = _load(database, admin, prospect_id)
    record = database.scalars(select(SponsorOtpChallenge).where(
        SponsorOtpChallenge.id == payload.challenge_id,
        SponsorOtpChallenge.organization_id == admin.organization_id,
        SponsorOtpChallenge.prospect_id == prospect_id,
    ).with_for_update()).one_or_none()
    now = utc_now()
    if (
        record is None or record.status != "accepted" or record.consumed_at
        or as_utc(record.expires_at) <= now or record.attempts >= MAX_ATTEMPTS
        or person.whatsapp_verified_at
    ):
        raise HTTPException(status_code=400, detail="Verification is invalid or expired")
    current_phone = _phone(person)
    if not hmac.compare_digest(record.phone_digest, _digest(cfg.otp_secret, current_phone)):
        raise HTTPException(status_code=400, detail="Verification is invalid or expired")
    record.attempts += 1
    expected = _code_digest(cfg.otp_secret, record.id, current_phone, payload.code)
    if not hmac.compare_digest(record.code_digest, expected):
        if record.attempts >= MAX_ATTEMPTS:
            record.status = "locked"
        database.commit()
        raise HTTPException(status_code=400, detail="Incorrect or expired verification code")
    record.consumed_at = now
    record.status = "verified"
    person.whatsapp_verified_at = now
    person.updated_at = now
    person.version += 1
    database.add(AuditEvent(
        organization_id=admin.organization_id, actor_admin_id=admin.id,
        action="prospect.whatsapp_verified", entity_type="prospect",
        entity_id=str(prospect_id), after_data={"challenge_id": str(record.id)},
    ))
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"status": "verified", "verified_at": now.isoformat()}


@router.post("/{prospect_id}/otp/activate")
def activate_after_otp(
    prospect_id: uuid.UUID,
    payload: OtpActivate,
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
) -> dict[str, str | bool]:
    """Consume a fresh OTP and activate in ONE transaction, never by stage PATCH.

    Already-verified numbers must receive a fresh OTP on each reactivation.
    First activation has no reason; prior Active -> Inactive -> Active needs one.
    This does not grant communication consent or change payment status.
    """
    cfg = get_settings()
    if not _enabled(cfg) or not cfg.otp_secret:
        raise HTTPException(status_code=503, detail="WhatsApp OTP is not configured")
    admin = context[0]
    person = _load(database, admin, prospect_id)
    if person.version != payload.version:
        raise HTTPException(status_code=409, detail="Prospect changed; reload and retry")
    if person.crm_stage != "inactive":
        raise HTTPException(status_code=409, detail="Prospect is already active")
    previously_active = database.scalar(select(ProspectStageTransition.id).where(
        ProspectStageTransition.organization_id == admin.organization_id,
        ProspectStageTransition.prospect_id == prospect_id,
        ProspectStageTransition.to_stage == "active",
    ).limit(1)) is not None
    reason = " ".join((payload.reactivation_reason or "").split())
    if previously_active and not 3 <= len(reason) <= 500:
        raise HTTPException(status_code=422, detail="Reactivation reason is required")
    if not previously_active and reason:
        raise HTTPException(status_code=422, detail="First activation needs no reason")

    record = database.scalars(select(SponsorOtpChallenge).where(
        SponsorOtpChallenge.id == payload.challenge_id,
        SponsorOtpChallenge.organization_id == admin.organization_id,
        SponsorOtpChallenge.prospect_id == prospect_id,
    ).with_for_update()).one_or_none()
    now = utc_now()
    if (record is None or record.status != "accepted" or record.consumed_at
            or as_utc(record.expires_at) <= now
            or record.attempts >= MAX_ATTEMPTS
            or (person.crm_stage_changed_at and
                as_utc(record.created_at) < as_utc(person.crm_stage_changed_at))):
        raise HTTPException(status_code=400, detail="Verification is invalid or expired")
    number = _phone(person)
    if not hmac.compare_digest(record.phone_digest, _digest(cfg.otp_secret, number)):
        raise HTTPException(status_code=400, detail="Verification is invalid or expired")
    record.attempts += 1
    expected = _code_digest(cfg.otp_secret, record.id, number, payload.code)
    if not hmac.compare_digest(record.code_digest, expected):
        if record.attempts >= MAX_ATTEMPTS:
            record.status = "locked"
        database.commit()
        raise HTTPException(status_code=400, detail="Incorrect or expired verification code")

    record.status = "verified"
    record.consumed_at = now
    person.whatsapp_verified_at = now
    person.crm_stage = "active"
    person.crm_stage_changed_at = now
    person.crm_inactive_reason = None
    person.crm_inactive_note = None
    person.updated_at = now
    person.version += 1
    database.add(ProspectStageTransition(
        organization_id=admin.organization_id, prospect_id=person.id,
        from_stage="inactive", to_stage="active",
        reason=None, note=reason or None, changed_at=now,
        actor_admin_id=admin.id,
    ))
    database.add(AuditEvent(
        organization_id=admin.organization_id, actor_admin_id=admin.id,
        action="prospect.otp_activated", entity_type="prospect",
        entity_id=str(person.id),
        after_data={"version": person.version, "reactivation": previously_active,
                    "challenge_id": str(record.id)},
    ))
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"status": "active", "reactivation": previously_active}
