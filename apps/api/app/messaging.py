"""Explicitly gated Pabbly WhatsApp transport. No historical backlog replay.

Pabbly 2xx means accepted, NOT sent or delivered. A signed, unique provider
callback is mandatory before any delivered claim. Uncertain attempts never retry
automatically, since the provider may have accepted a timed-out request.
"""
import hashlib
import hmac
import json
import uuid
from datetime import datetime
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounting import ist_today, month_start
from app.auth import db_session, get_admin
from app.config import get_settings
from app.models import (
    AdminSession,
    AdminUser,
    AuditEvent,
    ManualCollection,
    ManualCollectionReversal,
    MessageDeliveryEvent,
    MessageDispatch,
    MessageOutbox,
    OrganizationSettings,
    Promoter,
    Prospect,
    ReminderIntent,
)
from app.reminders import _build_preview, _settings, current_intent_eligible
from app.security import as_utc, utc_now

admin_router = APIRouter(prefix="/v1/messaging", tags=["Admin message delivery status"])
internal_router = APIRouter(prefix="/internal/messaging", tags=["Private message delivery"])
MAX_PER_RUN = 10


def _ready() -> bool:
    settings = get_settings()
    return bool(settings.messaging_delivery_enabled)


def _sign(payload: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _authenticate(secret: str | None, submitted: str | None) -> None:
    if not secret or not submitted or not hmac.compare_digest(secret, submitted):
        raise HTTPException(status_code=401, detail="Unauthorized delivery operation")


class DeliveryStats(BaseModel):
    delivery_enabled: bool
    operationally_enabled: bool
    awaiting_confirmation_intents: int
    prepared_reminder_intents: int
    accepted_by_provider: int
    sent_confirmed: int
    delivered_confirmed: int
    unresolved_attempts: int
    notice: str


@admin_router.get("/status", response_model=DeliveryStats)
def delivery_status(
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    db: Annotated[Session, Depends(db_session)],
) -> DeliveryStats:
    organization_id=context[0].organization_id
    settings=db.get(OrganizationSettings,organization_id)
    def count(table, *clauses):
        return db.scalar(select(func.count(table.id)).where(*clauses)) or 0
    response.headers["Cache-Control"]="no-store"
    return DeliveryStats(
        delivery_enabled=_ready(),
        operationally_enabled=bool(_ready() and settings and settings.automation_enabled),
        awaiting_confirmation_intents=count(
            MessageOutbox,MessageOutbox.organization_id==organization_id,
            MessageOutbox.status=="awaiting_integration",
        ),
        prepared_reminder_intents=count(
            ReminderIntent,ReminderIntent.organization_id==organization_id,
            ReminderIntent.status=="prepared",
        ),
        accepted_by_provider=count(
            MessageDispatch,MessageDispatch.organization_id==organization_id,
            MessageDispatch.status=="accepted",
        ),
        sent_confirmed=count(
            MessageDispatch,MessageDispatch.organization_id==organization_id,
            MessageDispatch.status=="sent",
        ),
        delivered_confirmed=count(
            MessageDispatch,MessageDispatch.organization_id==organization_id,
            MessageDispatch.status=="delivered",
        ),
        unresolved_attempts=count(
            MessageDispatch,MessageDispatch.organization_id==organization_id,
            MessageDispatch.status.in_(["claimed","unknown","failed"]),
        ),
        notice=(
            "Provider acceptance is not delivery. Only authenticated delivery "
            "callbacks confirm sent/delivered. Previously prepared messages "
            "are never automatically released when integration becomes active."
        ),
    )


def _eligible_and_payload(
    db: Session, dispatch: MessageDispatch, now: datetime,
) -> dict | None:
    """Regenerate message from live ledger and consent; snapshots aren't trusted."""
    org=dispatch.organization_id
    settings=db.scalars(select(OrganizationSettings).where(
        OrganizationSettings.organization_id==org,
    ).with_for_update()).one_or_none()
    cfg=get_settings()
    if not settings or not settings.automation_enabled or not _ready():
        return None
    if as_utc(now) < as_utc(cfg.messaging_enable_after):
        return None
    if dispatch.outbox_id:
        intent=db.get(MessageOutbox, dispatch.outbox_id)
        if not intent or intent.organization_id!=org or intent.status!="awaiting_integration":
            return None
        if as_utc(intent.created_at) < as_utc(cfg.messaging_enable_after):
            return None
        receipt=db.scalars(select(ManualCollection).where(
            ManualCollection.organization_id==org,
            ManualCollection.id==intent.collection_id,
        )).one_or_none()
        if not receipt:
            return None
        reversed_entry=db.scalar(select(ManualCollectionReversal.id).where(
            ManualCollectionReversal.organization_id==org,
            ManualCollectionReversal.collection_id==receipt.id,
        ))
        if reversed_entry is not None:
            return None
        sponsor=db.scalars(select(Prospect).where(
            Prospect.id==receipt.prospect_id,Prospect.organization_id==org,
        ).with_for_update()).one_or_none()
        if not sponsor or sponsor.archived_at or not sponsor.whatsapp_opt_in:
            return None
        phone=sponsor.whatsapp_number or sponsor.mobile_number
        if not phone:
            return None
        return {
            "recipient_phone":phone,
            "template":cfg.whatsapp_template_payment,
            "variables":{
                "name":sponsor.full_name,
                "amount_inr":f"{receipt.amount_paise / 100:.2f}",
                "period_month":receipt.period_month.strftime("%B %Y"),
            },
        }
    intent=db.get(ReminderIntent,dispatch.reminder_intent_id)
    if not intent or intent.organization_id!=org or not intent.status=="prepared":
        return None
    if as_utc(intent.created_at) < as_utc(cfg.messaging_enable_after):
        return None
    admin=db.scalars(select(AdminUser).where(
        AdminUser.organization_id==org,AdminUser.is_active.is_(True),
    )).first()
    if admin is None or not current_intent_eligible(db,admin,intent,now):
        return None
    org_settings=_settings(db,admin)
    preview=_build_preview(db,admin,org_settings,intent.kind,now)
    recipient_id=intent.prospect_id if intent.kind=="sponsor" else intent.promoter_id
    row=next((r for r in preview.recipients if r.recipient_id==recipient_id),None)
    if row is None:
        return None
    if intent.kind=="sponsor":
        sponsor=db.scalars(select(Prospect).where(
            Prospect.organization_id==org,Prospect.id==recipient_id
        ).with_for_update()).one_or_none()
        if not sponsor or not sponsor.whatsapp_opt_in or sponsor.archived_at:
            return None
        return {
            "recipient_phone":sponsor.whatsapp_number or sponsor.mobile_number,
            "template":cfg.whatsapp_template_sponsor,
            "variables":{
                "name":sponsor.full_name,
                "amount_inr":f"{row.outstanding_paise / 100:.2f}",
                "period_month":month_start(ist_today(now)).strftime("%B %Y"),
            },
        }
    if not cfg.promoter_disclosure_approved:
        return None
    promoter=db.scalars(select(Promoter).where(
        Promoter.organization_id==org,Promoter.id==recipient_id
    ).with_for_update()).one_or_none()
    if not promoter or not promoter.is_active or not promoter.whatsapp_opt_in:
        return None
    # Privacy-safe cap: fail closed if a summary would be too large.
    details="; ".join(
        f"{item.full_name} ₹{item.outstanding_paise / 100:.2f}"
        for item in row.unpaid_sponsors
    )
    if len(row.unpaid_sponsors)>20 or len(details)>900:
        return None
    return {
        "recipient_phone":promoter.whatsapp_number or promoter.mobile_number,
        "template":cfg.whatsapp_template_promoter,
        "variables":{
            "name":promoter.full_name,
            "period_month":month_start(ist_today(now)).strftime("%B %Y"),
            "sponsor_count":str(row.sponsor_count),
            "outstanding_inr":f"{row.outstanding_paise / 100:.2f}",
            "sponsor_summary":details,
        },
    }


def _first_candidate(db: Session, after: datetime, now: datetime):
    """Select only new enabled-era messages. No old backlog replay."""
    attempted_outbox=select(MessageDispatch.outbox_id).where(
        MessageDispatch.outbox_id.is_not(None)
    )
    enabled_orgs=select(OrganizationSettings.organization_id).where(
        OrganizationSettings.automation_enabled.is_(True)
    )
    collection=db.scalars(select(MessageOutbox).where(
        MessageOutbox.status=="awaiting_integration",
        MessageOutbox.organization_id.in_(enabled_orgs),
        MessageOutbox.created_at>=after,
        MessageOutbox.id.not_in(attempted_outbox),
    ).order_by(MessageOutbox.created_at,MessageOutbox.id).limit(1)).first()
    if collection is not None:
        return collection, None
    attempted_reminders=select(MessageDispatch.reminder_intent_id).where(
        MessageDispatch.reminder_intent_id.is_not(None)
    )
    reminder=db.scalars(select(ReminderIntent).where(
        ReminderIntent.status=="prepared",
        ReminderIntent.organization_id.in_(enabled_orgs),
        ReminderIntent.created_at>=after,
        ReminderIntent.period_month==month_start(ist_today(now)),
        ReminderIntent.scheduled_on==ist_today(now),
        ReminderIntent.id.not_in(attempted_reminders),
    ).order_by(ReminderIntent.created_at,ReminderIntent.id).limit(1)).first()
    return None,reminder


class DispatchRun(BaseModel):
    attempted: int
    accepted: int
    cancelled: int
    failed: int
    unknown: int
    notice: str


@internal_router.post("/dispatch", response_model=DispatchRun)
def dispatch(
    response: Response,
    db: Annotated[Session, Depends(db_session)],
    runner_token: Annotated[str | None, Header(alias="X-Delivery-Runner-Token")]=None,
) -> DispatchRun:
    cfg=get_settings()
    _authenticate(cfg.messaging_runner_secret, runner_token)
    if not cfg.messaging_delivery_enabled:
        raise HTTPException(status_code=503, detail="Delivery is disabled")
    now=utc_now()
    if now<as_utc(cfg.messaging_enable_after):
        raise HTTPException(status_code=409, detail="Messaging is not yet activated")
    statuses={"accepted":0,"cancelled":0,"failed":0,"unknown":0}
    attempted=0
    for _ in range(MAX_PER_RUN):
        outbox,intent=_first_candidate(db,cfg.messaging_enable_after,utc_now())
        if outbox is None and intent is None:
            break
        org=outbox.organization_id if outbox else intent.organization_id
        dispatch_record=MessageDispatch(
            organization_id=org,
            outbox_id=outbox.id if outbox else None,
            reminder_intent_id=intent.id if intent else None,
            category="collection" if outbox else intent.kind+"_reminder",
            status="claimed",
        )
        db.add(dispatch_record)
        try:
            db.commit()  # persistent at-most-once claim before any network call
        except IntegrityError:
            db.rollback()  # another runner claimed this source
            continue
        attempted+=1
        # Re-check eligibility while locking contact and organization rows.
        payload=_eligible_and_payload(db,dispatch_record,utc_now())
        if payload is None or not payload.get("recipient_phone"):
            dispatch_record.status="cancelled"
            dispatch_record.failure_code="not_eligible"
            dispatch_record.updated_at=utc_now()
            db.commit()
            statuses["cancelled"]+=1
            continue
        payload["correlation_id"]=str(dispatch_record.id)
        payload["idempotency_key"]=str(dispatch_record.id)
        body=json.dumps(payload,separators=(",",":"),ensure_ascii=False).encode()
        try:
            result=httpx.post(
                cfg.pabbly_webhook_url,
                content=body,
                headers={
                    "Content-Type":"application/json",
                    "X-SaS-Signature":_sign(body,cfg.pabbly_signature_secret),
                    "X-SaS-Idempotency-Key":str(dispatch_record.id),
                },
                follow_redirects=False, timeout=8.0,
            )
            if 200<=result.status_code<300:
                status="accepted"
                failure=None
            else:
                status="failed"
                failure="provider_non_2xx"
        except (httpx.HTTPError,OSError):
            # Never auto-retry uncertain sends, even across future worker runs.
            status="unknown"
            failure="provider_unknown"
        if dispatch_record.status=="claimed":
            dispatch_record.status=status
            dispatch_record.failure_code=failure
            dispatch_record.updated_at=utc_now()
        db.add(AuditEvent(
            organization_id=org,actor_admin_id=None,
            action="messaging.provider_attempt",entity_type="message_dispatch",
            entity_id=str(dispatch_record.id),
            after_data={"category":dispatch_record.category,"status":dispatch_record.status},
        ))
        db.commit()
        statuses[status]+=1
    response.headers["Cache-Control"]="no-store"
    return DispatchRun(
        attempted=attempted,notice="Provider 2xx is acceptance, not WhatsApp delivery.",
        **statuses,
    )


class CallbackInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    event_id: str=Field(min_length=8,max_length=128)
    dispatch_id: uuid.UUID
    provider_message_id: str=Field(min_length=3,max_length=128)
    status: Literal["sent","delivered","failed"]


@internal_router.post("/callback")
async def callback(
    request: Request,
    db: Annotated[Session, Depends(db_session)],
) -> dict[str,str]:
    cfg=get_settings()
    raw=await request.body()
    if len(raw)>4096 or not cfg.messaging_callback_secret:
        raise HTTPException(status_code=401,detail="Unauthorized callback")
    expected=_sign(raw,cfg.messaging_callback_secret)
    header=request.headers.get("X-SaS-Callback-Signature","")
    if not hmac.compare_digest(header,expected):
        raise HTTPException(status_code=401,detail="Invalid callback signature")
    try:
        payload=CallbackInput.model_validate_json(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422,detail="Invalid delivery callback") from exc
    record=db.scalars(select(MessageDispatch).where(
        MessageDispatch.id==payload.dispatch_id
    ).with_for_update()).one_or_none()
    if record is None:
        raise HTTPException(status_code=404,detail="Dispatch not found")
    duplicate=db.scalar(select(MessageDeliveryEvent.id).where(
        MessageDeliveryEvent.organization_id==record.organization_id,
        MessageDeliveryEvent.event_id==payload.event_id,
    ))
    if duplicate is not None:
        return {"status":"already_recorded"}
    if record.status=="cancelled":
        raise HTTPException(status_code=409,detail="Cancelled dispatch cannot receive a callback")
    if record.provider_message_id and record.provider_message_id!=payload.provider_message_id:
        raise HTTPException(status_code=409,detail="Provider message ID mismatch")
    if record.status=="delivered" and payload.status!="delivered":
        raise HTTPException(status_code=409,detail="Cannot downgrade delivery")
    if record.status=="sent" and payload.status=="failed":
        raise HTTPException(status_code=409,detail="Cannot downgrade sent receipt")
    db.add(MessageDeliveryEvent(
        organization_id=record.organization_id,dispatch_id=record.id,
        event_id=payload.event_id,status=payload.status,
        provider_message_id=payload.provider_message_id,
    ))
    record.provider_message_id=payload.provider_message_id
    record.status=payload.status
    record.updated_at=utc_now()
    if payload.status=="delivered":
        record.confirmed_at=utc_now()
    db.add(AuditEvent(
        organization_id=record.organization_id,actor_admin_id=None,
        action="messaging.provider_receipt",entity_type="message_dispatch",
        entity_id=str(record.id),
        after_data={"status":payload.status},
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status":"already_recorded"}
    return {"status":"recorded"}
