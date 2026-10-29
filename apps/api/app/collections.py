"""Admin attestation of received funds, not automated bank verification."""
import hashlib
import hmac
import json
import re
import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import auth as auth_module
from app.accounting import effective_credits, evaluate_status, ist_today, month_start, shift_month
from app.auth import db_session, get_admin, require_csrf
from app.communication_consent import address_opted_out, evaluate_recipients
from app.config import get_settings
from app.models import (
    AdminSession,
    AdminUser,
    AuditEvent,
    ManualCollection,
    ManualCollectionReversal,
    MessageDispatch,
    MessageOutbox,
    OrganizationSettings,
    Prospect,
    SponsorshipRate,
    VerifiedCredit,
)
from app.security import as_utc, utc_now
from app.sponsorship_policy import valid_contribution

router = APIRouter(prefix="/v1/collections", tags=["Manual collections"])
REFERENCE = re.compile(r"^[A-Z0-9][A-Z0-9._:/-]{5,99}$")


class CollectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    prospect_id: uuid.UUID
    period_month: date
    received_on: date
    amount_paise: int = Field(ge=1, le=1_000_000_000)
    payment_method: Literal["upi", "bank_transfer", "cash"]
    receipt_reference: str | None = Field(default=None, min_length=6, max_length=100)
    funds_confirmed: Literal[True]

    @field_validator("receipt_reference")
    @classmethod
    def normalize_reference(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        ref = value.strip().upper()
        if not REFERENCE.fullmatch(ref):
            raise ValueError("Use a unique transaction or receipt reference (6-100 characters)")
        return ref

    @field_validator("period_month")
    @classmethod
    def month_only(cls, value: date) -> date:
        if value != month_start(value):
            raise ValueError("Month must be its first day")
        return value


class CollectionOutput(BaseModel):
    id: uuid.UUID
    prospect_id: uuid.UUID
    sponsor_name: str
    sponsor_mobile: str
    amount_paise: int
    period_month: date
    received_on: date
    recorded_at: datetime
    payment_method: str
    reference_mask: str
    evidence: Literal["admin_attested"]
    message_status: Literal[
        "awaiting_integration", "suppressed", "claimed", "accepted",
        "unknown", "failed", "cancelled", "sent", "delivered",
    ]
    sponsor_status: str
    reversed: bool
    reversal_reason: str | None


class CollectionPage(BaseModel):
    items: list[CollectionOutput]
    total: int
    limit: int
    offset: int


def _fingerprint(domain: bytes, raw: bytes) -> str:
    """Domain-separated secret-keyed receipt fingerprints."""
    secret = auth_module.get_settings().auth_secret
    if not secret or len(secret) < 32:
        raise HTTPException(status_code=503, detail="Receipt fingerprint key unavailable")
    return hmac.new(secret.encode("utf-8"), domain + raw, hashlib.sha256).hexdigest()


def _payload_bytes(payload: CollectionInput) -> bytes:
    body = payload.model_dump(mode="json", exclude={"request_id"})
    return json.dumps(body, sort_keys=True).encode("utf-8")


def _payload_hash(payload: CollectionInput) -> str:
    return _fingerprint(b"sas:manual-receipt-request:v2:", _payload_bytes(payload))


def _legacy_payload_hash(payload: CollectionInput) -> str:
    # Only compare against older immutable entries. Never write this new.
    return hashlib.sha256(_payload_bytes(payload)).hexdigest()


def _reference_hash(ref: str) -> str:
    return _fingerprint(b"sas:manual-receipt-ref:v2:", ref.encode("utf-8"))


def _legacy_reference_hash(ref: str) -> str:
    return hashlib.sha256(ref.encode("utf-8")).hexdigest()


def _receipt_notice(
    db: Session, organization_id: uuid.UUID, collection_id: uuid.UUID,
) -> MessageOutbox:
    """Prefer an explicit resend to the original even on same-second timestamps.

    SQLite and some imported ledgers have coarse created_at timestamps; sorting
    by a random UUID makes the visible status nondeterministic.
    """
    notices = db.scalars(select(MessageOutbox).where(
        MessageOutbox.organization_id == organization_id,
        MessageOutbox.collection_id == collection_id,
    )).all()
    resend = next(
        (event for event in notices
         if event.event_type == "collection_confirmation_resend"), None,
    )
    original = next(
        (event for event in notices if event.event_type == "collection_recorded"), None,
    )
    event = resend or original
    if event is None:
        raise HTTPException(status_code=409, detail="Collection confirmation record missing")
    return event


def _view(db: Session, row: ManualCollection) -> CollectionOutput:
    sponsor = db.get(Prospect, row.prospect_id)
    event = _receipt_notice(db, row.organization_id, row.id)
    reversed_entry = db.scalars(select(ManualCollectionReversal).where(
        ManualCollectionReversal.organization_id == row.organization_id,
        ManualCollectionReversal.collection_id == row.id,
    )).one_or_none()
    dispatch=db.scalars(select(MessageDispatch).where(
        MessageDispatch.organization_id == row.organization_id,
        MessageDispatch.outbox_id == event.id,
    )).one_or_none()
    return CollectionOutput(
        id=row.id, prospect_id=row.prospect_id, sponsor_name=sponsor.full_name,
        sponsor_mobile=sponsor.mobile_number,
        amount_paise=row.amount_paise, period_month=row.period_month,
        received_on=row.received_on, recorded_at=row.created_at,
        payment_method=row.payment_method,
        reference_mask=row.reference_mask, evidence="admin_attested",
        message_status=dispatch.status if dispatch else event.status,
        sponsor_status=sponsor.lifecycle_status,
        reversed=reversed_entry is not None,
        reversal_reason=reversed_entry.reason_code if reversed_entry else None,
    )


@router.post("", response_model=CollectionOutput, status_code=201)
def add_collection(
    payload: CollectionInput,
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    db: Annotated[Session, Depends(db_session)],
) -> CollectionOutput:
    admin = context[0]
    settings = db.scalars(select(OrganizationSettings).where(
        OrganizationSettings.organization_id == admin.organization_id
    ).with_for_update()).one_or_none()
    if settings is None or settings.timezone != "Asia/Kolkata" or settings.currency_code != "INR":
        raise HTTPException(status_code=503, detail="Accounting settings unavailable")

    payload_hash = _payload_hash(payload)
    old = db.scalars(select(ManualCollection).where(
        ManualCollection.organization_id == admin.organization_id,
        ManualCollection.request_id == payload.request_id,
    )).one_or_none()
    if old is not None:
        if old.request_payload_hash not in (payload_hash, _legacy_payload_hash(payload)):
            raise HTTPException(status_code=409, detail="Request ID used for different payment")
        response.status_code = 200
        response.headers["Cache-Control"] = "no-store"
        return _view(db, old)

    # Exact replays of historical off-tier receipts are read-only.
    if not valid_contribution(payload.amount_paise):
        raise HTTPException(
            status_code=422,
            detail="New contributions must be ₹250 or an exact multiple of ₹250",
        )
    today = ist_today()
    if payload.received_on > today or payload.period_month > month_start(today):
        raise HTTPException(status_code=422, detail="Cannot record a future payment")
    if payload.received_on < payload.period_month:
        raise HTTPException(status_code=422, detail="Received date predates billing month")
    sponsor = db.scalars(select(Prospect).where(
        Prospect.organization_id == admin.organization_id,
        Prospect.id == payload.prospect_id,
        Prospect.archived_at.is_(None),
    ).with_for_update()).one_or_none()
    if sponsor is None:
        raise HTTPException(status_code=404, detail="Sponsor not found or archived")
    if sponsor.crm_stage != "active":
        raise HTTPException(
            status_code=422, detail="Only active CRM sponsors can receive collections"
        )
    if sponsor.start_month is None or payload.period_month < sponsor.start_month:
        raise HTTPException(status_code=422, detail="Billing month predates registration")
    if payload.received_on < sponsor.start_month:
        raise HTTPException(status_code=422, detail="Receipt predates sponsor registration")
    rates = db.scalars(select(SponsorshipRate).where(
        SponsorshipRate.organization_id == admin.organization_id,
        SponsorshipRate.prospect_id == sponsor.id,
    )).all()
    if not any(rate.effective_month <= payload.period_month for rate in rates):
        raise HTTPException(status_code=409, detail="Contribution agreement missing")
    # No external transaction ID? Allocate a stable, clearly internal ledger key.
    # This keeps request idempotency and unique-reference constraints without
    # fabricating bank or payment-provider proof.
    reference = payload.receipt_reference or ("INTERNAL-" + payload.request_id.hex.upper())
    digest = _reference_hash(reference)
    if payload.receipt_reference and db.scalars(select(ManualCollection.id).where(
        ManualCollection.organization_id == admin.organization_id,
        ManualCollection.reference_digest.in_(
            (digest, _legacy_reference_hash(reference))
        ),
    )).first() is not None:
        raise HTTPException(status_code=409, detail="Receipt or transaction already recorded")
    now = utc_now()
    credit = VerifiedCredit(
        organization_id=admin.organization_id, prospect_id=sponsor.id,
        period_month=payload.period_month, amount_paise=payload.amount_paise,
        source_type="manual_attested", source_key="manual:"+digest, verified_at=now,
    )
    db.add(credit)
    try:
        db.flush()
    except IntegrityError as exc:
        # Flush happens before commit so the ordinary commit exception guard
        # cannot catch a concurrent duplicate evidence/source key.
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Duplicate request or transaction. Refresh before retrying"
        ) from exc
    row = ManualCollection(
        organization_id=admin.organization_id, prospect_id=sponsor.id,
        verified_credit_id=credit.id, request_id=payload.request_id,
        request_payload_hash=payload_hash, reference_digest=digest,
        reference_mask=("****"+reference[-4:] if payload.receipt_reference
                        else "Not provided"),
        received_on=payload.received_on, period_month=payload.period_month,
        payment_method=payload.payment_method, amount_paise=payload.amount_paise,
        recorded_by_admin_id=admin.id,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Duplicate request or transaction. Refresh before retrying"
        ) from exc
    can_message = sponsor.whatsapp_opt_in and bool(
        sponsor.whatsapp_number or sponsor.mobile_number
    )
    db.add(MessageOutbox(
        organization_id=admin.organization_id,
        prospect_id=sponsor.id, collection_id=row.id,
        event_type="collection_recorded",
        status="awaiting_integration" if can_message else "suppressed",
        suppress_reason=None if can_message else
        ("consent_missing" if not sponsor.whatsapp_opt_in else "recipient_missing"),
    ))
    before = sponsor.lifecycle_status
    credits = effective_credits(
        db, admin.organization_id, sponsor_id=sponsor.id, as_of=now,
    )
    after = evaluate_status(
        sponsor, rates, credits, today, now, settings.inactivity_months,
    )
    latest = max((as_utc(row.verified_at) for row in credits), default=None)
    changed_receipt = (
        (as_utc(sponsor.last_verified_payment_at)
         if sponsor.last_verified_payment_at else None) != latest
    )
    if changed_receipt:
        sponsor.last_verified_payment_at = latest
    if before != after or changed_receipt:
        sponsor.lifecycle_status = after
        if before != after:
            sponsor.status_updated_at = now
        sponsor.updated_at = now
        sponsor.version += 1
    db.add(AuditEvent(
        organization_id=admin.organization_id, actor_admin_id=admin.id,
        action="collection.manual_recorded", entity_type="manual_collection",
        entity_id=str(row.id), before_data=None,
        after_data={
            "prospect_id": str(sponsor.id), "amount_paise": payload.amount_paise,
            "period_month": str(payload.period_month), "method": payload.payment_method,
            "source": "admin_attested", "previous_status": before, "new_status": after,
        },
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Duplicate request or transaction. Refresh before retrying"
        ) from exc
    response.headers["Cache-Control"] = "no-store"
    return _view(db, row)


@router.get("", response_model=CollectionPage)
def list_collections(
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    db: Annotated[Session, Depends(db_session)],
    period_month: date | None = None,
    received_month: date | None = None,
    active_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CollectionPage:
    conditions = [ManualCollection.organization_id == context[0].organization_id]
    if period_month is not None:
        if period_month != month_start(period_month):
            raise HTTPException(status_code=422, detail="Invalid billing month")
        conditions.append(ManualCollection.period_month == period_month)
    if received_month is not None:
        if received_month != month_start(received_month):
            raise HTTPException(status_code=422, detail="Invalid received month")
        conditions.extend([
            ManualCollection.received_on >= received_month,
            ManualCollection.received_on < shift_month(received_month, 1),
        ])
    if active_only:
        reversed_record = select(ManualCollectionReversal.id).where(
            ManualCollectionReversal.organization_id == ManualCollection.organization_id,
            ManualCollectionReversal.collection_id == ManualCollection.id,
        ).exists()
        conditions.append(~reversed_record)
    total = db.scalar(select(func.count(ManualCollection.id)).where(*conditions)) or 0
    rows = db.scalars(select(ManualCollection).where(*conditions)
        .order_by(ManualCollection.created_at.desc(), ManualCollection.id.desc())
        .limit(limit).offset(offset)).all()
    response.headers["Cache-Control"] = "no-store"
    return CollectionPage(
        items=[_view(db, row) for row in rows], total=total,
        limit=limit, offset=offset,
    )


class ReversalInput(BaseModel):
    """Voids a mistaken ledger attestation; it does NOT initiate a refund."""

    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    reason_code: Literal[
        "duplicate_entry", "wrong_sponsor", "wrong_amount", "funds_not_received", "other"
    ]
    confirmation: Literal["REVERSE"]


class ReversalOutput(BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    prospect_id: uuid.UUID
    amount_paise: int
    reason_code: str
    reversed: Literal[True]
    message_status: Literal[
        "awaiting_integration", "suppressed", "claimed", "accepted",
        "unknown", "failed", "cancelled", "sent", "delivered",
    ]
    sponsor_status: str


def _reversal_view(
    database: Session, reversal: ManualCollectionReversal, receipt: ManualCollection,
) -> ReversalOutput:
    sponsor = database.get(Prospect, receipt.prospect_id)
    outbox = _receipt_notice(database, receipt.organization_id, receipt.id)
    dispatch=database.scalars(select(MessageDispatch).where(
        MessageDispatch.organization_id==receipt.organization_id,
        MessageDispatch.outbox_id==outbox.id,
    )).one_or_none()
    return ReversalOutput(
        id=reversal.id, collection_id=receipt.id, prospect_id=receipt.prospect_id,
        amount_paise=receipt.amount_paise, reason_code=reversal.reason_code,
        reversed=True, message_status=dispatch.status if dispatch else outbox.status,
        sponsor_status=sponsor.lifecycle_status,
    )


@router.post("/{collection_id}/reverse", response_model=ReversalOutput, status_code=201)
def reverse_collection(
    collection_id: uuid.UUID,
    payload: ReversalInput,
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    db: Annotated[Session, Depends(db_session)],
) -> ReversalOutput:
    """Atomically remove an incorrect payment from net totals, preserving evidence."""
    admin = context[0]
    settings = db.scalars(select(OrganizationSettings).where(
        OrganizationSettings.organization_id == admin.organization_id,
    ).with_for_update()).one_or_none()
    if settings is None or settings.currency_code != "INR" or settings.timezone != "Asia/Kolkata":
        raise HTTPException(status_code=503, detail="Accounting settings unavailable")

    previously = db.scalars(select(ManualCollectionReversal).where(
        ManualCollectionReversal.organization_id == admin.organization_id,
        ManualCollectionReversal.request_id == payload.request_id,
    )).one_or_none()
    receipt = db.scalars(select(ManualCollection).where(
        ManualCollection.organization_id == admin.organization_id,
        ManualCollection.id == collection_id,
    )).one_or_none()
    if receipt is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    if previously is not None:
        if (previously.collection_id != collection_id or
                previously.reason_code != payload.reason_code):
            raise HTTPException(
                status_code=409, detail="Request ID already used for a different reversal"
            )
        response.status_code = 200
        response.headers["Cache-Control"] = "no-store"
        return _reversal_view(db, previously, receipt)
    already = db.scalars(select(ManualCollectionReversal).where(
        ManualCollectionReversal.organization_id == admin.organization_id,
        ManualCollectionReversal.collection_id == collection_id,
    )).one_or_none()
    if already is not None:
        raise HTTPException(status_code=409, detail="This collection is already reversed")

    sponsor = db.scalars(select(Prospect).where(
        Prospect.organization_id == admin.organization_id,
        Prospect.id == receipt.prospect_id,
    ).with_for_update()).one()
    outboxes = db.scalars(select(MessageOutbox).where(
        MessageOutbox.organization_id == admin.organization_id,
        MessageOutbox.collection_id == collection_id,
    ).with_for_update()).all()
    # Reversal suppresses every as-yet-unclaimed confirmation, including
    # an explicitly requeued copy, without altering the historical attempts.
    before_message = (
        next(
            (event.status for event in outboxes
             if event.event_type == "collection_confirmation_resend"),
            outboxes[0].status if outboxes else "suppressed",
        )
    )
    for outbox in outboxes:
        if outbox.status == "awaiting_integration":
            outbox.status = "suppressed"
            outbox.suppress_reason = "collection_reversed"

    reversal = ManualCollectionReversal(
        organization_id=admin.organization_id, collection_id=collection_id,
        request_id=payload.request_id, reason_code=payload.reason_code,
        actor_admin_id=admin.id,
    )
    db.add(reversal)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Collection was reversed by another request. Refresh and retry"
        ) from exc
    rates = list(db.scalars(select(SponsorshipRate).where(
        SponsorshipRate.organization_id == admin.organization_id,
        SponsorshipRate.prospect_id == receipt.prospect_id,
    )).all())
    now = utc_now()
    credits = effective_credits(
        db, admin.organization_id, sponsor_id=receipt.prospect_id, as_of=now,
    )
    before_status = sponsor.lifecycle_status
    latest = max((as_utc(row.verified_at) for row in credits), default=None)
    changed_receipt = (
        (as_utc(sponsor.last_verified_payment_at)
         if sponsor.last_verified_payment_at else None) != latest
    )
    if changed_receipt:
        sponsor.last_verified_payment_at = latest
    if sponsor.archived_at is None:
        new_status = evaluate_status(
            sponsor, rates, credits, ist_today(now), now, settings.inactivity_months
        )
        changed_status = new_status != before_status
        if changed_status:
            sponsor.lifecycle_status = new_status
            sponsor.status_updated_at = now
        if changed_status or changed_receipt:
            sponsor.updated_at = now
            sponsor.version += 1
    elif changed_receipt:
        sponsor.updated_at = now
        sponsor.version += 1
    db.add(AuditEvent(
        organization_id=admin.organization_id, actor_admin_id=admin.id,
        action="collection.manual_reversed", entity_type="manual_collection",
        entity_id=str(collection_id),
        before_data={
            "amount_paise": receipt.amount_paise,
            "status": before_status, "message_status": before_message,
        },
        after_data={
            "reversal_id": str(reversal.id), "reason_code": payload.reason_code,
            "status": sponsor.lifecycle_status,
            "message_status": before_message,
            "net_receipt_removed_paise": receipt.amount_paise,
        },
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Collection was reversed by another request. Refresh and retry"
        ) from exc
    response.headers["Cache-Control"] = "no-store"
    return _reversal_view(db, reversal, receipt)


class CollectionResendInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    confirmation: Literal["RESEND"]


class CollectionResendOutput(BaseModel):
    status: Literal["queued", "already_queued"]
    notice: str


@router.post("/{collection_id}/resend-confirmation", response_model=CollectionResendOutput)
def resend_collection_confirmation(
    collection_id: uuid.UUID,
    payload: CollectionResendInput,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    db: Annotated[Session, Depends(db_session)],
    response: Response,
) -> CollectionResendOutput:
    """Fail closed until a separately approved Saasyto receipt workflow exists.

    Legacy accepted/unknown attempts may have reached the recipient; a newly
    queued repeat could duplicate a real receipt. No Pabbly sender remains.
    """
    raise HTTPException(
        status_code=503,
        detail="Saasyto collection receipt resends are not yet enabled",
    )
