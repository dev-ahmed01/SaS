"""Admin-only Prospects CRUD and privacy-conscious UPI identifiers.

Phase 04 deliberately never promotes a candidate to 'active' without a payment.
Payment lifecycle logic belongs to Phase 06 and verified reconciliation Phase 08.
"""

import hashlib
import hmac
import json
import re
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounting import effective_credits, evaluate_status, ist_today
from app.auth import db_session, get_admin, require_csrf
from app.config import get_settings
from app.models import (
    AdminSession,
    AdminUser,
    AuditEvent,
    ManualCollection,
    ManualCollectionReversal,
    OrganizationSettings,
    Promoter,
    PromoterAssignment,
    Prospect,
    ProspectArchiveInterval,
    ProspectFollowUp,
    ProspectStageDefinition,
    ProspectStageTransition,
    ProspectUpiIdentifier,
    SponsorshipRate,
)
from app.security import utc_now
from app.sponsorship_policy import SPONSORSHIP_STEP_PAISE, valid_commitment


def _ist_month() -> date:
    return utc_now().astimezone(ZoneInfo("Asia/Kolkata")).date().replace(day=1)


router = APIRouter(prefix="/v1/prospects", tags=["Admin prospects"])

E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")
VPA = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}@[a-z0-9][a-z0-9.-]{1,63}$")
MAX_AMOUNT_PAISE = 1_000_000_000


def _clean_text(value: str) -> str:
    value = " ".join(value.split())
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Control characters are not allowed")
    return value


class ProspectFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=2, max_length=160)
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    email: EmailStr | None = None
    occupation: str | None = Field(default=None, max_length=120)
    start_month: date | None = None
    mobile_number: str = Field(min_length=9, max_length=16)
    whatsapp_number: str | None = Field(default=None, max_length=16)
    area_city: str = Field(default="", max_length=120)
    monthly_contribution_paise: int | None = Field(
        default=None, ge=SPONSORSHIP_STEP_PAISE, le=MAX_AMOUNT_PAISE,
        multiple_of=SPONSORSHIP_STEP_PAISE,
    )
    next_followup_on: date | None = None
    last_contact_on: date | None = None
    notes: str | None = Field(default=None, max_length=1500)
    whatsapp_opt_in: bool = False

    @field_validator("full_name")
    @classmethod
    def normalize_labels(cls, value: str) -> str:
        result = _clean_text(value)
        if len(result) < 2:
            raise ValueError("Provide at least two characters")
        return result

    @field_validator("first_name", "last_name", "occupation")
    @classmethod
    def clean_profile(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_text(value) or None

    @field_validator("start_month")
    @classmethod
    def valid_start_month(cls, value: date | None) -> date | None:
        if value is None:
            return None
        today = _ist_month()
        delta = (value.year - today.year) * 12 + value.month - today.month
        if value.day != 1 or not 0 <= delta < 6:
            raise ValueError(
                "Tentative start must be the first of a month, within the next six months"
            )
        return value

    @field_validator("area_city")
    @classmethod
    def normalize_area(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if cleaned and len(cleaned) < 2:
            raise ValueError("Provide at least two characters when a location is supplied")
        return cleaned

    @field_validator("mobile_number", "whatsapp_number")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.replace(" ", "").replace("-", "")
        if not E164.fullmatch(normalized):
            raise ValueError("Use international format, e.g. +919876543210")
        return normalized

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ProspectCreate(ProspectFields):
    upi_ids: list[str] = Field(default_factory=list, max_length=5)
    request_id: uuid.UUID | None = None


class ProspectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    email: EmailStr | None = None
    occupation: str | None = Field(default=None, max_length=120)
    pipeline_stage_id: uuid.UUID | None = None
    mobile_number: str | None = Field(default=None, min_length=9, max_length=16)
    whatsapp_number: str | None = Field(default=None, max_length=16)
    area_city: str | None = Field(default=None, max_length=120)
    monthly_contribution_paise: int | None = Field(default=None, ge=1, le=MAX_AMOUNT_PAISE)
    next_followup_on: date | None = None
    last_contact_on: date | None = None
    notes: str | None = Field(default=None, max_length=1500)
    whatsapp_opt_in: bool | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "ProspectUpdate":
        nonnull = ("full_name", "mobile_number", "area_city", "monthly_contribution_paise",
                   "whatsapp_opt_in")
        if any(name in self.model_fields_set and getattr(self, name) is None for name in nonnull):
            raise ValueError("Required fields cannot be set to null")
        if self.model_fields_set == {"version"}:
            raise ValueError("Specify at least one field to update")
        # Normalize using the same rules as the creation request.
        for name in ("first_name", "last_name", "occupation"):
            if name in self.model_fields_set and getattr(self, name) is not None:
                setattr(self, name, _clean_text(getattr(self, name)) or None)
        for name in ("full_name", "area_city"):
            if name in self.model_fields_set:
                value = _clean_text(getattr(self, name))
                if len(value) < 2 and (name != "area_city" or value):
                    raise ValueError("Provide at least two characters")
                setattr(self, name, value)
        for name in ("mobile_number", "whatsapp_number"):
            value = getattr(self, name)
            if value is not None and name in self.model_fields_set:
                setattr(self, name, ProspectFields.validate_phone(value))
        if "notes" in self.model_fields_set and self.notes is not None:
            self.notes = self.notes.strip() or None
        return self


class StageDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    stage: Literal["active", "inactive"]
    reason: Literal["not_interested", "budget", "timing", "unreachable", "other"] | None = None
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_inactive_reason(self) -> "StageDecision":
        if self.stage == "inactive" and not self.reason:
            raise ValueError("An inactive reason is required")
        if self.stage == "active" and not self.note:
            raise ValueError("A follow-up note is required before activation")
        if self.stage == "active" and self.reason:
            raise ValueError("Use a follow-up note instead of an inactivity reason")
        if self.note is not None:
            self.note = _clean_text(self.note) or None
        return self


class StageHistoryRead(BaseModel):
    from_stage: Literal["active", "inactive"]
    to_stage: Literal["active", "inactive"]
    reason: str | None
    note: str | None
    changed_at: datetime


class UpiAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upi_id: str = Field(min_length=5, max_length=193)
    version: int = Field(ge=1)


class UpiRead(BaseModel):
    id: uuid.UUID
    masked_vpa: str
    is_verified: bool


class ProspectRead(BaseModel):
    id: uuid.UUID
    full_name: str
    first_name: str | None
    last_name: str | None
    email: str | None
    occupation: str | None
    crm_stage: Literal["active", "inactive"]
    crm_inactive_reason: str | None
    crm_inactive_note: str | None
    crm_stage_changed_at: datetime | None
    days_inactive: int | None
    assigned_promoter_id: uuid.UUID | None
    assigned_promoter_name: str | None
    pipeline_stage_id: uuid.UUID | None
    pipeline_stage_name: str | None
    pipeline_stage_color: str | None
    stage_history: list[StageHistoryRead]
    mobile_number: str
    whatsapp_number: str | None
    area_city: str
    monthly_contribution_paise: int
    next_followup_on: date | None
    last_contact_on: date | None
    notes: str | None
    whatsapp_opt_in: bool
    lifecycle_status: Literal["new", "active", "inactive"]
    last_verified_payment_at: datetime | None
    start_month: date | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    version: int
    upi_ids: list[UpiRead]


class FollowUpInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    occurred_on: date
    outcome: Literal["contacted", "no_answer", "interested", "not_interested", "callback"]
    notes: str = Field(min_length=3, max_length=500)
    next_followup_on: date | None = None

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if len(cleaned) < 3:
            raise ValueError("A meaningful follow-up note is required")
        return cleaned


class FollowUpRead(BaseModel):
    id: uuid.UUID
    occurred_on: date
    outcome: str
    notes: str
    next_followup_on: date | None
    created_at: datetime


class ProspectPage(BaseModel):
    items: list[ProspectRead]
    total: int
    limit: int
    offset: int


def _validate_pipeline(
    db: Session, admin: AdminUser, stage_id: uuid.UUID,
) -> None:
    exists = db.scalar(select(ProspectStageDefinition.id).where(
        ProspectStageDefinition.organization_id == admin.organization_id,
        ProspectStageDefinition.id == stage_id,
    ))
    if exists is None:
        raise HTTPException(status_code=422, detail="Select an existing prospect stage")


def _upi_normalized(raw: str) -> str:
    value = raw.strip().lower()
    if not VPA.fullmatch(value):
        raise HTTPException(status_code=422, detail="Invalid UPI ID format")
    return value


def _upi_digest(value: str) -> str:
    secret = get_settings().upi_match_secret
    if not secret or len(secret) < 32:
        raise HTTPException(status_code=503, detail="UPI matching is not configured")
    return hmac.new(secret.encode("utf-8"), value.encode("ascii"), hashlib.sha256).hexdigest()


def _mask_vpa(value: str) -> str:
    local, handle = value.split("@", 1)
    # A short masked identifier is sufficient to manage registrations. Keep the handle
    # but never expose or persist the full payer address.
    return local[:1] + "***" + (local[-2:] if len(local) > 3 else "") + "@" + handle


def _upi_list(prospect: Prospect) -> list[UpiRead]:
    return [
        UpiRead(id=item.id, masked_vpa=item.masked_vpa, is_verified=item.is_verified)
        for item in sorted(prospect.upi_ids, key=lambda item: item.created_at)
        if item.revoked_at is None
    ]


def _read(prospect: Prospect, status_override: str | None = None,
          *, db: Session | None = None) -> ProspectRead:
    promoter = None
    if db is not None:
        promoter = db.execute(select(PromoterAssignment.promoter_id, Promoter.full_name).join(
            Promoter, Promoter.id == PromoterAssignment.promoter_id,
        ).where(
            PromoterAssignment.organization_id == prospect.organization_id,
            PromoterAssignment.prospect_id == prospect.id,
            PromoterAssignment.ended_at.is_(None),
            Promoter.organization_id == prospect.organization_id,
        )).first()
    changed_at = prospect.crm_stage_changed_at
    if changed_at is not None and changed_at.tzinfo is None:
        changed_at = changed_at.replace(tzinfo=UTC)
    days_inactive = (max(0, (utc_now() - changed_at).days)
                     if prospect.crm_stage == "inactive" and changed_at else None)
    pipeline = (db.get(ProspectStageDefinition, prospect.pipeline_stage_id)
                if db is not None and prospect.pipeline_stage_id else None)
    return ProspectRead(
        id=prospect.id,
        full_name=prospect.full_name,
        first_name=prospect.first_name,
        last_name=prospect.last_name,
        email=prospect.email,
        occupation=prospect.occupation,
        crm_stage=prospect.crm_stage,
        crm_inactive_reason=prospect.crm_inactive_reason,
        crm_inactive_note=prospect.crm_inactive_note,
        crm_stage_changed_at=prospect.crm_stage_changed_at,
        days_inactive=days_inactive,
        assigned_promoter_id=promoter.promoter_id if promoter else None,
        assigned_promoter_name=promoter.full_name if promoter else None,
        pipeline_stage_id=prospect.pipeline_stage_id,
        pipeline_stage_name=pipeline.name if pipeline else None,
        pipeline_stage_color=pipeline.color if pipeline else None,
        stage_history=[StageHistoryRead(
            from_stage=row.from_stage, to_stage=row.to_stage,
            reason=row.reason, note=row.note, changed_at=row.changed_at,
        ) for row in prospect.stage_transitions],
        mobile_number=prospect.mobile_number,
        whatsapp_number=prospect.whatsapp_number,
        area_city=prospect.area_city,
        monthly_contribution_paise=prospect.monthly_contribution_paise,
        next_followup_on=prospect.next_followup_on,
        last_contact_on=prospect.last_contact_on,
        notes=prospect.notes,
        whatsapp_opt_in=prospect.whatsapp_opt_in,
        lifecycle_status=status_override or prospect.lifecycle_status,
        last_verified_payment_at=prospect.last_verified_payment_at,
        start_month=prospect.start_month,
        created_at=prospect.created_at,
        updated_at=prospect.updated_at,
        archived_at=prospect.archived_at,
        version=prospect.version,
        upi_ids=_upi_list(prospect),
    )


def _audit(db: Session, admin: AdminUser, prospect: Prospect, action: str,
           before: dict | None = None, after: dict | None = None) -> None:
    # Avoid replicating personally identifying strings into append-only logs.
    db.add(AuditEvent(
        organization_id=admin.organization_id,
        actor_admin_id=admin.id,
        action=action,
        entity_type="prospect",
        entity_id=str(prospect.id),
        before_data=before,
        after_data=after,
    ))


def _get(db: Session, admin: AdminUser, prospect_id: uuid.UUID,
         *, allow_archived: bool = False, lock: bool = False) -> Prospect:
    query = select(Prospect).where(
        Prospect.id == prospect_id,
        Prospect.organization_id == admin.organization_id,
    )
    if not allow_archived:
        query = query.where(Prospect.archived_at.is_(None))
    if lock:
        query = query.with_for_update()
    prospect = db.scalars(query).one_or_none()
    if prospect is None:
        raise HTTPException(status_code=404, detail="Prospect not found")
    return prospect


def _check_version(prospect: Prospect, requested: int) -> None:
    if prospect.version != requested:
        raise HTTPException(
            status_code=409,
            detail="This prospect changed in another session. Refresh and try again.",
        )


def _attach_upi(db: Session, admin: AdminUser, prospect: Prospect, raw: str) -> None:
    normalized = _upi_normalized(raw)
    digest = _upi_digest(normalized)
    for existing in prospect.upi_ids:
        if existing.digest == digest:
            if existing.revoked_at is None:
                raise HTTPException(status_code=409, detail="UPI ID is already registered")
            existing.revoked_at = None
            existing.is_verified = False
            return
    db.add(ProspectUpiIdentifier(
        organization_id=admin.organization_id,
        prospect_id=prospect.id,
        digest=digest,
        masked_vpa=_mask_vpa(normalized),
        is_verified=False,
    ))


def _project_statuses(
    db: Session, admin: AdminUser, sponsors: list[Prospect],
) -> dict[uuid.UUID, str]:
    """Read-only fresh tenant-scoped status; GET must not mutate audit/versions."""
    current = [p for p in sponsors if p.archived_at is None]
    if not current:
        return {}
    settings = db.get(OrganizationSettings, admin.organization_id)
    if settings is None:
        raise HTTPException(status_code=503, detail="Accounting settings unavailable")
    now = utc_now()
    today = ist_today(now)
    sponsor_ids = {p.id for p in current}
    rates = defaultdict(list)
    for item in db.scalars(select(SponsorshipRate).where(
        SponsorshipRate.organization_id == admin.organization_id,
        SponsorshipRate.prospect_id.in_(sponsor_ids),
    )):
        rates[item.prospect_id].append(item)
    credits = defaultdict(list)
    for item in effective_credits(db, admin.organization_id, as_of=now):
        if item.prospect_id in sponsor_ids:
            credits[item.prospect_id].append(item)
    return {
        p.id: evaluate_status(
            p, rates[p.id], credits[p.id], today, now, settings.inactivity_months,
        )
        for p in current
    }


@router.get("", response_model=ProspectPage)
def list_prospects(
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
    status: Literal["new", "active", "inactive"] | None = None,
    crm_stage: Literal["active", "inactive"] | None = None,
    q: Annotated[str, Query(max_length=100)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_archived: bool = False,
) -> ProspectPage:
    admin = context[0]
    conditions = [Prospect.organization_id == admin.organization_id]
    if not include_archived:
        conditions.append(Prospect.archived_at.is_(None))
    if crm_stage is not None:
        conditions.append(Prospect.crm_stage == crm_stage)
    if q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        term = f"%{escaped}%"
        conditions.append(or_(
            Prospect.full_name.ilike(term, escape="\\"),
            Prospect.mobile_number.ilike(term, escape="\\"),
            Prospect.area_city.ilike(term, escape="\\"),
            Prospect.email.ilike(term, escape="\\"),
            Prospect.occupation.ilike(term, escape="\\"),
        ))
    results = database.scalars(
        select(Prospect).where(*conditions)
        .order_by(Prospect.created_at.desc(), Prospect.id.desc())
    ).all()
    fresh = _project_statuses(database, admin, results)
    matching = [
        _read(p, fresh.get(p.id), db=database)
        for p in results
        if status is None or fresh.get(p.id, p.lifecycle_status) == status
    ]
    response.headers["Cache-Control"] = "no-store"
    return ProspectPage(
        items=matching[offset:offset + limit], total=len(matching),
        limit=limit, offset=offset,
    )


@router.post("", status_code=201, response_model=ProspectRead)
def create_prospect(
    payload: ProspectCreate,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
) -> ProspectRead:
    admin = context[0]
    # Optional client-supplied registration ID makes browser retries safe even when
    # a successful response is lost in transit. Never retain the original payload.
    # The fingerprint may include a sensitive VPA. Key it so a database copy
    # cannot be used as an offline dictionary oracle for those identifiers.
    # A distinct domain prevents correlation with the separately keyed VPA index.
    payload_hash = None
    if payload.request_id is not None:
        cfg = get_settings()
        # UPI requests require their dedicated key. Ordinary request IDs can
        # use the authenticated application's stable secret instead.
        fingerprint_secret = getattr(cfg, "upi_match_secret", None) or (
            getattr(cfg, "auth_secret", None) if not payload.upi_ids else None
        )
        if not fingerprint_secret or len(fingerprint_secret) < 32:
            raise HTTPException(status_code=503, detail="Registration HMAC is not configured")
        canonical = json.dumps(
            payload.model_dump(mode="json", exclude={"request_id"}),
            sort_keys=True, ensure_ascii=True,
        ).encode("utf-8")
        payload_hash = hmac.new(
            fingerprint_secret.encode("utf-8"),
            b"sas:prospect-registration:v2:" + canonical,
            hashlib.sha256,
        ).hexdigest()
    if payload.request_id is not None:
        existing = database.scalars(
            select(Prospect).where(
                Prospect.organization_id == admin.organization_id,
                Prospect.registration_request_id == payload.request_id,
            )
        ).one_or_none()
        if existing is not None:
            if existing.registration_payload_hash != payload_hash:
                raise HTTPException(status_code=409, detail="Request ID reused with different data")
            response.status_code = 200
            response.headers["Cache-Control"] = "no-store"
            return _read(existing, db=database)

    # A person is identified by their normalized mobile, never their name.
    # Archived records also reserve their number: restore instead of re-register.
    existing_mobile = database.scalar(select(Prospect.id).where(
        Prospect.organization_id == admin.organization_id,
        Prospect.mobile_number == payload.mobile_number,
    ))
    if existing_mobile is not None:
        raise HTTPException(
            status_code=409,
            detail="Mobile number already registered as a prospect",
        )
    settings = database.get(OrganizationSettings, admin.organization_id)
    if settings is None:
        raise HTTPException(status_code=503, detail="Organization settings unavailable")
    amount = payload.monthly_contribution_paise
    if amount is None:
        amount = settings.default_contribution_paise
    if not valid_commitment(amount):
        raise HTTPException(
            status_code=409,
            detail="Configured sponsor amount must be a positive multiple of ₹250",
        )
    ids = [_upi_normalized(raw) for raw in payload.upi_ids]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="Duplicate UPI identifiers supplied")
    if ids:
        for identifier in ids:
            _upi_digest(identifier)
    # Server-enforced: registration always begins at New Inquiry.
    # Admin can change it later only through the versioned details PATCH.
    inquiry = database.scalars(select(ProspectStageDefinition).where(
        ProspectStageDefinition.organization_id == admin.organization_id,
        ProspectStageDefinition.name_key == "new inquiry",
    )).one_or_none()
    if inquiry is None:
        inquiry = ProspectStageDefinition(
            organization_id=admin.organization_id,
            name="New Inquiry", name_key="new inquiry",
            description="Awaiting first documented follow-up",
            color="#64748b", sort_order=0, version=1,
        )
        database.add(inquiry)
        database.flush()
    fields = payload.model_dump(exclude={
        "upi_ids", "monthly_contribution_paise", "request_id", "start_month",
    })
    prospect = Prospect(
        organization_id=admin.organization_id,
        **fields,
        monthly_contribution_paise=amount,
        lifecycle_status="new",
        crm_stage="inactive",
        crm_stage_changed_at=utc_now(),
        pipeline_stage_id=inquiry.id,
        registration_request_id=payload.request_id,
        registration_payload_hash=payload_hash if payload.request_id else None,
        version=1,
        start_month=payload.start_month or _ist_month(),
    )
    try:
        database.add(prospect)
        database.flush()
        database.add(SponsorshipRate(
            organization_id=admin.organization_id,
            prospect_id=prospect.id,
            effective_month=prospect.start_month,
            amount_paise=amount,
        ))
        for raw in ids:
            _attach_upi(database, admin, prospect, raw)
        database.flush()
        database.refresh(prospect, attribute_names=["upi_ids"])
        _audit(database, admin, prospect, "prospect.created", after={
            "version": 1, "upi_count": len(ids), "status": "new",
        })
        database.commit()
    except IntegrityError as exc:
        database.rollback()
        if payload.request_id:
            same = database.scalars(
                select(Prospect).where(
                    Prospect.organization_id == admin.organization_id,
                    Prospect.registration_request_id == payload.request_id,
                )
            ).one_or_none()
            if same is not None and same.registration_payload_hash == payload_hash:
                response.status_code = 200
                response.headers["Cache-Control"] = "no-store"
                return _read(same, db=database)
        duplicate = database.scalar(select(Prospect.id).where(
            Prospect.organization_id == admin.organization_id,
            Prospect.mobile_number == payload.mobile_number,
        ))
        if duplicate is not None:
            raise HTTPException(
                status_code=409,
                detail="Mobile number already registered as a prospect",
            ) from exc
        raise HTTPException(status_code=409, detail="Prospect registration conflict") from exc
    response.headers["Cache-Control"] = "no-store"
    return _read(prospect, db=database)

@router.get("/{prospect_id}", response_model=ProspectRead)
def get_prospect(
    prospect_id: uuid.UUID,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
) -> ProspectRead:
    prospect = _get(database, context[0], prospect_id, allow_archived=True)
    current = _project_statuses(database, context[0], [prospect])
    response.headers["Cache-Control"] = "no-store"
    return _read(prospect, current.get(prospect.id), db=database)


@router.patch("/{prospect_id}", response_model=ProspectRead)
def update_prospect(
    prospect_id: uuid.UUID,
    payload: ProspectUpdate,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
) -> ProspectRead:
    admin = context[0]
    prospect = _get(database, admin, prospect_id, lock=True)
    _check_version(prospect, payload.version)
    updated = payload.model_dump(exclude_unset=True, exclude={"version"})
    changed = {field: value for field, value in updated.items()
               if getattr(prospect, field) != value}
    if "pipeline_stage_id" in changed and changed["pipeline_stage_id"] is not None:
        _validate_pipeline(database, admin, changed["pipeline_stage_id"])
    if "mobile_number" in changed:
        duplicate = database.scalar(select(Prospect.id).where(
            Prospect.organization_id == admin.organization_id,
            Prospect.mobile_number == changed["mobile_number"],
            Prospect.id != prospect.id,
        ))
        if duplicate is not None:
            raise HTTPException(
                status_code=409,
                detail="Mobile number already registered as a prospect",
            )
    if "mobile_number" in changed or "whatsapp_number" in changed:
        # A verified phone cannot remain trusted after its contact number changes.
        if (changed.get("mobile_number", prospect.mobile_number) != prospect.mobile_number
                or changed.get("whatsapp_number", prospect.whatsapp_number)
                != prospect.whatsapp_number):
            changed["whatsapp_verified_at"] = None
    if "monthly_contribution_paise" in changed and not valid_commitment(
        changed["monthly_contribution_paise"]
    ):
        raise HTTPException(status_code=422, detail="New commitments require ₹250 increments")
    if changed:
        previous = prospect.version
        for field, value in changed.items():
            setattr(prospect, field, value)
        if "monthly_contribution_paise" in changed:
            # Existing and current IST months retain the contracted amount.
            # A new rate becomes effective NEXT month; no historical rewrite.
            from app.accounting import shift_month

            effective = shift_month(_ist_month(), 1)
            row = database.scalars(
                select(SponsorshipRate).where(
                    SponsorshipRate.organization_id == admin.organization_id,
                    SponsorshipRate.prospect_id == prospect.id,
                    SponsorshipRate.effective_month == effective,
                )
            ).one_or_none()
            if row is None:
                database.add(SponsorshipRate(
                    organization_id=admin.organization_id,
                    prospect_id=prospect.id,
                    effective_month=effective,
                    amount_paise=changed["monthly_contribution_paise"],
                ))
            else:
                row.amount_paise = changed["monthly_contribution_paise"]
        prospect.version += 1
        prospect.updated_at = utc_now()
        _audit(database, admin, prospect, "prospect.updated",
               before={"version": previous},
               after={"version": prospect.version, "changed_fields": sorted(changed)})
        try:
            database.commit()
        except IntegrityError as exc:
            database.rollback()
            # A concurrent request may have registered the same mobile after
            # our check. The database unique index is the final authority.
            if "mobile_number" in changed:
                raise HTTPException(
                    status_code=409,
                    detail="Mobile number already registered as a prospect",
                ) from exc
            raise HTTPException(status_code=409, detail="Prospect update conflict") from exc
    response.headers["Cache-Control"] = "no-store"
    return _read(prospect, db=database)


@router.delete("/{prospect_id}", status_code=204)
def archive_prospect(
    prospect_id: uuid.UUID,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
    version: Annotated[int | None, Header(alias="If-Match")] = None,
) -> Response:
    if version is None:
        raise HTTPException(status_code=428, detail="If-Match version header required")
    admin = context[0]
    prospect = _get(database, admin, prospect_id, lock=True)
    _check_version(prospect, version)
    previous = prospect.version
    archived_at = utc_now()
    if any(interval.restored_at is None for interval in prospect.archive_intervals):
        raise HTTPException(status_code=409, detail="Archive history is inconsistent")
    database.add(ProspectArchiveInterval(
        organization_id=admin.organization_id, prospect_id=prospect.id,
        archived_at=archived_at,
    ))
    prospect.archived_at = archived_at
    prospect.version += 1
    prospect.updated_at = utc_now()
    _audit(database, admin, prospect, "prospect.archived",
           before={"version": previous}, after={"version": prospect.version})
    database.commit()
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.post("/{prospect_id}/restore", response_model=ProspectRead)
def restore_prospect(
    prospect_id: uuid.UUID,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
    version: Annotated[int | None, Header(alias="If-Match")] = None,
) -> ProspectRead:
    if version is None:
        raise HTTPException(status_code=428, detail="If-Match version header required")
    admin = context[0]
    prospect = _get(database, admin, prospect_id, lock=True, allow_archived=True)
    if prospect.archived_at is None:
        raise HTTPException(status_code=409, detail="Prospect is not archived")
    _check_version(prospect, version)
    open_intervals = [
        row for row in prospect.archive_intervals if row.restored_at is None
    ]
    if len(open_intervals) != 1:
        raise HTTPException(
            status_code=409, detail="Archive history needs operator repair"
        )
    previous = prospect.version
    open_intervals[0].restored_at = utc_now()
    prospect.archived_at = None
    prospect.version += 1
    prospect.updated_at = utc_now()
    _audit(database, admin, prospect, "prospect.restored",
           before={"version": previous}, after={"version": prospect.version})
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return _read(prospect, db=database)


@router.post("/{prospect_id}/upi-ids", status_code=201, response_model=ProspectRead)
def add_upi(
    prospect_id: uuid.UUID,
    payload: UpiAdd,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
) -> ProspectRead:
    admin = context[0]
    prospect = _get(database, admin, prospect_id, lock=True)
    _check_version(prospect, payload.version)
    if len(_upi_list(prospect)) >= 5:
        raise HTTPException(status_code=422, detail="Maximum five UPI identifiers")
    _attach_upi(database, admin, prospect, payload.upi_id)
    prospect.version += 1
    prospect.updated_at = utc_now()
    _audit(database, admin, prospect, "prospect.upi_added",
           after={"version": prospect.version})
    database.commit()
    database.refresh(prospect, attribute_names=["upi_ids"])
    response.headers["Cache-Control"] = "no-store"
    return _read(prospect, db=database)


@router.delete("/{prospect_id}/upi-ids/{upi_id}", response_model=ProspectRead)
def revoke_upi(
    prospect_id: uuid.UUID,
    upi_id: uuid.UUID,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
    version: Annotated[int | None, Header(alias="If-Match")] = None,
) -> ProspectRead:
    if version is None:
        raise HTTPException(status_code=428, detail="If-Match version header required")
    admin = context[0]
    prospect = _get(database, admin, prospect_id, lock=True)
    _check_version(prospect, version)
    identifier = next(
        (item for item in prospect.upi_ids if item.id == upi_id and item.revoked_at is None),
        None,
    )
    if identifier is None:
        raise HTTPException(status_code=404, detail="UPI identifier not found")
    identifier.revoked_at = utc_now()
    identifier.is_verified = False
    prospect.version += 1
    prospect.updated_at = utc_now()
    _audit(database, admin, prospect, "prospect.upi_revoked",
           after={"version": prospect.version})
    database.commit()
    database.refresh(prospect, attribute_names=["upi_ids"])
    response.headers["Cache-Control"] = "no-store"
    return _read(prospect, db=database)


@router.post("/{prospect_id}/stage", response_model=ProspectRead)
def change_crm_stage(
    prospect_id: uuid.UUID,
    payload: StageDecision,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
) -> ProspectRead:
    """Manually track donor outreach and attrition without rewriting payment status."""
    admin = context[0]
    prospect = _get(database, admin, prospect_id, lock=True)
    _check_version(prospect, payload.version)
    if prospect.crm_stage == payload.stage:
        raise HTTPException(status_code=409, detail="Prospect is already in that CRM stage")
    previous = prospect.crm_stage
    now = utc_now()
    database.add(ProspectStageTransition(
        organization_id=admin.organization_id,
        prospect_id=prospect.id,
        from_stage=previous, to_stage=payload.stage,
        reason=payload.reason if payload.stage == "inactive" else None,
        note=payload.note,
        changed_at=now, actor_admin_id=admin.id,
    ))
    prospect.crm_stage = payload.stage
    prospect.crm_stage_changed_at = now
    prospect.crm_inactive_reason = payload.reason if payload.stage == "inactive" else None
    prospect.crm_inactive_note = payload.note if payload.stage == "inactive" else None
    prospect.version += 1
    prospect.updated_at = now
    _audit(database, admin, prospect, "prospect.crm_stage_changed",
           before={"stage": previous, "version": payload.version},
           after={"stage": payload.stage, "reason_code": payload.reason,
                  "version": prospect.version})
    database.commit()
    database.expire(prospect, ["stage_transitions"])
    response.headers["Cache-Control"] = "no-store"
    return _read(prospect, db=database)


@router.get("/{prospect_id}/followups", response_model=list[FollowUpRead])
def list_followups(
    prospect_id: uuid.UUID,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
) -> list[FollowUpRead]:
    prospect = _get(database, context[0], prospect_id)
    rows = database.scalars(select(ProspectFollowUp).where(
        ProspectFollowUp.organization_id == context[0].organization_id,
        ProspectFollowUp.prospect_id == prospect.id,
    ).order_by(ProspectFollowUp.created_at.desc(), ProspectFollowUp.id.desc()).limit(100)).all()
    response.headers["Cache-Control"] = "no-store"
    return [FollowUpRead.model_validate({
        "id": row.id, "occurred_on": row.occurred_on, "outcome": row.outcome,
        "notes": row.notes, "next_followup_on": row.next_followup_on,
        "created_at": row.created_at,
    }) for row in rows]


@router.post("/{prospect_id}/followups", response_model=FollowUpRead, status_code=201)
def add_followup(
    prospect_id: uuid.UUID,
    payload: FollowUpInput,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
) -> FollowUpRead:
    admin = context[0]
    prospect = _get(database, admin, prospect_id, lock=True)
    _check_version(prospect, payload.version)
    today = ist_today()
    if payload.occurred_on > today:
        raise HTTPException(status_code=422, detail="Follow-up cannot be in the future")
    if payload.next_followup_on is not None and payload.next_followup_on < today:
        raise HTTPException(status_code=422, detail="Next follow-up cannot be in the past")
    event = ProspectFollowUp(
        organization_id=admin.organization_id,
        prospect_id=prospect.id, actor_admin_id=admin.id,
        occurred_on=payload.occurred_on, outcome=payload.outcome,
        notes=payload.notes, next_followup_on=payload.next_followup_on,
    )
    database.add(event)
    prospect.last_contact_on = payload.occurred_on
    prospect.next_followup_on = payload.next_followup_on
    prospect.updated_at = utc_now()
    prospect.version += 1
    database.flush()
    _audit(database, admin, prospect, "prospect.followup_logged",
           after={"outcome": payload.outcome, "followup_id": str(event.id)})
    database.commit()
    database.refresh(event)
    response.headers["Cache-Control"] = "no-store"
    return FollowUpRead(
        id=event.id, occurred_on=event.occurred_on,
        outcome=event.outcome, notes=event.notes,
        next_followup_on=event.next_followup_on, created_at=event.created_at,
    )


@router.get("/{prospect_id}/activity", response_model=list[dict[str, str]])
def prospect_activity(
    prospect_id: uuid.UUID,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
) -> list[dict[str, str]]:
    """Real CRM, contribution and assignment events; no inferred delivery/payment."""
    admin = context[0]
    prospect = _get(database, admin, prospect_id, allow_archived=True)
    entries: list[dict[str, str]] = []

    def add(key: str, kind: str, title: str, detail: str, when: datetime) -> None:
        entries.append({
            "id": key, "kind": kind, "title": title,
            "detail": detail, "occurred_at": when.isoformat(),
        })

    add("created", "created", "Prospect created", "Registered in the CRM", prospect.created_at)
    transitions = database.scalars(select(ProspectStageTransition).where(
        ProspectStageTransition.organization_id == admin.organization_id,
        ProspectStageTransition.prospect_id == prospect.id,
    ).order_by(ProspectStageTransition.changed_at.desc()).limit(100)).all()
    for row in transitions:
        label = "Marked active" if row.to_stage == "active" else "Marked inactive"
        add(str(row.id), "status", label, row.note or row.reason or "CRM status changed",
            row.changed_at)
    followups = database.scalars(select(ProspectFollowUp).where(
        ProspectFollowUp.organization_id == admin.organization_id,
        ProspectFollowUp.prospect_id == prospect.id,
    ).order_by(ProspectFollowUp.created_at.desc()).limit(100)).all()
    for row in followups:
        add(str(row.id), "followup", "Follow-up: " + row.outcome.replace("_", " "),
            row.notes, row.created_at)
    assignments = database.scalars(select(PromoterAssignment).where(
        PromoterAssignment.organization_id == admin.organization_id,
        PromoterAssignment.prospect_id == prospect.id,
    ).order_by(PromoterAssignment.assigned_at.desc()).limit(100)).all()
    for row in assignments:
        promoter = database.get(Promoter, row.promoter_id)
        name = (
            promoter.full_name
            if promoter and promoter.organization_id == admin.organization_id else "promoter"
        )
        add(str(row.id) + ":assigned", "assignment", "Promoter assigned",
            "Assigned to " + name, row.assigned_at)
        if row.ended_at:
            add(str(row.id) + ":ended", "assignment", "Promoter assignment ended",
                "Previous assignment to " + name + " ended", row.ended_at)
    collections = database.scalars(select(ManualCollection).where(
        ManualCollection.organization_id == admin.organization_id,
        ManualCollection.prospect_id == prospect.id,
    ).order_by(ManualCollection.created_at.desc()).limit(100)).all()
    for row in collections:
        amount = f"₹{row.amount_paise / 100:,.0f}"
        add(str(row.id), "payment", "Collection recorded",
            (f"{amount} received on {row.received_on.strftime('%d/%m/%y')} "
             f"for {row.period_month.strftime('%m/%Y')}"),
            row.created_at)
    collection_ids = [row.id for row in collections]
    if collection_ids:
        reversals = database.scalars(select(ManualCollectionReversal).where(
            ManualCollectionReversal.organization_id == admin.organization_id,
            ManualCollectionReversal.collection_id.in_(collection_ids),
        ).order_by(ManualCollectionReversal.created_at.desc()).limit(100)).all()
        for row in reversals:
            add(str(row.id), "payment", "Collection reversed",
                "Recorded contribution voided: " + row.reason_code.replace("_", " "),
                row.created_at)
    for row in database.scalars(select(AuditEvent).where(
        AuditEvent.organization_id == admin.organization_id,
        AuditEvent.entity_type == "prospect",
        AuditEvent.entity_id == str(prospect.id),
        AuditEvent.action.in_(("prospect.updated", "prospect.archived", "prospect.restored")),
    ).order_by(AuditEvent.occurred_at.desc()).limit(100)).all():
        changed = (row.after_data or {}).get("changed_fields", [])
        if row.action == "prospect.updated":
            title = (
                "Journey stage changed" if "pipeline_stage_id" in changed
                else "Prospect details updated"
            )
            detail = (
                "Stage updated by Admin"
                if "pipeline_stage_id" in changed else "Profile or sponsorship updated by Admin"
            )
        else:
            title = (
                "Prospect archived" if row.action == "prospect.archived" else "Prospect restored"
            )
            detail = "Admin changed archival status"
        add(str(row.id), "updated", title, detail, row.occurred_at)
    entries.sort(key=lambda entry: entry["occurred_at"], reverse=True)
    response.headers["Cache-Control"] = "no-store"
    return entries[:100]
