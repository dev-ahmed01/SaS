"""Admin-only Prospects CRUD and privacy-conscious UPI identifiers.

Phase 04 deliberately never promotes a candidate to 'active' without a payment.
Payment lifecycle logic belongs to Phase 06 and verified reconciliation Phase 08.
"""

import hashlib
import hmac
import re
import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import db_session, get_admin, require_csrf
from app.config import get_settings
from app.models import (
    AdminSession,
    AdminUser,
    AuditEvent,
    OrganizationSettings,
    Prospect,
    ProspectUpiIdentifier,
)
from app.security import utc_now

router = APIRouter(prefix="/v1/prospects", tags=["Admin prospects"])

E164 = re.compile(r"^\+[1-9]\d{7,14}$")
VPA = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}@[a-z0-9][a-z0-9.-]{1,63}$")
MAX_AMOUNT_PAISE = 100_000_000


def _clean_text(value: str) -> str:
    value = " ".join(value.split())
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Control characters are not allowed")
    return value


class ProspectFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=2, max_length=160)
    mobile_number: str = Field(min_length=9, max_length=16)
    whatsapp_number: str | None = Field(default=None, max_length=16)
    area_city: str = Field(min_length=2, max_length=120)
    monthly_contribution_paise: int | None = Field(default=None, ge=1, le=MAX_AMOUNT_PAISE)
    next_followup_on: date | None = None
    last_contact_on: date | None = None
    notes: str | None = Field(default=None, max_length=1500)
    whatsapp_opt_in: bool = False

    @field_validator("full_name", "area_city")
    @classmethod
    def normalize_labels(cls, value: str) -> str:
        result = _clean_text(value)
        if len(result) < 2:
            raise ValueError("Provide at least two characters")
        return result

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


class ProspectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    mobile_number: str | None = Field(default=None, min_length=9, max_length=16)
    whatsapp_number: str | None = Field(default=None, max_length=16)
    area_city: str | None = Field(default=None, min_length=2, max_length=120)
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
        for name in ("full_name", "area_city"):
            if name in self.model_fields_set:
                value = _clean_text(getattr(self, name))
                if len(value) < 2:
                    raise ValueError("Provide at least two characters")
                setattr(self, name, value)
        for name in ("mobile_number", "whatsapp_number"):
            value = getattr(self, name)
            if value is not None and name in self.model_fields_set:
                setattr(self, name, ProspectFields.validate_phone(value))
        if "notes" in self.model_fields_set and self.notes is not None:
            self.notes = self.notes.strip() or None
        return self


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
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    version: int
    upi_ids: list[UpiRead]


class ProspectPage(BaseModel):
    items: list[ProspectRead]
    total: int
    limit: int
    offset: int


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


def _read(prospect: Prospect) -> ProspectRead:
    return ProspectRead(
        id=prospect.id,
        full_name=prospect.full_name,
        mobile_number=prospect.mobile_number,
        whatsapp_number=prospect.whatsapp_number,
        area_city=prospect.area_city,
        monthly_contribution_paise=prospect.monthly_contribution_paise,
        next_followup_on=prospect.next_followup_on,
        last_contact_on=prospect.last_contact_on,
        notes=prospect.notes,
        whatsapp_opt_in=prospect.whatsapp_opt_in,
        lifecycle_status=prospect.lifecycle_status,
        last_verified_payment_at=prospect.last_verified_payment_at,
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


@router.get("", response_model=ProspectPage)
def list_prospects(
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
    status: Literal["new", "active", "inactive"] | None = None,
    q: Annotated[str, Query(max_length=100)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_archived: bool = False,
) -> ProspectPage:
    admin = context[0]
    conditions = [Prospect.organization_id == admin.organization_id]
    if not include_archived:
        conditions.append(Prospect.archived_at.is_(None))
    if status:
        conditions.append(Prospect.lifecycle_status == status)
    if q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        term = f"%{escaped}%"
        conditions.append(or_(
            Prospect.full_name.ilike(term, escape="\\"),
            Prospect.mobile_number.ilike(term, escape="\\"),
            Prospect.area_city.ilike(term, escape="\\"),
        ))
    total = database.scalar(select(func.count(Prospect.id)).where(*conditions)) or 0
    results = database.scalars(
        select(Prospect).where(*conditions)
        .order_by(Prospect.created_at.desc(), Prospect.id.desc())
        .limit(limit).offset(offset)
    ).all()
    response.headers["Cache-Control"] = "no-store"
    return ProspectPage(items=[_read(p) for p in results], total=total,
                        limit=limit, offset=offset)


@router.post("", status_code=201, response_model=ProspectRead)
def create_prospect(
    payload: ProspectCreate,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
) -> ProspectRead:
    admin = context[0]
    settings = database.get(OrganizationSettings, admin.organization_id)
    if settings is None:
        raise HTTPException(status_code=503, detail="Organization settings unavailable")
    amount = payload.monthly_contribution_paise
    if amount is None:
        amount = settings.default_contribution_paise
    if amount > MAX_AMOUNT_PAISE:
        raise HTTPException(status_code=422, detail="Amount exceeds the maximum")
    ids = [_upi_normalized(raw) for raw in payload.upi_ids]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="Duplicate UPI identifiers supplied")
    # Resolve the hashing secret before making any mutations.
    if ids:
        for identifier in ids:
            _upi_digest(identifier)
    fields = payload.model_dump(exclude={"upi_ids", "monthly_contribution_paise"})
    prospect = Prospect(
        organization_id=admin.organization_id,
        **fields,
        monthly_contribution_paise=amount,
        lifecycle_status="new",
        version=1,
    )
    database.add(prospect)
    database.flush()
    for raw in ids:
        _attach_upi(database, admin, prospect, raw)
    database.flush()
    # Relationship is selectin-loaded automatically on read.
    database.refresh(prospect, attribute_names=["upi_ids"])
    _audit(database, admin, prospect, "prospect.created", after={
        "version": 1, "upi_count": len(ids), "status": "new",
    })
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return _read(prospect)


@router.get("/{prospect_id}", response_model=ProspectRead)
def get_prospect(
    prospect_id: uuid.UUID,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
) -> ProspectRead:
    prospect = _get(database, context[0], prospect_id, allow_archived=True)
    response.headers["Cache-Control"] = "no-store"
    return _read(prospect)


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
    if ("monthly_contribution_paise" in updated
            and prospect.last_verified_payment_at is not None):
        raise HTTPException(
            status_code=409, detail="Change active sponsorship amounts through agreement history"
        )
    changed = {field: value for field, value in updated.items()
               if getattr(prospect, field) != value}
    if changed:
        previous = prospect.version
        for field, value in changed.items():
            setattr(prospect, field, value)
        prospect.version += 1
        prospect.updated_at = utc_now()
        _audit(database, admin, prospect, "prospect.updated",
               before={"version": previous},
               after={"version": prospect.version, "changed_fields": sorted(changed)})
        database.commit()
    response.headers["Cache-Control"] = "no-store"
    return _read(prospect)


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
    prospect.archived_at = utc_now()
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
    previous = prospect.version
    prospect.archived_at = None
    prospect.version += 1
    prospect.updated_at = utc_now()
    _audit(database, admin, prospect, "prospect.restored",
           before={"version": previous}, after={"version": prospect.version})
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return _read(prospect)


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
    return _read(prospect)


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
    return _read(prospect)
