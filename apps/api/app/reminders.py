"""Deterministic IST WhatsApp reminder eligibility and preparation only.

No delivery transport exists in this module. A later sender MUST revalidate
consent, sponsor status, outstanding balance and promoter assignments at send time.
"""
import uuid
from collections import defaultdict
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounting import (
    effective_credits,
    evaluate_status,
    ist_today,
    month_start,
    period_balance,
)
from app.auth import db_session, get_admin, require_csrf
from app.communication_consent import evaluate_recipients
from app.models import (
    AdminSession,
    AdminUser,
    AuditEvent,
    MessageDispatch,
    OrganizationSettings,
    Promoter,
    PromoterAssignment,
    Prospect,
    ReminderBatch,
    ReminderIntent,
    SponsorshipRate,
)
from app.security import utc_now

router = APIRouter(prefix="/v1/reminders", tags=["Admin reminder eligibility"])
ReminderKind = Literal["sponsor", "promoter"]
MAX_SPONSORS = 12000
MAX_RECIPIENTS = 12000


class UnpaidSponsor(BaseModel):
    prospect_id: uuid.UUID
    full_name: str
    outstanding_paise: int


class ReminderRecipient(BaseModel):
    recipient_id: uuid.UUID
    recipient_name: str
    sponsor_count: int
    outstanding_paise: int
    unpaid_sponsors: list[UnpaidSponsor]


class ReminderPreview(BaseModel):
    kind: ReminderKind
    period_month: date
    today_ist: date
    scheduled_on: date
    is_due_today: bool
    currency: Literal["INR"]
    timezone: Literal["Asia/Kolkata"]
    eligible_recipients: int
    unpaid_sponsors: int
    total_outstanding_paise: int
    recipients: list[ReminderRecipient]
    notice: str


class PrepareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: ReminderKind
    request_id: uuid.UUID


class BatchRead(BaseModel):
    id: uuid.UUID
    kind: ReminderKind
    period_month: date
    scheduled_on: date
    recipient_count: int
    status: Literal["prepared", "partially_delivered", "delivered"]
    delivered_count: int


class BatchPage(BaseModel):
    items: list[BatchRead]
    total: int
    limit: int
    offset: int


def _settings(
    database: Session, admin: AdminUser, lock: bool = False,
) -> OrganizationSettings:
    query = select(OrganizationSettings).where(
        OrganizationSettings.organization_id == admin.organization_id
    )
    if lock:
        query = query.with_for_update()
    settings = database.scalars(query).one_or_none()
    if settings is None or (
        settings.timezone != "Asia/Kolkata" or settings.currency_code != "INR"
    ):
        raise HTTPException(status_code=503, detail="Reminder locale is unavailable")
    return settings


def _schedule(settings: OrganizationSettings, kind: ReminderKind, today: date) -> date:
    day = (
        settings.sponsor_reminder_day
        if kind == "sponsor" else settings.promoter_reminder_day
    )
    return month_start(today).replace(day=day)


def _eligible_unpaid(
    database: Session, admin: AdminUser, settings: OrganizationSettings,
    today: date, now: datetime,
) -> tuple[dict[uuid.UUID, UnpaidSponsor], dict[uuid.UUID, Prospect]]:
    sponsors = list(database.scalars(select(Prospect).where(
        Prospect.organization_id == admin.organization_id,
        Prospect.archived_at.is_(None),
        Prospect.crm_stage == "active",
    ).order_by(Prospect.id).limit(MAX_SPONSORS + 1)).all())
    if len(sponsors) > MAX_SPONSORS:
        raise HTTPException(
            status_code=409,
            detail="Too many sponsors for a single reminder batch. No reminders prepared",
        )
    rates_by_sponsor = defaultdict(list)
    for rate in database.scalars(select(SponsorshipRate).where(
        SponsorshipRate.organization_id == admin.organization_id,
    )):
        rates_by_sponsor[rate.prospect_id].append(rate)
    credits_by_sponsor = defaultdict(list)
    for credit in effective_credits(database, admin.organization_id, as_of=now):
        credits_by_sponsor[credit.prospect_id].append(credit)
    unpaid: dict[uuid.UUID, UnpaidSponsor] = {}
    sponsor_map: dict[uuid.UUID, Prospect] = {}
    current = month_start(today)
    for sponsor in sponsors:
        if sponsor.start_month is None or sponsor.start_month > current:
            continue
        rates = rates_by_sponsor[sponsor.id]
        credits = credits_by_sponsor[sponsor.id]
        status = evaluate_status(
            sponsor, rates, credits, today, now, settings.inactivity_months
        )
        # Never rely on the materialized Prospects status cache for reminders.
        if status == "inactive":
            continue
        due, _, outstanding, fully_paid = period_balance(
            sponsor, rates, credits, current, now,
        )
        if due <= 0 or fully_paid or outstanding <= 0:
            continue
        unpaid[sponsor.id] = UnpaidSponsor(
            prospect_id=sponsor.id, full_name=sponsor.full_name,
            outstanding_paise=outstanding,
        )
        sponsor_map[sponsor.id] = sponsor
    return unpaid, sponsor_map


