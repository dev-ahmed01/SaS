"""Admin-only Promoters: manual activity, sponsor ownership and historical assignments.

No reminder messages are emitted here. The 20th-day aggregate is Phase 11.
"""
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import db_session, get_admin, require_csrf
from app.models import (
    AdminSession,
    AdminUser,
    AuditEvent,
    Promoter,
    PromoterAssignment,
    Prospect,
)
from app.prospects import ProspectFields, _clean_text
from app.security import utc_now

router = APIRouter(prefix="/v1/promoters", tags=["Admin promoters"])


class PromoterCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=2, max_length=160)
    mobile_number: str = Field(min_length=9, max_length=16)
    whatsapp_number: str | None = Field(default=None, max_length=16)
    area_city: str = Field(default="", max_length=120)
    notes: str | None = Field(default=None, max_length=1500)
    whatsapp_opt_in: bool = False

    @field_validator("full_name")
    @classmethod
    def clean_label(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if len(cleaned) < 2:
            raise ValueError("At least two characters are required")
        return cleaned

    @field_validator("area_city")
    @classmethod
    def clean_area(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if cleaned and len(cleaned) < 2:
            raise ValueError("At least two characters required for a supplied location")
        return cleaned

    @field_validator("mobile_number", "whatsapp_number")
    @classmethod
    def clean_phone(cls, value: str | None) -> str | None:
        return ProspectFields.validate_phone(value)

    @field_validator("notes")
    @classmethod
    def clean_notes(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class PromoterPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    mobile_number: str | None = Field(default=None, min_length=9, max_length=16)
    whatsapp_number: str | None = Field(default=None, max_length=16)
    area_city: str | None = Field(default=None, min_length=2, max_length=120)
    notes: str | None = Field(default=None, max_length=1500)
    whatsapp_opt_in: bool | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_fields(self) -> "PromoterPatch":
        if self.model_fields_set == {"version"}:
            raise ValueError("At least one change is required")
        for field in ("full_name", "mobile_number", "area_city", "whatsapp_opt_in", "is_active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError("Required fields cannot be cleared")
        for field in ("full_name", "area_city"):
            if field in self.model_fields_set:
                cleaned = _clean_text(getattr(self, field))
                if len(cleaned) < 2:
                    raise ValueError("At least two characters are required")
                setattr(self, field, cleaned)
        for field in ("mobile_number", "whatsapp_number"):
            if field in self.model_fields_set:
                setattr(self, field, ProspectFields.validate_phone(getattr(self, field)))
        if "notes" in self.model_fields_set and self.notes is not None:
            self.notes = self.notes.strip() or None
        return self


class PromoterRead(BaseModel):
    id: uuid.UUID
    full_name: str
    mobile_number: str
    whatsapp_number: str | None
    area_city: str
    notes: str | None
    whatsapp_opt_in: bool
    is_active: bool
    sponsor_count: int
    version: int
    created_at: datetime
    updated_at: datetime


class PromoterPage(BaseModel):
    items: list[PromoterRead]
    total: int
    offset: int
    limit: int


class SponsorAssignment(BaseModel):
    assignment_id: uuid.UUID
    prospect_id: uuid.UUID
    full_name: str
    mobile_number: str
    lifecycle_status: str
    prospect_version: int


class SponsorPage(BaseModel):
    items: list[SponsorAssignment]
    total: int
    limit: int
    offset: int


def _count(db: Session, promoter: Promoter) -> int:
    return db.scalar(
        select(func.count(PromoterAssignment.id)).where(
            PromoterAssignment.organization_id == promoter.organization_id,
            PromoterAssignment.promoter_id == promoter.id,
            PromoterAssignment.ended_at.is_(None),
        )
    ) or 0


def _present(db: Session, promoter: Promoter) -> PromoterRead:
    return PromoterRead(
        id=promoter.id, full_name=promoter.full_name,
        mobile_number=promoter.mobile_number, whatsapp_number=promoter.whatsapp_number,
        area_city=promoter.area_city, notes=promoter.notes,
        whatsapp_opt_in=promoter.whatsapp_opt_in, is_active=promoter.is_active,
        sponsor_count=_count(db, promoter), version=promoter.version,
        created_at=promoter.created_at, updated_at=promoter.updated_at,
    )


def _audit(db: Session, admin: AdminUser, promoter: Promoter, action: str,
           before: dict | None = None, after: dict | None = None) -> None:
    # Names, numbers, consent details and notes are not copied to audit JSON.
    db.add(AuditEvent(
        organization_id=admin.organization_id,
        actor_admin_id=admin.id,
        action=action, entity_type="promoter", entity_id=str(promoter.id),
        before_data=before, after_data=after,
    ))


def _load(db: Session, admin: AdminUser, promoter_id: uuid.UUID,
          *, lock: bool = False) -> Promoter:
    stmt = select(Promoter).where(
        Promoter.id == promoter_id, Promoter.organization_id == admin.organization_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    value = db.scalars(stmt).one_or_none()
    if value is None:
        raise HTTPException(status_code=404, detail="Promoter not found")
    return value


def _version(record: Promoter | Prospect, expected: int) -> None:
    if record.version != expected:
        raise HTTPException(status_code=409, detail="Record has changed. Refresh and try again.")


def _version_header(value: int | None) -> int:
    if value is None:
        raise HTTPException(status_code=428, detail="If-Match version required")
    if value < 1:
        raise HTTPException(status_code=422, detail="Invalid version")
    return value


@router.get("", response_model=PromoterPage)
def list_promoters(
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
    active: bool | None = None,
    q: Annotated[str, Query(max_length=100)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PromoterPage:
    org = context[0].organization_id
    filters = [Promoter.organization_id == org]
    if active is not None:
        filters.append(Promoter.is_active == active)
    if q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        term = f"%{escaped}%"
        filters.append(or_(
            Promoter.full_name.ilike(term, escape="\\"),
            Promoter.mobile_number.ilike(term, escape="\\"),
            Promoter.area_city.ilike(term, escape="\\"),
        ))
    total = database.scalar(select(func.count(Promoter.id)).where(*filters)) or 0
    rows = database.scalars(
        select(Promoter).where(*filters)
        .order_by(Promoter.created_at.desc(), Promoter.id.desc())
        .limit(limit).offset(offset)
    ).all()
    response.headers["Cache-Control"] = "no-store"
    return PromoterPage(items=[_present(database, p) for p in rows],
                        total=total, offset=offset, limit=limit)


@router.post("", status_code=201, response_model=PromoterRead)
def create_promoter(
    payload: PromoterCreate,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
) -> PromoterRead:
    admin = context[0]
    # Prevent duplicates within one foundation while permitting other organizations.
    existing = database.scalar(
        select(Promoter.id).where(
            Promoter.organization_id == admin.organization_id,
            Promoter.mobile_number == payload.mobile_number,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Promoter phone already registered")
    promoter = Promoter(
        organization_id=admin.organization_id, **payload.model_dump(),
        is_active=True, version=1,
    )
    database.add(promoter)
    try:
        database.flush()
        _audit(database, admin, promoter, "promoter.created",
               after={"version": 1, "active": True})
        database.commit()
    except IntegrityError as exc:
        database.rollback()
        raise HTTPException(status_code=409, detail="Promoter phone already registered") from exc
    response.headers["Cache-Control"] = "no-store"
    return _present(database, promoter)


@router.get("/{promoter_id}", response_model=PromoterRead)
def get_promoter(
    promoter_id: uuid.UUID,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
) -> PromoterRead:
    promoter = _load(database, context[0], promoter_id)
    response.headers["Cache-Control"] = "no-store"
    return _present(database, promoter)


@router.patch("/{promoter_id}", response_model=PromoterRead)
def update_promoter(
    promoter_id: uuid.UUID,
    payload: PromoterPatch,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
) -> PromoterRead:
    admin = context[0]
    promoter = _load(database, admin, promoter_id, lock=True)
    _version(promoter, payload.version)
    data = payload.model_dump(exclude_unset=True, exclude={"version"})
    changed = {k: v for k, v in data.items() if getattr(promoter, k) != v}
    if not changed:
        response.headers["Cache-Control"] = "no-store"
        return _present(database, promoter)
    if changed.get("is_active") is False and _count(database, promoter):
        raise HTTPException(
            status_code=409,
            detail="Reassign or unassign the promoter's sponsors before deactivation",
        )
    previous = promoter.version
    for key, value in changed.items():
        setattr(promoter, key, value)
    promoter.version += 1
    promoter.updated_at = utc_now()
    _audit(database, admin, promoter, "promoter.updated",
           before={"version": previous},
           after={"version": promoter.version, "changed_fields": sorted(changed)})
    try:
        database.commit()
    except IntegrityError as exc:
        database.rollback()
        raise HTTPException(status_code=409, detail="Promoter phone already registered") from exc
    response.headers["Cache-Control"] = "no-store"
    return _present(database, promoter)


@router.get("/{promoter_id}/sponsors", response_model=SponsorPage)
def assigned_sponsors(
    promoter_id: uuid.UUID,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SponsorPage:
    promoter = _load(database, context[0], promoter_id)
    filters = [
        PromoterAssignment.organization_id == promoter.organization_id,
        PromoterAssignment.promoter_id == promoter.id,
        PromoterAssignment.ended_at.is_(None),
    ]
    total = database.scalar(select(func.count(PromoterAssignment.id)).where(*filters)) or 0
    assignments = database.execute(
        select(PromoterAssignment, Prospect)
        .join(Prospect, Prospect.id == PromoterAssignment.prospect_id)
        .where(*filters)
        .order_by(Prospect.full_name, Prospect.id)
        .limit(limit).offset(offset)
    ).all()
    response.headers["Cache-Control"] = "no-store"
    return SponsorPage(
        items=[SponsorAssignment(
            assignment_id=a.id, prospect_id=p.id, full_name=p.full_name,
            mobile_number=p.mobile_number, lifecycle_status=p.lifecycle_status,
            prospect_version=p.version,
        ) for a, p in assignments], total=total, limit=limit, offset=offset,
    )


def _edit_assignment(
    db: Session, admin: AdminUser, promoter: Promoter,
    prospect_id: uuid.UUID, expected_version: int, remove: bool,
) -> None:
    # For Postgres, locking the sponsor row serializes competing assignment changes.
    prospect = db.scalars(select(Prospect).where(
        Prospect.id == prospect_id,
        Prospect.organization_id == admin.organization_id,
        *([] if remove else [Prospect.archived_at.is_(None)]),
    ).with_for_update()).one_or_none()
    if prospect is None:
        raise HTTPException(status_code=404, detail="Prospect not found")
    _version(prospect, expected_version)
    current = db.scalars(select(PromoterAssignment).where(
        PromoterAssignment.organization_id == admin.organization_id,
        PromoterAssignment.prospect_id == prospect_id,
        PromoterAssignment.ended_at.is_(None),
    ).with_for_update()).one_or_none()
    if remove:
        if current is None or current.promoter_id != promoter.id:
            raise HTTPException(status_code=404, detail="Active assignment not found")
    elif not promoter.is_active:
        raise HTTPException(status_code=409, detail="Cannot assign to an inactive promoter")
    elif current is not None and current.promoter_id == promoter.id:
        return
    previous_promoter = None
    if current is not None:
        current.ended_at = utc_now()
        current.ended_by_admin_id = admin.id
        if current.promoter_id != promoter.id:
            previous_promoter = db.get(Promoter, current.promoter_id)
        # Flush the partial-unique index release before inserting a replacement.
        db.flush()
    if not remove:
        db.add(PromoterAssignment(
            organization_id=admin.organization_id,
            promoter_id=promoter.id, prospect_id=prospect.id,
            assigned_by_admin_id=admin.id,
        ))
    prospect.version += 1
    prospect.updated_at = utc_now()
    promoter.version += 1
    promoter.updated_at = utc_now()
    if previous_promoter is not None:
        previous_promoter.version += 1
        previous_promoter.updated_at = utc_now()
    _audit(db, admin, promoter,
           "promoter.sponsor_unassigned" if remove else "promoter.sponsor_assigned",
           after={"prospect_id": str(prospect.id), "prospect_version": prospect.version,
                  "previous_promoter_id": str(current.promoter_id) if current else None})


@router.put("/{promoter_id}/sponsors/{prospect_id}", response_model=PromoterRead)
def assign_sponsor(
    promoter_id: uuid.UUID, prospect_id: uuid.UUID,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
    version: Annotated[int | None, Header(alias="If-Match")] = None,
) -> PromoterRead:
    admin = context[0]
    promoter = _load(database, admin, promoter_id, lock=True)
    _edit_assignment(database, admin, promoter, prospect_id,
                     _version_header(version), remove=False)
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return _present(database, promoter)


@router.delete("/{promoter_id}/sponsors/{prospect_id}", status_code=204)
def unassign_sponsor(
    promoter_id: uuid.UUID, prospect_id: uuid.UUID,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
    version: Annotated[int | None, Header(alias="If-Match")] = None,
) -> Response:
    admin = context[0]
    promoter = _load(database, admin, promoter_id, lock=True)
    _edit_assignment(database, admin, promoter, prospect_id,
                     _version_header(version), remove=True)
    database.commit()
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
