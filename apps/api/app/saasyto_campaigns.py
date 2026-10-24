"""Explicitly approved, tenant-safe Saasyto campaigns and at-most-once runner.

Campaign creation is never send approval. Approval freezes the member set after a
fresh reviewed preparation, and a worker rechecks *live* consent/status/address.
Provider status is only submitted/unknown/failed, never delivered without a
documented, authenticated callback protocol (not yet available).
"""
import hmac
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta
from typing import Annotated, Literal

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
    AdminSession, AdminUser, AuditEvent, CommunicationCampaign,
    CommunicationPreparation, Promoter, Prospect, SaasytoCampaignRecipient,
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


def _existing_run(db: Session, org: uuid.UUID, campaign: uuid.UUID):
    return db.scalars(select(SaasytoCampaignRun).where(
        SaasytoCampaignRun.organization_id == org,
        SaasytoCampaignRun.campaign_id == campaign,
    )).one_or_none()


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
        db, admin.organization_id, candidates, row.channel, row.category,
    )
    eligible = [(person, kind) for person, kind, state, _ in decisions
                if state == "eligible"]
    if (not eligible or len(eligible) > MAX_APPROVAL_RECIPIENTS
            or len(eligible) != payload.expected_eligible
            or len(eligible) != prep.eligible_count):
        raise HTTPException(status_code=409, detail="Audience changed; review again")
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
            recipient_kind=kind, recipient_id=person.id, status="queued",
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
    month = now.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).strftime("%B %Y")
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
        db, run.organization_id, candidates, "whatsapp", row.category,
    )
    if not any(
        p.id == person.id and kind == item.recipient_kind and state == "eligible"
        for p, kind, state, _ in decisions
    ):
        return None
    phone = contact_address(person, "whatsapp")
    message = _render(row.body, person, now)
    return phone, message


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
    counts: Counter[str] = Counter()
    for _ in range(MAX_PER_RUN):
        now = utc_now()
        # Commit each claim *before* the HTTP request: crashes cannot resend it.
        candidate = db.execute(select(SaasytoCampaignRecipient, SaasytoCampaignRun,
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
        ).limit(1).with_for_update(skip_locked=True)).first()
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
                status = send_text(cfg, phone=phone, message=message).state
            except (ValueError, TypeError):
                status = "unknown"
            reason = None if status == "accepted_unverified" else status
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
    response.headers["Cache-Control"] = "no-store"
    return dict(counts)