def _build_preview(
    database: Session, admin: AdminUser,
    settings: OrganizationSettings, kind: ReminderKind, now: datetime,
) -> ReminderPreview:
    today = ist_today(now)
    scheduled_on = _schedule(settings, kind, today)
    unpaid, sponsor_map = _eligible_unpaid(database, admin, settings, today, now)
    recipients: list[ReminderRecipient] = []

    if kind == "sponsor":
        decisions = evaluate_recipients(
            database, admin.organization_id, list(sponsor_map.values()),
            "whatsapp", "reminder", now=now,
        )
        eligible_ids = {
            person.id for person, _, state, _ in decisions if state == "eligible"
        }
        for sponsor_id, person in unpaid.items():
            if sponsor_id not in eligible_ids:
                continue
            recipients.append(ReminderRecipient(
                recipient_id=sponsor_id, recipient_name=person.full_name,
                sponsor_count=1, outstanding_paise=person.outstanding_paise,
                unpaid_sponsors=[person],
            ))
    else:
        promoters = {
            row.id: row for row in database.scalars(select(Promoter).where(
                Promoter.organization_id == admin.organization_id,
                Promoter.is_active.is_(True),
                Promoter.whatsapp_opt_in.is_(True),
            ))
            if row.whatsapp_number or row.mobile_number
        }
        # Explicit opt-out events and address-level blocking override a
        # legacy checked consent box. Shared numbers are deduplicated.
        decisions = evaluate_recipients(
            database, admin.organization_id, list(promoters.values()),
            "whatsapp", "reminder", now=now,
        )
        eligible_ids = {
            person.id for person, _, state, _ in decisions if state == "eligible"
        }
        promoters = {
            identifier: person for identifier, person in promoters.items()
            if identifier in eligible_ids
        }
        assigned = defaultdict(list)
        for link in database.scalars(select(PromoterAssignment).where(
            PromoterAssignment.organization_id == admin.organization_id,
            PromoterAssignment.ended_at.is_(None),
        )):
            if link.promoter_id in promoters and link.prospect_id in unpaid:
                assigned[link.promoter_id].append(unpaid[link.prospect_id])
        for promoter_id, group in assigned.items():
            # Every eligible assigned sponsor is collapsed into a single
            # promoter intent; never one separate message per linked sponsor.
            group = sorted(group, key=lambda person: (person.full_name, str(person.prospect_id)))
            recipients.append(ReminderRecipient(
                recipient_id=promoter_id,
                recipient_name=promoters[promoter_id].full_name,
                sponsor_count=len(group),
                outstanding_paise=sum(x.outstanding_paise for x in group),
                unpaid_sponsors=group,
            ))
    recipients.sort(key=lambda row: (row.recipient_name, str(row.recipient_id)))
    if len(recipients) > MAX_RECIPIENTS:
        raise HTTPException(
            status_code=409,
            detail="Too many eligible recipients. No reminders prepared",
        )
    return ReminderPreview(
        kind=kind, period_month=month_start(today), today_ist=today,
        scheduled_on=scheduled_on, is_due_today=today == scheduled_on,
        currency="INR", timezone="Asia/Kolkata",
        eligible_recipients=len(recipients),
        unpaid_sponsors=sum(item.sponsor_count for item in recipients),
        total_outstanding_paise=sum(item.outstanding_paise for item in recipients),
        recipients=recipients,
        notice=(
            "Eligibility preview only. No WhatsApp or Pabbly delivery is enabled. "
            "Delivery must recheck consent, paid status and assignments."
        ),
    )


def _batch_read(db: Session, row: ReminderBatch) -> BatchRead:
    """Count only dispatches confirmed by authenticated delivery callbacks."""
    delivered = db.scalar(
        select(func.count(MessageDispatch.id)).join(
            ReminderIntent,
            (ReminderIntent.organization_id == MessageDispatch.organization_id)
            & (ReminderIntent.id == MessageDispatch.reminder_intent_id),
        ).where(
            ReminderIntent.organization_id == row.organization_id,
            ReminderIntent.batch_id == row.id,
            MessageDispatch.status == "delivered",
        )
    ) or 0
    status = (
        "delivered" if row.recipient_count and delivered == row.recipient_count
        else "partially_delivered" if delivered > 0 else "prepared"
    )
    return BatchRead(
        id=row.id, kind=row.kind, period_month=row.period_month,
        scheduled_on=row.scheduled_on, recipient_count=row.recipient_count,
        status=status, delivered_count=delivered,
    )


