"""Audited payout planning and Admin-attested outgoing payments.

Creating a payout plan does not transfer funds. Only explicit Admin confirmation
creates a financial payment record; the app has no bank disbursement interface.
"""
import hashlib
import json
import re
import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounting import ist_today, month_start, shift_month
from app.auth import db_session, get_admin, require_csrf
from app.models import (
    AdminSession,
    AdminUser,
    AuditEvent,
    OrganizationSettings,
    PayoutPayment,
    PayoutPlan,
    PayoutPlanTerm,
)

router = APIRouter(prefix="/v1/payouts", tags=["Admin payouts"])
REFERENCE = re.compile(r"^[A-Z0-9][A-Z0-9._:/-]{5,99}$")
MAX_AMOUNT = 1_000_000_000


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    payee_name: str = Field(min_length=2, max_length=160)
    purpose: str = Field(min_length=3, max_length=240)
    notes: str | None = Field(default=None, max_length=800)
    cadence: Literal["recurring", "one_time"]
    amount_paise: int = Field(ge=1, le=MAX_AMOUNT)
    start_month: date
    scheduled_on: date | None = None

    @field_validator("payee_name", "purpose")
    @classmethod
    def trim_required(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("A meaningful non-empty value is required")
        return cleaned

    @field_validator("notes")
    @classmethod
    def trim_optional(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("start_month")
    @classmethod
    def valid_month(cls, value: date) -> date:
        if value != month_start(value):
            raise ValueError("Start month must be the first day of the month")
        return value


class PlanRead(BaseModel):
    id: uuid.UUID
    payee_name: str
    purpose: str
    notes: str | None
    cadence: Literal["recurring", "one_time"]
    amount_paise: int
    start_month: date
    scheduled_on: date | None
    status: Literal["active", "paused", "closed", "scheduled", "paid", "overdue"]
    next_status: Literal["active", "paused", "closed"] | None
    current_month_due_paise: int
    current_month_paid_paise: int
    payment_count: int
    created_at: date


class PlanPage(BaseModel):
    items: list[PlanRead]
    total: int
    limit: int
    offset: int
    period_month: date


class StatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    new_status: Literal["active", "paused", "closed"]


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    period_month: date
    paid_on: date
    payment_method: Literal["upi", "bank_transfer", "cash", "cheque"]
    payment_reference: str = Field(min_length=6, max_length=100)
    funds_disbursed: Literal[True]

    @field_validator("period_month")
    @classmethod
    def valid_month(cls, value: date) -> date:
        if value != month_start(value):
            raise ValueError("Payment month must be its first day")
        return value

    @field_validator("payment_reference")
    @classmethod
    def normalize_reference(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not REFERENCE.fullmatch(normalized):
            raise ValueError("Provide a unique bank, UPI or numbered cash receipt reference")
        return normalized


class PaymentRead(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    payee_name: str
    period_month: date
    paid_on: date
    amount_paise: int
    payment_method: str
    reference_mask: str
    evidence: Literal["admin_attested"]


class PaymentPage(BaseModel):
    items: list[PaymentRead]
    total: int
    limit: int
    offset: int


def _hash(payload: BaseModel) -> str:
    fields = payload.model_dump(mode="json", exclude={"request_id"})
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def _settings(db: Session, admin: AdminUser, lock: bool = False) -> OrganizationSettings:
    query = select(OrganizationSettings).where(
        OrganizationSettings.organization_id == admin.organization_id
    )
    if lock:
        query = query.with_for_update()
    row = db.scalars(query).one_or_none()
    if row is None or row.currency_code != "INR" or row.timezone != "Asia/Kolkata":
        raise HTTPException(status_code=503, detail="Payout locale is not configured")
    return row


def _plan(db: Session, admin: AdminUser, plan_id: uuid.UUID) -> PayoutPlan:
    row = db.scalars(select(PayoutPlan).where(
        PayoutPlan.id == plan_id,
        PayoutPlan.organization_id == admin.organization_id,
    )).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Payout plan not found")
    return row


def _terms(db: Session, plan: PayoutPlan) -> list[PayoutPlanTerm]:
    return list(db.scalars(select(PayoutPlanTerm).where(
        PayoutPlanTerm.organization_id == plan.organization_id,
        PayoutPlanTerm.plan_id == plan.id,
    ).order_by(PayoutPlanTerm.effective_month)).all())


def _term_status(terms: list[PayoutPlanTerm], month: date) -> str | None:
    active = [term for term in terms if term.effective_month <= month]
    return active[-1].status if active else None


def _payments(db: Session, plan: PayoutPlan) -> list[PayoutPayment]:
    return list(db.scalars(select(PayoutPayment).where(
        PayoutPayment.organization_id == plan.organization_id,
        PayoutPayment.plan_id == plan.id,
    )).all())


def _render_plan(
    db: Session, plan: PayoutPlan, period: date,
) -> PlanRead:
    terms = _terms(db, plan)
    payments = _payments(db, plan)
    received = sum(p.amount_paise for p in payments if p.period_month == period)
    current = month_start(ist_today())
    upcoming = shift_month(current, 1)
    if plan.cadence == "one_time":
        status = ("paid" if payments else
                  "overdue" if plan.scheduled_on < ist_today() else "scheduled")
        due = plan.amount_paise if plan.start_month == period else 0
        next_status = None
    else:
        status = _term_status(terms, current) or "scheduled"
        effective = _term_status(terms, period)
        due = (
            plan.amount_paise
            if period >= plan.start_month and effective == "active" else 0
        )
        future = _term_status(terms, upcoming)
        next_status = future if future != status else None
    return PlanRead(
        id=plan.id, payee_name=plan.payee_name, purpose=plan.purpose,
        notes=plan.notes, cadence=plan.cadence, amount_paise=plan.amount_paise,
        start_month=plan.start_month, scheduled_on=plan.scheduled_on,
        status=status, next_status=next_status,
        current_month_due_paise=due,
        current_month_paid_paise=received, payment_count=len(payments),
        created_at=plan.created_at.date() if plan.created_at else ist_today(),
    )


def _render_payment(db: Session, entry: PayoutPayment) -> PaymentRead:
    plan = db.get(PayoutPlan, entry.plan_id)
    return PaymentRead(
        id=entry.id, plan_id=entry.plan_id, payee_name=plan.payee_name,
        period_month=entry.period_month, paid_on=entry.paid_on,
        amount_paise=entry.amount_paise, payment_method=entry.payment_method,
        reference_mask=entry.reference_mask, evidence="admin_attested",
    )


@router.post("/plans", response_model=PlanRead, status_code=201)
def create_plan(
    payload: PlanCreate, response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    db: Annotated[Session, Depends(db_session)],
) -> PlanRead:
    admin = context[0]
    _settings(db, admin, lock=True)
    sig = _hash(payload)
    existing = db.scalars(select(PayoutPlan).where(
        PayoutPlan.organization_id == admin.organization_id,
        PayoutPlan.create_request_id == payload.request_id,
    )).one_or_none()
    if existing:
        if existing.create_hash != sig:
            raise HTTPException(status_code=409, detail="Request ID already used")
        response.status_code = 200
        response.headers["Cache-Control"] = "no-store"
        return _render_plan(db, existing, month_start(ist_today()))
    today = ist_today()
    if payload.start_month > shift_month(month_start(today), 12):
        raise HTTPException(status_code=422, detail="Start cannot exceed twelve future months")
    if payload.start_month < shift_month(month_start(today), -35):
        raise HTTPException(status_code=422, detail="Start is outside the 36-month window")
    if payload.cadence == "recurring" and payload.scheduled_on is not None:
        raise HTTPException(status_code=422, detail="Recurring payouts use the start month")
    if payload.cadence == "one_time":
        if payload.scheduled_on is None or month_start(payload.scheduled_on) != payload.start_month:
            raise HTTPException(status_code=422, detail="One-time date must be in its start month")
    plan = PayoutPlan(
        organization_id=admin.organization_id,
        create_request_id=payload.request_id, create_hash=sig,
        payee_name=payload.payee_name, purpose=payload.purpose,
        notes=payload.notes, cadence=payload.cadence,
        start_month=payload.start_month, scheduled_on=payload.scheduled_on,
        amount_paise=payload.amount_paise, created_by_admin_id=admin.id,
    )
    db.add(plan)
    db.flush()
    db.add(PayoutPlanTerm(
        organization_id=admin.organization_id, plan_id=plan.id,
        effective_month=payload.start_month, status="active",
        recorded_by_admin_id=admin.id,
    ))
    db.add(AuditEvent(
        organization_id=admin.organization_id, actor_admin_id=admin.id,
        action="payout.plan_created", entity_type="payout_plan",
        entity_id=str(plan.id), before_data=None,
        after_data={
            "cadence":payload.cadence, "amount_paise":payload.amount_paise,
            "start_month":str(payload.start_month), "purpose":payload.purpose,
        },
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Payout already exists; refresh") from exc
    response.headers["Cache-Control"] = "no-store"
    return _render_plan(db, plan, month_start(today))


@router.get("/plans", response_model=PlanPage)
def list_plans(
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    db: Annotated[Session, Depends(db_session)],
    view: Literal["active", "all"] = "all",
    month: str | None = Query(default=None, max_length=7),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PlanPage:
    admin = context[0]
    _settings(db, admin)
    today = month_start(ist_today())
    if month:
        try:
            if len(month) != 7 or month[4] != "-":
                raise ValueError("invalid")
            period = date.fromisoformat(month + "-01")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Use YYYY-MM") from exc
    else:
        period = today
    if period < shift_month(today, -35) or period > shift_month(today, 12):
        raise HTTPException(status_code=422, detail="Selected month is out of range")
    clauses = [PayoutPlan.organization_id == admin.organization_id]
    if view == "active":
        # Match _render_plan's *current* status, independent of selected month.
        latest_state = (
            select(PayoutPlanTerm.status).where(
                PayoutPlanTerm.organization_id == admin.organization_id,
                PayoutPlanTerm.plan_id == PayoutPlan.id,
                PayoutPlanTerm.effective_month <= today,
            )
            .order_by(PayoutPlanTerm.effective_month.desc())
            .limit(1)
            .correlate(PayoutPlan)
            .scalar_subquery()
        )
        clauses.extend((PayoutPlan.cadence == "recurring", latest_state == "active"))
    total = db.scalar(select(func.count(PayoutPlan.id)).where(*clauses)) or 0
    plans = db.scalars(
        select(PayoutPlan).where(*clauses)
        .order_by(PayoutPlan.created_at.desc(), PayoutPlan.id.desc())
        .limit(limit).offset(offset)
    ).all()
    rows = [_render_plan(db, plan, period) for plan in plans]
    response.headers["Cache-Control"] = "no-store"
    return PlanPage(
        items=rows, total=total, limit=limit, offset=offset, period_month=period,
    )


@router.post("/plans/{plan_id}/status", response_model=PlanRead, status_code=201)
def change_plan_status(
    plan_id: uuid.UUID, payload: StatusChange, response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    db: Annotated[Session, Depends(db_session)],
) -> PlanRead:
    admin = context[0]
    _settings(db, admin, lock=True)
    plan = _plan(db, admin, plan_id)
    if plan.cadence != "recurring":
        raise HTTPException(status_code=409, detail="One-time payouts have no recurring status")
    existing = db.scalars(select(PayoutPlanTerm).where(
        PayoutPlanTerm.organization_id == admin.organization_id,
        PayoutPlanTerm.request_id == payload.request_id,
    )).one_or_none()
    current = month_start(ist_today())
    if existing:
        if existing.plan_id != plan_id or existing.status != payload.new_status:
            raise HTTPException(status_code=409, detail="Request ID already used")
        response.status_code = 200
        response.headers["Cache-Control"] = "no-store"
        return _render_plan(db, plan, current)
    future = shift_month(current, 1)
    terms = _terms(db, plan)
    status = _term_status(terms, current) or "active"
    if status == "closed":
        raise HTTPException(status_code=409, detail="Closed payout plan cannot resume")
    if payload.new_status == status:
        raise HTTPException(status_code=409, detail="Plan is already in this state")
    if any(term.effective_month == future for term in terms):
        raise HTTPException(
            status_code=409, detail="A next-month status change is already scheduled"
        )
    db.add(PayoutPlanTerm(
        organization_id=admin.organization_id, plan_id=plan.id,
        effective_month=future, request_id=payload.request_id,
        status=payload.new_status, recorded_by_admin_id=admin.id,
    ))
    db.add(AuditEvent(
        organization_id=admin.organization_id, actor_admin_id=admin.id,
        action="payout.status_scheduled", entity_type="payout_plan",
        entity_id=str(plan.id), before_data={"status":status},
        after_data={
            "status":payload.new_status,
            "effective_month":str(future),
        },
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflicting scheduled change") from exc
    response.headers["Cache-Control"] = "no-store"
    return _render_plan(db, plan, current)


@router.post("/plans/{plan_id}/payments", response_model=PaymentRead, status_code=201)
def record_disbursement(
    plan_id: uuid.UUID, payload: PaymentCreate, response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    db: Annotated[Session, Depends(db_session)],
) -> PaymentRead:
    admin = context[0]
    _settings(db, admin, lock=True)
    plan = _plan(db, admin, plan_id)
    sig = _hash(payload)
    prior = db.scalars(select(PayoutPayment).where(
        PayoutPayment.organization_id == admin.organization_id,
        PayoutPayment.request_id == payload.request_id,
    )).one_or_none()
    if prior:
        if prior.plan_id != plan_id or prior.request_payload_hash != sig:
            raise HTTPException(status_code=409, detail="Request ID used for different payment")
        response.status_code = 200
        response.headers["Cache-Control"] = "no-store"
        return _render_payment(db, prior)
    today = ist_today()
    if payload.paid_on > today or payload.period_month > month_start(today):
        raise HTTPException(status_code=422, detail="Cannot attest a future payment")
    if payload.period_month < plan.start_month or payload.paid_on < payload.period_month:
        raise HTTPException(status_code=422, detail="Payment predates the obligation")
    if plan.cadence == "one_time":
        if payload.period_month != plan.start_month:
            raise HTTPException(status_code=422, detail="Wrong month for a one-time payout")
        # Advance disbursement is explicitly outside the approved payout policy.
        if plan.scheduled_on is None or payload.paid_on < plan.scheduled_on:
            raise HTTPException(status_code=422, detail="Payment predates the scheduled payout")
    elif _term_status(_terms(db, plan), payload.period_month) != "active":
        raise HTTPException(status_code=409, detail="No active payout obligation for this month")
    normalized = payload.payment_reference
    digest = hashlib.sha256(normalized.encode()).hexdigest()
    if db.scalars(select(PayoutPayment.id).where(
        PayoutPayment.organization_id == admin.organization_id,
        PayoutPayment.reference_digest == digest,
    )).first() is not None:
        raise HTTPException(status_code=409, detail="Payment reference already recorded")
    entry = PayoutPayment(
        organization_id=admin.organization_id, plan_id=plan.id,
        request_id=payload.request_id, request_payload_hash=sig,
        period_month=payload.period_month, paid_on=payload.paid_on,
        amount_paise=plan.amount_paise, payment_method=payload.payment_method,
        reference_digest=digest, reference_mask="****"+normalized[-4:],
        recorded_by_admin_id=admin.id,
    )
    db.add(entry)
    db.flush()
    db.add(AuditEvent(
        organization_id=admin.organization_id, actor_admin_id=admin.id,
        action="payout.disbursement_attested", entity_type="payout_payment",
        entity_id=str(entry.id), before_data=None,
        after_data={
            "plan_id":str(plan.id), "amount_paise":plan.amount_paise,
            "period_month":str(payload.period_month),
            "payment_method":payload.payment_method,
            "proof_type":"admin_attested",
        },
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Duplicate payment or reference; refresh"
        ) from exc
    response.headers["Cache-Control"] = "no-store"
    return _render_payment(db, entry)


@router.get("/payments", response_model=PaymentPage)
def list_disbursements(
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    db: Annotated[Session, Depends(db_session)],
    plan_id: uuid.UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PaymentPage:
    admin = context[0]
    _settings(db, admin)
    criteria = [PayoutPayment.organization_id == admin.organization_id]
    if plan_id:
        criteria.append(PayoutPayment.plan_id == plan_id)
    count = db.scalar(select(func.count(PayoutPayment.id)).where(*criteria)) or 0
    entries = db.scalars(select(PayoutPayment).where(*criteria)
        .order_by(PayoutPayment.created_at.desc(), PayoutPayment.id.desc())
        .limit(limit).offset(offset)).all()
    response.headers["Cache-Control"] = "no-store"
    return PaymentPage(
        items=[_render_payment(db, payment) for payment in entries],
        total=count, offset=offset, limit=limit,
    )
