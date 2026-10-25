"""Explicitly approved, tenant-safe Saasyto campaigns and at-most-once runner.

Campaign creation is never send approval. Approval freezes the member set after a
fresh reviewed preparation, and a worker rechecks *live* consent/status/address.
Provider status is only submitted/unknown/failed, never delivered without a
documented, authenticated callback protocol (not yet available).
"""
import hashlib
import hmac
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import db_session, get_admin, require_csrf
from app.communication import _audience_rows
from app.communication_consent import contact_address, evaluate_recipients
from app.config import get_settings
from app.models import (
    AdminSession,
    AdminUser,
    AuditEvent,
    CommunicationCampaign,
    CommunicationPreparation,
    CommunicationRecipientSnapshot,
    Promoter,
    Prospect,
    SaasytoCampaignRecipient,
    SaasytoCampaignRun,
)
from app.saasyto_client import send_text
from app.security import as_utc, utc_now

admin_router = APIRouter(prefix="/v1/communication", tags=["Saasyto campaigns"])
internal_router = APIRouter(prefix="/internal/saasyto", tags=["Saasyto private runner"])
MAX_PER_RUN = 10
MAX_APPROVAL_RECIPIENTS = 500
VALID_TEMPLATE = re.compile(r"{{\s*(name|month)\s*}}")
UNKNOWN_TOKEN = re.compile(r"{{.*?}}")


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preparation_id: uuid.UUID
    expected_eligible: int = Field(ge=1, le=MAX_APPROVAL_RECIPIENTS)
    confirm_send: Literal[True]