def current_intent_eligible(
    database: Session, admin: AdminUser, intent: ReminderIntent,
    now: datetime | None = None,
) -> bool:
    """Mandatory conservative pre-dispatch gate for Phase 11.

    A new delivery worker must also compose the promoter summary from the
    refreshed list, not the frozen snapshot. A prepared batch is never
    sufficient permission to send.
    """
    now = now or utc_now()
    if intent.organization_id != admin.organization_id or intent.status != "prepared":
        return False
    if (
        intent.period_month != month_start(ist_today(now))
        or intent.scheduled_on != ist_today(now)
    ):
        # Never deliver an old prepared batch on a rescheduled or later day.
        return False
    settings = _settings(database, admin)
    preview = _build_preview(database, admin, settings, intent.kind, now)
    if not preview.is_due_today:
        return False
    for recipient in preview.recipients:
        target = intent.prospect_id if intent.kind == "sponsor" else intent.promoter_id
        if recipient.recipient_id == target:
            return True
    return False


@router.get("/preview", response_model=ReminderPreview)
def preview(
    kind: ReminderKind,
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
) -> ReminderPreview:
    settings = _settings(database, context[0])
    response.headers["Cache-Control"] = "no-store"
    return _build_preview(database, context[0], settings, kind, utc_now())


@router.post("/prepare", response_model=BatchRead, status_code=201)
def prepare(
    payload: PrepareInput, response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
) -> BatchRead:
    admin = context[0]
    settings = _settings(database, admin, lock=True)
    now = utc_now()
    today = ist_today(now)
    scheduled = _schedule(settings, payload.kind, today)
    # Existing request retries are safe across the midnight IST boundary.
    existing = database.scalars(select(ReminderBatch).where(
        ReminderBatch.organization_id == admin.organization_id,
        ReminderBatch.request_id == payload.request_id,
    )).one_or_none()
    if existing is not None:
        if existing.kind != payload.kind:
            raise HTTPException(status_code=409, detail="Request ID belongs to another batch")
        response.status_code = 200
        response.headers["Cache-Control"] = "no-store"
        return _batch_read(database, existing)
    # Only *new* batches are subject to the no-catch-up configured-day gate.
    if today != scheduled:
        raise HTTPException(
            status_code=409,
            detail="Reminder preparation is only allowed on the configured IST reminder day",
        )
    if database.scalars(select(ReminderBatch.id).where(
        ReminderBatch.organization_id == admin.organization_id,
        ReminderBatch.kind == payload.kind,
        ReminderBatch.period_month == month_start(today),
    )).first() is not None:
        raise HTTPException(status_code=409, detail="This month's batch is already prepared")
    eligible = _build_preview(database, admin, settings, payload.kind, now)
    batch = ReminderBatch(
        organization_id=admin.organization_id, kind=payload.kind,
        request_id=payload.request_id, period_month=eligible.period_month,
        scheduled_on=scheduled, recipient_count=eligible.eligible_recipients,
        created_by_admin_id=admin.id,
    )
    database.add(batch)
    database.flush()
    for recipient in eligible.recipients:
        database.add(ReminderIntent(
            organization_id=admin.organization_id, batch_id=batch.id,
            kind=payload.kind,
            prospect_id=recipient.recipient_id if payload.kind == "sponsor" else None,
            promoter_id=recipient.recipient_id if payload.kind == "promoter" else None,
            period_month=eligible.period_month, scheduled_on=scheduled,
            sponsor_count=recipient.sponsor_count,
            outstanding_paise=recipient.outstanding_paise,
            sponsor_snapshot=[
                {"prospect_id": str(p.prospect_id), "outstanding_paise": p.outstanding_paise}
                for p in recipient.unpaid_sponsors
            ],
            status="prepared",
        ))
    database.add(AuditEvent(
        organization_id=admin.organization_id, actor_admin_id=admin.id,
        action="reminder.batch_prepared", entity_type="reminder_batch",
        entity_id=str(batch.id), before_data=None,
        after_data={
            "kind": payload.kind, "period_month": str(eligible.period_month),
            "scheduled_on": str(scheduled),
            "recipient_count": eligible.eligible_recipients,
            "delivery_enabled": False,
        },
    ))
    try:
        database.commit()
    except IntegrityError as exc:
        database.rollback()
        raise HTTPException(
            status_code=409, detail="Reminder batch already exists. Refresh before retrying"
        ) from exc
    response.headers["Cache-Control"] = "no-store"
    return _batch_read(database, batch)


@router.get("/batches", response_model=BatchPage)
def list_batches(
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BatchPage:
    clauses = [ReminderBatch.organization_id == context[0].organization_id]
    total = database.scalar(
        select(func.count(ReminderBatch.id)).where(*clauses)
    ) or 0
    batches = database.scalars(
        select(ReminderBatch).where(*clauses)
        .order_by(ReminderBatch.created_at.desc(), ReminderBatch.id.desc())
        .limit(limit).offset(offset)
    ).all()
    response.headers["Cache-Control"] = "no-store"
    return BatchPage(
        items=[_batch_read(database, row) for row in batches],
        total=total, limit=limit, offset=offset,
    )
