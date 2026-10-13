"""Admin-managed outgoing payout schedules and manually attested disbursements.

Creating a plan does not move money. Recording a disbursement means an Admin
has independently checked that an external transfer already occurred.
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

from app.accounting import ist_today, month_start
from app.auth import db_session, get_admin, require_csrf
from app.models import (
    AdminSession,
    AdminUser,
    AuditEvent,
    OrganizationSettings,
    PayoutDisbursement,
    PayoutPlan,
)

router = APIRouter(prefix="/v1/payouts", tags=["Payouts"])
REFERENCE = re.compile(r"^[A-Z0-9][A-Z0-9._:/-]{5,99}$")


class PlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    payee_name: str = Field(min_length=2, max_length=160)
    purpose: str = Field(min_length=3, max_length=240)
    amount_paise: int = Field(ge=1, le=1_000_000_000)
    frequency: Literal["recurring", "one_time"]
    start_month: date
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("start_month")
    @classmethod
    def validate_month(cls, value: date) -> date:
        if value != month_start(value):
            raise ValueError("Start month must be the first day of a month")
        return value

    @field_validator("payee_name", "purpose")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Required text must not be blank")
        return value


class PlanOutput(BaseModel):
    id: uuid.UUID
    payee_name: str
    purpose: str
    amount_paise: int
    frequency: str
    start_month: date
    status: str
    notes: str | None
    recorded_periods: int


class PlanPage(BaseModel):
    items: list[PlanOutput]
    total: int
    limit: int
    offset: int


class StatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["active", "paused", "closed"]


class DisbursementInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    period_month: date
    paid_on: date
    amount_paise: int = Field(ge=1, le=1_000_000_000)
    payment_method: Literal["upi", "bank_transfer", "cash"]
    receipt_reference: str = Field(min_length=6, max_length=100)
    funds_sent_confirmed: Literal[True]

    @field_validator("period_month")
    @classmethod
    def validate_month(cls, value: date) -> date:
        if value != month_start(value):
            raise ValueError("Period must be the first day of a month")
        return value

    @field_validator("receipt_reference")
    @classmethod
    def normalize_reference(cls, value: str) -> str:
        value = value.strip().upper()
        if not REFERENCE.fullmatch(value):
            raise ValueError("Provide a unique payment reference (6-100 characters)")
        return value


class DisbursementOutput(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    payee_name: str
    period_month: date
    paid_on: date
    amount_paise: int
    payment_method: str
    reference_mask: str
    evidence: Literal["admin_attested"]


class DisbursementPage(BaseModel):
    items: list[DisbursementOutput]
    total: int
    limit: int
    offset: int


def _hash(payload: BaseModel) -> str:
    content = payload.model_dump(mode="json", exclude={"request_id"})
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def _settings(db: Session, admin: AdminUser) -> OrganizationSettings:
    settings = db.scalars(select(OrganizationSettings).where(
        OrganizationSettings.organization_id == admin.organization_id,
    ).with_for_update()).one_or_none()
    if settings is None or settings.currency_code != "INR" or settings.timezone != "Asia/Kolkata":
        raise HTTPException(status_code=503, detail="Accounting settings unavailable")
    return settings


def _plan(db: Session, admin: AdminUser, plan_id: uuid.UUID) -> PayoutPlan:
    row = db.scalars(select(PayoutPlan).where(
        PayoutPlan.organization_id == admin.organization_id,
        PayoutPlan.id == plan_id,
    )).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Payout plan not found")
    return row


def _plan_output(db: Session, plan: PayoutPlan) -> PlanOutput:
    count = db.scalar(select(func.count()).select_from(PayoutDisbursement).where(
        PayoutDisbursement.organization_id == plan.organization_id,
        PayoutDisbursement.plan_id == plan.id,
    )) or 0
    return PlanOutput(
        id=plan.id, payee_name=plan.payee_name, purpose=plan.purpose,
        amount_paise=plan.amount_paise, frequency=plan.frequency,
        start_month=plan.start_month, status=plan.status,
        notes=plan.notes, recorded_periods=count,
    )


@router.post("", response_model=PlanOutput, status_code=201)
def create_plan(
    payload: PlanInput, response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    db: Annotated[Session, Depends(db_session)],
) -> PlanOutput:
    admin = context[0]
    _settings(db, admin)
    digest = _hash(payload)
    existing = db.scalars(select(PayoutPlan).where(
        PayoutPlan.organization_id == admin.organization_id,
        PayoutPlan.request_id == payload.request_id,
    )).one_or_none()
    if existing is not None:
        if existing.payload_hash != digest:
            raise HTTPException(status_code=409, detail="Request ID already used")
        response.status_code = 200
        return _plan_output(db, existing)
    plan = PayoutPlan(
        organization_id=admin.organization_id, request_id=payload.request_id,
        payload_hash=digest, payee_name=payload.payee_name,
        purpose=payload.purpose, amount_paise=payload.amount_paise,
        frequency=payload.frequency, start_month=payload.start_month,
        status="active", notes=payload.notes, created_by_admin_id=admin.id,
    )
    db.add(plan)
    db.flush()
    db.add(AuditEvent(
        organization_id=admin.organization_id, actor_admin_id=admin.id,
        action="payout.plan_created", entity_type="payout_plan",
        entity_id=str(plan.id),
        after_data={"frequency":plan.frequency, "amount_paise":plan.amount_paise,
                    "start_month":plan.start_month.isoformat()},
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Duplicate payout plan request") from exc
    response.headers["Cache-Control"] = "no-store"
    return _plan_output(db, plan)


@router.get("", response_model=PlanPage)
def list_plans(
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    db: Annotated[Session, Depends(db_session)],
    active_only: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100000),
) -> PlanPage:
    admin = context[0]
    filters = [PayoutPlan.organization_id == admin.organization_id]
    if active_only:
        filters.extend([PayoutPlan.frequency == "recurring", PayoutPlan.status == "active"])
    total = db.scalar(select(func.count()).select_from(PayoutPlan).where(*filters)) or 0
    rows = db.scalars(select(PayoutPlan).where(*filters).order_by(
        PayoutPlan.created_at.desc(), PayoutPlan.id.desc()
    ).limit(limit).offset(offset)).all()
    return PlanPage(
        items=[_plan_output(db, row) for row in rows],
        total=total, limit=limit, offset=offset,
    )


@router.post("/{plan_id}/status", response_model=PlanOutput)
def change_plan_status(
    plan_id: uuid.UUID, payload: StatusInput,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    db: Annotated[Session, Depends(db_session)],
) -> PlanOutput:
    admin = context[0]
    _settings(db, admin)
    plan = db.scalars(select(PayoutPlan).where(
        PayoutPlan.organization_id == admin.organization_id,
        PayoutPlan.id == plan_id,
    ).with_for_update()).one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Payout plan not found")
    if plan.frequency != "recurring":
        raise HTTPException(status_code=409, detail="Only recurring plans can change status")
    if plan.status == "closed" and payload.status != "closed":
        raise HTTPException(status_code=409, detail="Closed plans cannot be reopened")
    if plan.status != payload.status:
        old = plan.status
        plan.status = payload.status
        db.add(AuditEvent(
            organization_id=admin.organization_id, actor_admin_id=admin.id,
            action="payout.plan_status_changed", entity_type="payout_plan",
            entity_id=str(plan.id), before_data={"status":old},
            after_data={"status":plan.status},
        ))
        db.commit()
    return _plan_output(db, plan)


def _disbursement_output(row: PayoutDisbursement, plan: PayoutPlan) -> DisbursementOutput:
    return DisbursementOutput(
        id=row.id, plan_id=row.plan_id, payee_name=plan.payee_name,
        period_month=row.period_month, paid_on=row.paid_on,
        amount_paise=row.amount_paise, payment_method=row.payment_method,
        reference_mask=row.reference_mask, evidence="admin_attested",
    )


@router.post("/{plan_id}/disbursements", response_model=DisbursementOutput, status_code=201)
def record_disbursement(
    plan_id: uuid.UUID, payload: DisbursementInput, response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    db: Annotated[Session, Depends(db_session)],
) -> DisbursementOutput:
    admin = context[0]
    _settings(db, admin)
    plan = db.scalars(select(PayoutPlan).where(
        PayoutPlan.organization_id == admin.organization_id,
        PayoutPlan.id == plan_id,
    ).with_for_update()).one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Payout plan not found")
    digest = _hash(payload)
    previous = db.scalars(select(PayoutDisbursement).where(
        PayoutDisbursement.organization_id == admin.organization_id,
        PayoutDisbursement.request_id == payload.request_id,
    )).one_or_none()
    if previous is not None:
        if previous.plan_id != plan_id or previous.payload_hash != digest:
            raise HTTPException(status_code=409, detail="Request ID already used")
        response.status_code = 200
        return _disbursement_output(previous, plan)
    today = ist_today()
    if payload.paid_on > today or payload.period_month > month_start(today):
        raise HTTPException(status_code=422, detail="Cannot attest future outgoing funds")
    if payload.period_month < plan.start_month:
        raise HTTPException(status_code=422, detail="Period predates payout plan")
    if payload.paid_on < payload.period_month:
        raise HTTPException(status_code=422, detail="Payment predates accounting period")
    if plan.status != "active":
        raise HTTPException(status_code=409, detail="Payout plan is not active")
    if plan.frequency == "one_time" and payload.period_month != plan.start_month:
        raise HTTPException(status_code=422, detail="One-time payout must use its start month")
    if payload.amount_paise != plan.amount_paise:
        raise HTTPException(status_code=422, detail="Amount must equal the agreed payout amount")
    reference_digest = hashlib.sha256(payload.receipt_reference.encode()).hexdigest()
    if db.scalars(select(PayoutDisbursement).where(
        PayoutDisbursement.organization_id == admin.organization_id,
        PayoutDisbursement.reference_digest == reference_digest,
    )).first() is not None:
        raise HTTPException(status_code=409, detail="Reference already recorded")
    if db.scalars(select(PayoutDisbursement).where(
        PayoutDisbursement.organization_id == admin.organization_id,
        PayoutDisbursement.plan_id == plan_id,
        PayoutDisbursement.period_month == payload.period_month,
    )).first() is not None:
        raise HTTPException(status_code=409, detail="Period already paid")
    row = PayoutDisbursement(
        organization_id=admin.organization_id, plan_id=plan.id,
        request_id=payload.request_id, payload_hash=digest,
        period_month=payload.period_month, paid_on=payload.paid_on,
        amount_paise=payload.amount_paise, payment_method=payload.payment_method,
        reference_digest=reference_digest,
        reference_mask="****"+payload.receipt_reference[-4:],
        recorded_by_admin_id=admin.id,
    )
    db.add(row)
    db.flush()
    db.add(AuditEvent(
        organization_id=admin.organization_id, actor_admin_id=admin.id,
        action="payout.disbursement_recorded", entity_type="payout_disbursement",
        entity_id=str(row.id),
        after_data={"plan_id":str(plan.id), "amount_paise":row.amount_paise,
                    "period_month":row.period_month.isoformat(),
                    "method":row.payment_method},
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Duplicate payout evidence") from exc
    response.headers["Cache-Control"] = "no-store"
    return _disbursement_output(row, plan)


@router.get("/disbursements", response_model=DisbursementPage)
def list_disbursements(
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    db: Annotated[Session, Depends(db_session)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100000),
) -> DisbursementPage:
    admin = context[0]
    filters = [PayoutDisbursement.organization_id == admin.organization_id]
    total = db.scalar(select(func.count()).select_from(PayoutDisbursement).where(*filters)) or 0
    rows = db.execute(select(PayoutDisbursement, PayoutPlan).join(
        PayoutPlan,
        (PayoutPlan.organization_id == PayoutDisbursement.organization_id)
        & (PayoutPlan.id == PayoutDisbursement.plan_id),
    ).where(*filters).order_by(
        PayoutDisbursement.created_at.desc(), PayoutDisbursement.id.desc()
    ).limit(limit).offset(offset)).all()
    return DisbursementPage(
        items=[_disbursement_output(row, plan) for row, plan in rows],
        total=total, limit=limit, offset=offset,
    )
