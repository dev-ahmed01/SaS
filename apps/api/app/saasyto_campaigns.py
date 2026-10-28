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
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
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
    SaasytoDispatchThrottle,
)
from app.saasyto_client import local_pilot_permits, local_pilot_phones, send_text
from app.saasyto_live_eligibility import live_segment_member, live_whatsapp_permission
from app.security import as_utc, utc_now
from app.sponsorship_policy import SPONSORSHIP_STEP_PAISE

admin_router = APIRouter(prefix="/v1/communication", tags=["Saasyto campaigns"])
internal_router = APIRouter(prefix="/internal/saasyto", tags=["Saasyto private runner"])
MAX_PER_RUN = 10
MAX_APPROVAL_RECIPIENTS = 10000
MAX_DYNAMIC_LOCAL_RECIPIENTS = 500
VALID_TEMPLATE = re.compile(
    r"{{\s*(name|month|sponsorship|sponsorship_amount|sponsorship_units)\s*}}"
)
SPONSOR_TOKENS = re.compile(
    r"{{\s*(sponsorship|sponsorship_amount|sponsorship_units)\s*}}"
)
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
    permitted_phone: str | None = None
    permitted_phones: list[str] = Field(default_factory=list)
    local_dynamic_mode: bool = False
    max_recipients: int = MAX_APPROVAL_RECIPIENTS


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
    dynamic = bool(getattr(cfg, "saasyto_local_dynamic_enabled", False))
    permitted = getattr(cfg, "saasyto_local_test_phone", None) if local else None
    test_phones = local_pilot_phones(cfg) if local else ()
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
            permitted_phone=permitted, permitted_phones=list(test_phones),
            local_dynamic_mode=dynamic,
            max_recipients=(MAX_DYNAMIC_LOCAL_RECIPIENTS if dynamic else
                            MAX_APPROVAL_RECIPIENTS if not local else len(test_phones)),
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
    if SPONSOR_TOKENS.search(row.body) and row.audience != "prospects":
        return result("sponsorship_prospects_only",
                      "Sponsorship details can only be sent to Prospects.")
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
    if dynamic and count > MAX_DYNAMIC_LOCAL_RECIPIENTS:
        return result("local_limit", "Dynamic local testing is limited to 500 recipients.")
    if local:
        if count > len(test_phones):
            return result(
                "local_requires_one" if len(test_phones) == 1 else "local_limit",
                "Local pilot permits at most the explicitly configured "
                "test recipients.",
            )
        if any(not local_pilot_permits(cfg, contact_address(person, "whatsapp"))
               for person, _kind in eligible):
            return result(
                "local_number_mismatch",
                "An eligible contact is not in the local test phone allowlist. "
                "Check SAASYTO_LOCAL_TEST_PHONE and SAASYTO_LOCAL_TEST_PHONE_2, "
                "then restart the API and run Check recipients again.",
            )
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
    if SPONSOR_TOKENS.search(row.body) and row.audience != "prospects":
        raise HTTPException(
            status_code=422, detail="Sponsorship details require Prospects audience"
        )
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
    if getattr(cfg, "saasyto_local_dynamic_enabled", False) and (
        len(eligible) > MAX_DYNAMIC_LOCAL_RECIPIENTS
    ):
        raise HTTPException(status_code=409, detail="Dynamic local pilot exceeds 500 recipients")
    if getattr(cfg, "saasyto_local_test_enabled", False):
        if len(eligible) > len(local_pilot_phones(cfg)) or any(
            not local_pilot_permits(cfg, contact_address(person, "whatsapp"))
            for person, _kind in eligible
        ):
            raise HTTPException(
                status_code=409,
                detail="Local pilot requires consented, allowlisted recipients",
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
    amount = person.monthly_contribution_paise if isinstance(person, Prospect) else None
    units = amount // SPONSORSHIP_STEP_PAISE if amount is not None else None
    replacements = {"name": person.full_name, "month": month}
    if amount is not None and units is not None:
        formatted = f"₹{amount // 100:,}"
        replacements.update({
            "sponsorship_amount": formatted,
            "sponsorship_units": str(units),
            "sponsorship": (
                f"{formatted} per month" +
                (f" ({units} units at ₹250 each)" if units > 1 else "")
            ),
        })

    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if token not in replacements:
            raise ValueError("Sponsorship tokens require a prospect record")
        return replacements[token]

    return VALID_TEMPLATE.sub(replace, body)


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
    if not live_segment_member(
        db, run.organization_id, person, row.audience, row.segment, now,
    ):
        return None
    if not live_whatsapp_permission(
        db, run.organization_id, person, row.category, now,
    ):
        return None
    phone = contact_address(person, "whatsapp")
    cfg = get_settings()
    if getattr(cfg, "saasyto_local_test_enabled", False) and not local_pilot_permits(
        cfg, phone,
    ):
        return None
    if not hmac.compare_digest(
        item.approved_phone_digest, _phone_digest(cfg, phone)
    ):
        return None
    if SPONSOR_TOKENS.search(row.body) and not isinstance(person, Prospect):
        return None
    message = _render(row.body, person, now)
    return phone, message


def _reserve_sender_slot(db: Session, cfg, now: datetime) -> bool:
    """Reserve a global per-instance dispatch slot before any provider I/O.

    The unique row and SELECT FOR UPDATE serialize independent workers in
    PostgreSQL. Reserve in the same transaction as the recipient claim so a
    crash cannot result in replaying a possibly accepted WhatsApp request.
    This is a maximum request frequency, not a provider delivery guarantee.
    """
    sender_id = getattr(cfg, "saasyto_instance_id", None) or "test-sender"
    key = hashlib.sha256(str(sender_id).encode("utf-8")).hexdigest()
    rpm = getattr(cfg, "saasyto_max_attempts_per_minute", 12)
    if type(rpm) is not int or not 1 <= rpm <= 120:
        raise ValueError("Saasyto sender rate must be between 1 and 120 per minute")
    values = {"sender_digest": key, "next_allowed_at": now}
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        stmt = pg_insert(SaasytoDispatchThrottle).values(**values)
    elif dialect == "sqlite":
        stmt = sqlite_insert(SaasytoDispatchThrottle).values(**values)
    else:
        raise RuntimeError("Saasyto throttle requires PostgreSQL or SQLite test DB")
    # No implicit retries or unsafe re-insertion on concurrent worker startup.
    db.execute(stmt.on_conflict_do_nothing(index_elements=["sender_digest"]))
    row = db.scalar(select(SaasytoDispatchThrottle).where(
        SaasytoDispatchThrottle.sender_digest == key,
    ).with_for_update())
    if row is None:
        raise RuntimeError("Saasyto sender throttle missing")
    if as_utc(row.next_allowed_at) > now:
        return False
    row.next_allowed_at = now + timedelta(seconds=60 / rpm)
    return True


def _reconcile_stale_claims(db: Session, now: datetime) -> int:
    """Settle aged in-flight claims as unknown, never as safe to retry.

    A crash after a committed claim might have reached the provider. Do not
    reclaim it automatically. The sender uses a five-second HTTP timeout,
    so fifteen minutes is a conservative stale-claim window.
    """
    cutoff = now - timedelta(minutes=15)
    rows = db.scalars(select(SaasytoCampaignRecipient).where(
        SaasytoCampaignRecipient.status == "claimed",
        SaasytoCampaignRecipient.claimed_at.is_not(None),
        SaasytoCampaignRecipient.claimed_at <= cutoff,
    ).order_by(SaasytoCampaignRecipient.claimed_at).limit(100).with_for_update(
        skip_locked=True,
    )).all()
    if not rows:
        db.rollback()
        return 0
    run_ids = set()
    for item in rows:
        item.status = "unknown"
        item.reason = "worker_interrupted"
        item.finished_at = now
        run_ids.add(item.run_id)
        db.add(AuditEvent(
            organization_id=item.organization_id, actor_admin_id=None,
            action="saasyto.stale_claim_review", entity_type="saasyto_recipient",
            entity_id=str(item.id), after_data={"status": "unknown"},
        ))
    db.flush()
    for run_id in run_ids:
        remaining = db.scalar(select(SaasytoCampaignRecipient.id).where(
            SaasytoCampaignRecipient.run_id == run_id,
            SaasytoCampaignRecipient.status.in_(("queued", "claimed")),
        ).limit(1))
        if remaining is None:
            run = db.get(SaasytoCampaignRun, run_id)
            if run is not None and run.status == "approved":
                run.status = "completed"
    db.commit()
    return len(rows)


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
            db.rollback()
            break
        # The sender-wide rate gate is persisted before the external request.
        # If a slot is not due, release every row lock without claiming.
        # Local allowlisted/dynamic demo sends preserve their separate low-volume
        # pilot behavior; only approved production workers use this global gate.
        local_pilot = (
            getattr(cfg, "saasyto_local_test_enabled", False)
            or getattr(cfg, "saasyto_local_dynamic_enabled", False)
        )
        if not local_pilot and not _reserve_sender_slot(db, cfg, now):
            db.rollback()
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
    """Manual, explicit local send to reviewed, consented CRM contacts, at most once.

    Works in protected localhost allowlisted or dynamic mode only. Production
    and future scheduled campaigns remain private-worker-only.
    """
    cfg = get_settings()
    if not (cfg.saasyto_delivery_enabled and cfg.saasyto_sender_approved):
        raise HTTPException(status_code=503, detail="Saasyto sending is disabled")
    if not (getattr(cfg, "app_env", None) == "development"
            and getattr(cfg, "local_demo_login_enabled", False)
            and (
                getattr(cfg, "saasyto_local_test_enabled", False)
                or getattr(cfg, "saasyto_local_dynamic_enabled", False)
            )):
        raise HTTPException(status_code=403, detail="Manual send requires guarded localhost mode")
    admin = context[0]
    _campaign(db, admin, identifier)
    run = _existing_run(db, admin.organization_id, identifier)
    if run is None:
        raise HTTPException(status_code=409, detail="Approve the campaign before sending")
    limit = (
        MAX_DYNAMIC_LOCAL_RECIPIENTS if getattr(cfg, "saasyto_local_dynamic_enabled", False)
        else len(local_pilot_phones(cfg))
    )
    if run.status != "approved" or not 1 <= run.eligible_count <= limit:
        raise HTTPException(status_code=409, detail="Campaign exceeds local pilot limit")
    if as_utc(run.due_at) > utc_now():
        raise HTTPException(status_code=409, detail="Scheduled campaign is not yet due")
    # Every approved recipient must still be queued. Partial/previous attempts
    # cannot be re-submitted through this endpoint after any claim or rejection.
    states = db.scalars(select(SaasytoCampaignRecipient.status).where(
        SaasytoCampaignRecipient.organization_id == admin.organization_id,
        SaasytoCampaignRecipient.run_id == run.id,
    )).all()
    if len(states) != run.eligible_count or any(state != "queued" for state in states):
        raise HTTPException(status_code=409, detail="Already attempted or no pending send")
    _dispatch_due(db, cfg, target_run_id=run.id, max_attempts=run.eligible_count)
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
    reconciled = _reconcile_stale_claims(db, utc_now())
    counts = _dispatch_due(db, cfg)
    if reconciled:
        counts["unknown"] = counts.get("unknown", 0) + reconciled
    response.headers["Cache-Control"] = "no-store"
    return counts