class CampaignRunRead(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    status: str
    due_at: datetime
    eligible_count: int
    suppressed_count: int
    queued: int
    claimed: int
    accepted_unverified: int
    rejected: int
    unknown: int
    suppressed_after_approval: int
    notice: str = (
        "Gateway acceptance is not WhatsApp delivery. Unknown outcomes must "
        "not be automatically retried."
    )


def _read(db: Session, run: SaasytoCampaignRun) -> CampaignRunRead:
    counts = Counter(db.scalars(select(SaasytoCampaignRecipient.status).where(
        SaasytoCampaignRecipient.organization_id == run.organization_id,
        SaasytoCampaignRecipient.run_id == run.id,
    )).all())
    return CampaignRunRead(
        id=run.id, campaign_id=run.campaign_id, status=run.status,
        due_at=run.due_at, eligible_count=run.eligible_count,
        suppressed_count=run.suppressed_count, queued=counts["queued"],
        claimed=counts["claimed"], accepted_unverified=counts["accepted_unverified"],
        rejected=counts["rejected"], unknown=counts["unknown"],
        suppressed_after_approval=counts["suppressed"],
    )


def _campaign(db: Session, admin: AdminUser, identifier: uuid.UUID):
    row = db.scalars(select(CommunicationCampaign).where(
        CommunicationCampaign.organization_id == admin.organization_id,
        CommunicationCampaign.id == identifier,
    ).with_for_update()).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return row


def _phone_digest(cfg, address: str) -> str:
    secret = cfg.saasyto_runner_secret.get_secret_value()
    return hmac.new(secret.encode(), address.encode(), hashlib.sha256).hexdigest()


def _existing_run(db: Session, org: uuid.UUID, campaign: uuid.UUID):
    return db.scalars(select(SaasytoCampaignRun).where(
        SaasytoCampaignRun.organization_id == org,
        SaasytoCampaignRun.campaign_id == campaign,
    )).one_or_none()


def _reviewed_eligible(
    db: Session, organization_id: uuid.UUID, preparation_id: uuid.UUID,
) -> set[tuple[str, uuid.UUID]]:
    """Identify actual reviewed contacts; counts cannot authorize a swapped donor."""
    return set(db.execute(select(
        CommunicationRecipientSnapshot.recipient_kind,
        CommunicationRecipientSnapshot.recipient_id,
    ).where(
        CommunicationRecipientSnapshot.organization_id == organization_id,
        CommunicationRecipientSnapshot.preparation_id == preparation_id,
        CommunicationRecipientSnapshot.status == "eligible",
    )).all())


@admin_router.get("/campaigns/{identifier}/saasyto", response_model=CampaignRunRead | None)
def campaign_run(
    identifier: uuid.UUID, response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    db: Annotated[Session, Depends(db_session)],
):
    admin = context[0]
    _campaign(db, admin, identifier)
    response.headers["Cache-Control"] = "no-store"
    run = _existing_run(db, admin.organization_id, identifier)
    return _read(db, run) if run else None


class CampaignApprovalReadiness(BaseModel):
    ready: bool
    code: str
    message: str
    eligible_count: int
    local_test_mode: bool
    permitted_phone_masked: str | None = None


@admin_router.get("/campaigns/{identifier}/saasyto/readiness",
                  response_model=CampaignApprovalReadiness)
def campaign_approval_readiness(
    identifier: uuid.UUID, response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    db: Annotated[Session, Depends(db_session)],
) -> CampaignApprovalReadiness:
    """Read-only eligibility check with actionable blockers, never a send.

    Checks are advisory and are re-evaluated at approval and actual dispatch.
    Keep complete recipient numbers and backend credentials out of replies.
    """
    cfg = get_settings()
    admin = context[0]
    row = _campaign(db, admin, identifier)
    now = utc_now()
    local = bool(getattr(cfg, "saasyto_local_test_enabled", False))
    allowlisted = (getattr(cfg, "saasyto_local_test_phone", None) or "").lstrip("+")
    masked = "•••• " + allowlisted[-4:] if local and len(allowlisted) >= 4 else None
    preparation = db.scalars(select(CommunicationPreparation).where(
        CommunicationPreparation.organization_id == admin.organization_id,
        CommunicationPreparation.campaign_id == row.id,
    ).order_by(CommunicationPreparation.evaluated_at.desc()).limit(1)).first()
    candidates = _audience_rows(db, admin, row.audience, row.segment, now)
    decisions = evaluate_recipients(
        db, admin.organization_id, candidates, row.channel, row.category, now=now,
    )
    eligible = [(person, kind) for person, kind, state, _ in decisions
                if state == "eligible"]
    count = len(eligible)

    def result(code: str, message: str) -> CampaignApprovalReadiness:
        return CampaignApprovalReadiness(
            ready=code == "ready", code=code, message=message,
            eligible_count=count, local_test_mode=local,
            permitted_phone_masked=masked,
        )

    response.headers["Cache-Control"] = "no-store"
    if not cfg.saasyto_delivery_enabled or not cfg.saasyto_sender_approved:
        return result("sending_disabled",
                      "WhatsApp sending is disabled in API settings. "
                      "Enable it only after sender and recipient permissions are verified.")
    if row.status == "cancelled" or row.channel != "whatsapp":
        return result("invalid_campaign", "Only an active WhatsApp campaign can be sent.")
    if _existing_run(db, admin.organization_id, identifier):
        return result("already_approved",
                      "This campaign already has a delivery attempt or approval. "
                      "Check its results; do not create a duplicate send.")
    cutoff = getattr(cfg, "saasyto_enable_after", None)
    if cutoff is None or as_utc(row.created_at) < as_utc(cutoff):
        return result("before_activation",
                      "This campaign predates Saasyto activation. "
                      "Create a new campaign after activation.")
    if UNKNOWN_TOKEN.search(VALID_TEMPLATE.sub("", row.body)):
        return result("invalid_template",
                      "Message contains an unsupported {{placeholder}}.")
    if preparation is None:
        return result("no_recipient_check", "Click Check recipients before sending.")
    if as_utc(preparation.evaluated_at) < now - timedelta(minutes=15):
        return result("stale_recipient_check",
                      "Recipient check expired. Click Check recipients again.")
    if count == 0:
        return result("no_eligible_contacts",
                      "No eligible contacts. Review consent, opt-outs and active status.")
    if (count > MAX_APPROVAL_RECIPIENTS or count != preparation.eligible_count
            or {(kind, person.id) for person, kind in eligible} != _reviewed_eligible(
                db, admin.organization_id, preparation.id,
            )):
        return result("audience_changed",
                      "Eligible contacts changed since the last check. "
                      "Click Check recipients again.")
    if local:
        if count != 1:
            return result("local_requires_one",
                          "Local pilot requires exactly one eligible recipient.")
        actual = contact_address(eligible[0][0], "whatsapp").lstrip("+")
        if not allowlisted or not hmac.compare_digest(actual, allowlisted):
            return result("local_number_mismatch",
                          "The one eligible contact does not match the permitted "
                          "local test number. Check the contact's WhatsApp number "
                          "against SAASYTO_LOCAL_TEST_PHONE in the API .env, "
                          "then restart the API and run Check recipients again.")
    return result("ready", "Recipient check passed. Sending still requires your approval.")


@admin_router.post("/campaigns/{identifier}/saasyto", response_model=CampaignRunRead,
                   status_code=201)
def approve_campaign(
    identifier: uuid.UUID, payload: Approval, response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    db: Annotated[Session, Depends(db_session)],
):
    cfg = get_settings()
    if not cfg.saasyto_delivery_enabled or not cfg.saasyto_sender_approved:
        raise HTTPException(status_code=503, detail="Saasyto dispatch is disabled")
    admin = context[0]
    row = _campaign(db, admin, identifier)
    now = utc_now()
    if row.status == "cancelled" or row.channel != "whatsapp":
        raise HTTPException(status_code=409, detail="Campaign cannot use Saasyto")
    if as_utc(row.created_at) < as_utc(cfg.saasyto_enable_after):
        raise HTTPException(status_code=409, detail="Older campaigns require new approval plans")
    if _existing_run(db, admin.organization_id, identifier):
        raise HTTPException(status_code=409, detail="Campaign already approved or completed")
    if UNKNOWN_TOKEN.search(VALID_TEMPLATE.sub("", row.body)):
        raise HTTPException(status_code=422, detail="Unsupported message placeholder")
    prep = db.scalars(select(CommunicationPreparation).where(
        CommunicationPreparation.organization_id == admin.organization_id,
        CommunicationPreparation.campaign_id == row.id,
        CommunicationPreparation.id == payload.preparation_id,
    )).one_or_none()
    if prep is None or as_utc(prep.evaluated_at) < now - timedelta(minutes=15):
        raise HTTPException(status_code=409, detail="Refresh recipient check before approval")
    candidates = _audience_rows(
        db, admin, row.audience, row.segment, now,
    )
    decisions = evaluate_recipients(
        db, admin.organization_id, candidates, row.channel, row.category, now=now,
    )
    eligible = [(person, kind) for person, kind, state, _ in decisions
                if state == "eligible"]
    if (not eligible or len(eligible) > MAX_APPROVAL_RECIPIENTS
            or len(eligible) != payload.expected_eligible
            or len(eligible) != prep.eligible_count
            or {(kind, person.id) for person, kind in eligible} != _reviewed_eligible(
                db, admin.organization_id, prep.id,
            )):
        raise HTTPException(status_code=409, detail="Audience changed; review again")
    if getattr(cfg, "saasyto_local_test_enabled", False):
        allowed = (cfg.saasyto_local_test_phone or "").lstrip("+")
        if len(eligible) != 1 or any(
            contact_address(person, "whatsapp").lstrip("+") != allowed
            for person, _kind in eligible
        ):
            raise HTTPException(
                status_code=409,
                detail="Local pilot requires one consented, allowlisted recipient",
            )
    run = SaasytoCampaignRun(
        organization_id=admin.organization_id, campaign_id=row.id,
        approved_by_admin_id=admin.id, approved_at=now,
        due_at=max(now, as_utc(row.planned_for)) if row.planned_for else now,
        status="approved", eligible_count=len(eligible),
        suppressed_count=len(decisions) - len(eligible),
    )
    db.add(run)
    db.flush()
    for person, kind in eligible:
        db.add(SaasytoCampaignRecipient(
            organization_id=admin.organization_id, run_id=run.id,
            recipient_kind=kind, recipient_id=person.id,
            approved_phone_digest=_phone_digest(
                cfg, contact_address(person, "whatsapp")
            ), status="queued",
        ))
    db.add(AuditEvent(
        organization_id=admin.organization_id, actor_admin_id=admin.id,
        action="saasyto.campaign_approved", entity_type="saasyto_run",
        entity_id=str(run.id), after_data={
            "recipients": len(eligible), "scheduled": run.due_at > now,
        },
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Campaign already approved") from exc
    response.headers["Cache-Control"] = "no-store"
    return _read(db, run)


@admin_router.post("/campaigns/{identifier}/saasyto/cancel",
                   response_model=CampaignRunRead)
def cancel_campaign_run(
    identifier: uuid.UUID, response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    db: Annotated[Session, Depends(db_session)],
):
    admin = context[0]
    _campaign(db, admin, identifier)
    run = _existing_run(db, admin.organization_id, identifier)
    if not run:
        raise HTTPException(status_code=404, detail="No Saasyto approval exists")
    if run.status == "approved":
        run.status = "cancelled"
        for item in db.scalars(select(SaasytoCampaignRecipient).where(
            SaasytoCampaignRecipient.run_id == run.id,
            SaasytoCampaignRecipient.status == "queued",
        ).with_for_update()):
            item.status = "suppressed"
            item.reason = "campaign_cancelled"
            item.finished_at = utc_now()
        db.add(AuditEvent(
            organization_id=admin.organization_id, actor_admin_id=admin.id,
            action="saasyto.campaign_cancelled", entity_type="saasyto_run",
            entity_id=str(run.id),
        ))
        db.commit()
    response.headers["Cache-Control"] = "no-store"
    return _read(db, run)


def _render(body: str, person: Prospect | Promoter, now: datetime) -> str:
    month = now.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%B %Y")
    return VALID_TEMPLATE.sub(
        lambda match: person.full_name if match.group(1) == "name" else month,
        body,
    )


def _eligible_live(db: Session, run: SaasytoCampaignRun,
                   item: SaasytoCampaignRecipient, row: CommunicationCampaign,
                   now: datetime) -> tuple[str, str] | None:
    model = Prospect if item.recipient_kind == "prospect" else Promoter
    person = db.scalars(select(model).where(
        model.organization_id == run.organization_id,
        model.id == item.recipient_id,
    )).one_or_none()
    if not person:
        return None
    if (isinstance(person, Prospect) and person.archived_at is not None) or (
        isinstance(person, Promoter) and not person.is_active
    ):
        return None
    candidates = _audience_rows(
        db,
        type("Org", (), {"organization_id": run.organization_id})(),
        row.audience, row.segment, now,
    )
    if not any(isinstance(p, model) and p.id == person.id for p in candidates):
        return None
    decisions = evaluate_recipients(
        db, run.organization_id, candidates, "whatsapp", row.category, now=now,
    )
    if not any(
        p.id == person.id and kind == item.recipient_kind and state == "eligible"
        for p, kind, state, _ in decisions
    ):
        return None
    phone = contact_address(person, "whatsapp")
    cfg = get_settings()
    if getattr(cfg, "saasyto_local_test_enabled", False) and not hmac.compare_digest(
        phone.lstrip("+"), (cfg.saasyto_local_test_phone or "").lstrip("+")
    ):
        return None
    if not hmac.compare_digest(
        item.approved_phone_digest, _phone_digest(cfg, phone)
    ):
        return None
    message = _render(row.body, person, now)
    return phone, message


def _dispatch_due(db: Session, cfg, *, target_run_id: uuid.UUID | None = None,
                  max_attempts: int = MAX_PER_RUN) -> dict[str, int]:
    """Claim once then submit; used by the private worker and one-phone manual pilot.

    A targeted manual request cannot consume other campaigns' queued recipients.
    Every claim is committed before network I/O, including uncertain outcomes.
    """
    counts: Counter[str] = Counter()
    for _ in range(max_attempts):
        now = utc_now()
        # Commit each claim *before* the HTTP request: crashes cannot resend it.
        query = select(SaasytoCampaignRecipient, SaasytoCampaignRun,
                                      CommunicationCampaign).join(
            SaasytoCampaignRun,
            SaasytoCampaignRecipient.run_id == SaasytoCampaignRun.id,
        ).join(
            CommunicationCampaign,
            SaasytoCampaignRun.campaign_id == CommunicationCampaign.id,
        ).where(
            SaasytoCampaignRecipient.organization_id == SaasytoCampaignRun.organization_id,
            SaasytoCampaignRecipient.status == "queued",
            SaasytoCampaignRun.status == "approved",
            SaasytoCampaignRun.due_at <= now,
            SaasytoCampaignRun.approved_at >= cfg.saasyto_enable_after,
            CommunicationCampaign.status != "cancelled",
        ).order_by(
            SaasytoCampaignRun.due_at, SaasytoCampaignRecipient.id,
        ).limit(1).with_for_update(skip_locked=True)
        if target_run_id is not None:
            query = query.where(SaasytoCampaignRecipient.run_id == target_run_id)
        candidate = db.execute(query).first()
        if not candidate:
            break
        item, run, campaign = candidate
        item.status = "claimed"
        item.claimed_at = now
        db.commit()
        counts["claimed"] += 1
        # An already claimed item can never be picked up automatically again.
        # Re-fetch campaign status and recipient eligibility after committing.
        db.refresh(run)
        db.refresh(campaign)
        if run.status != "approved" or campaign.status == "cancelled":
            eligibility = None
        else:
            eligibility = _eligible_live(db, run, item, campaign, utc_now())
        if not eligibility:
            status, reason = "suppressed", "consent_or_status_changed"
        else:
            phone, message = eligibility
            try:
                submission = send_text(cfg, phone=phone, message=message)
                status = submission.state
                reason = submission.reason or (
                    None if status == "accepted_unverified" else status
                )
            except (ValueError, TypeError):
                status, reason = "unknown", "invalid_send_request"
        db.refresh(item)
        if item.status == "claimed":
            item.status = status
            item.reason = reason
            item.finished_at = utc_now()
            db.add(AuditEvent(
                organization_id=run.organization_id, actor_admin_id=None,
                action="saasyto.recipient_attempt", entity_type="saasyto_recipient",
                entity_id=str(item.id), after_data={"status": status},
            ))
            db.commit()
        counts[status] += 1
        # Close completed runs, including suppressed/rejected/unknown attempts.
        remaining = db.scalar(select(SaasytoCampaignRecipient.id).where(
            SaasytoCampaignRecipient.run_id == run.id,
            SaasytoCampaignRecipient.status.in_(("queued", "claimed")),
        ).limit(1))
        if remaining is None and run.status == "approved":
            run.status = "completed"
            db.commit()
    return dict(counts)


@admin_router.post("/campaigns/{identifier}/saasyto/send-now",
                   response_model=CampaignRunRead)
def send_now_local_pilot(
    identifier: uuid.UUID, response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    db: Annotated[Session, Depends(db_session)],
) -> CampaignRunRead:
    """Explicitly dispatch ONE previously approved local pilot recipient.

    This is not available for production, a future scheduled campaign, or bulk
    sends. The private worker remains the production/scheduled transport.
    """
    cfg = get_settings()
    if not (cfg.saasyto_delivery_enabled and cfg.saasyto_sender_approved):
        raise HTTPException(status_code=503, detail="Saasyto sending is disabled")
    if not (getattr(cfg, "app_env", None) == "development"
            and getattr(cfg, "local_demo_login_enabled", False)
            and getattr(cfg, "saasyto_local_test_enabled", False)):
        raise HTTPException(status_code=403, detail="Manual send requires local test mode")
    admin = context[0]
    _campaign(db, admin, identifier)
    run = _existing_run(db, admin.organization_id, identifier)
    if run is None:
        raise HTTPException(status_code=409, detail="Approve the campaign before sending")
    if run.status != "approved" or run.eligible_count != 1:
        raise HTTPException(status_code=409, detail="Campaign not eligible for one-phone send")
    if as_utc(run.due_at) > utc_now():
        raise HTTPException(status_code=409, detail="Scheduled campaign is not yet due")
    # Checking for exactly one queued recipient prevents this endpoint from
    # being used as a replay/retry mechanism after a claim or rejection.
    states = db.scalars(select(SaasytoCampaignRecipient.status).where(
        SaasytoCampaignRecipient.organization_id == admin.organization_id,
        SaasytoCampaignRecipient.run_id == run.id,
    )).all()
    if states != ["queued"]:
        raise HTTPException(status_code=409, detail="Already attempted or no pending send")
    _dispatch_due(db, cfg, target_run_id=run.id, max_attempts=1)
    db.refresh(run)
    response.headers["Cache-Control"] = "no-store"
    return _read(db, run)


@internal_router.post("/dispatch")
def run_due(
    response: Response,
    db: Annotated[Session, Depends(db_session)],
    runner_token: Annotated[str | None, Header(alias="X-Saasyto-Runner-Token")] = None,
) -> dict[str, int]:
    cfg = get_settings()
    secret = (
        cfg.saasyto_runner_secret.get_secret_value()
        if cfg.saasyto_runner_secret else ""
    )
    if not secret or not runner_token or not hmac.compare_digest(secret, runner_token):
        raise HTTPException(status_code=401, detail="Unauthorized runner")
    if not cfg.saasyto_delivery_enabled or not cfg.saasyto_sender_approved:
        raise HTTPException(status_code=503, detail="Saasyto delivery disabled")
    counts = _dispatch_due(db, cfg)
    response.headers["Cache-Control"] = "no-store"
    return counts
