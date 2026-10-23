"""Admin-only Promoters: manual activity, sponsor ownership and historical assignments.

No reminder messages are emitted here. The 20th-day aggregate is Phase 11.
"""
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
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
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    email: EmailStr | None = None
    occupation: str | None = Field(default=None, max_length=120)
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

    @field_validator("first_name", "last_name", "occupation")
    @classmethod
    def clean_profile(cls, value: str | None) -> str | None:
        return (_clean_text(value) or None) if value is not None else None

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
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    email: EmailStr | None = None
    occupation: str | None = Field(default=None, max_length=120)
    mobile_number: str | None = Field(default=None, min_length=9, max_length=16)
    whatsapp_number: str | None = Field(default=None, max_length=16)
    area_city: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1500)
    whatsapp_opt_in: bool | None = None
    is_active: bool | None = None
    reassign_to_promoter_id: uuid.UUID | None = None
    reassign_individually: dict[uuid.UUID, uuid.UUID | None] | None = None

    @model_validator(mode="after")
    def validate_fields(self) -> "PromoterPatch":
        if self.model_fields_set == {"version"}:
            raise ValueError("At least one change is required")
        for field in ("full_name", "mobile_number", "area_city", "whatsapp_opt_in", "is_active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError("Required fields cannot be cleared")
        for field in ("first_name", "last_name", "occupation"):
            if field in self.model_fields_set and getattr(self, field) is not None:
                setattr(self, field, _clean_text(getattr(self, field)) or None)
        for field in ("full_name", "area_city"):
            if field in self.model_fields_set:
                cleaned = _clean_text(getattr(self, field))
                if len(cleaned) < 2 and (field != "area_city" or cleaned):
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
    first_name: str | None
    last_name: str | None
    email: str | None
    occupation: str | None
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
        first_name=promoter.first_name, last_name=promoter.last_name,
        email=promoter.email, occupation=promoter.occupation,
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
            Promoter.email.ilike(term, escape="\\"),
            Promoter.occupation.ilike(term, escape="\\"),
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
    data = payload.model_dump(exclude_unset=True, exclude={"version", "reassign_to_promoter_id", "reassign_individually"})
    changed = {k: v for k, v in data.items() if getattr(promoter, k) != v}
    if not changed:
        response.headers["Cache-Control"] = "no-store"
        return _present(database, promoter)
    if (payload.reassign_to_promoter_id or payload.reassign_individually is not None) and changed.get("is_active") is not False:
        raise HTTPException(status_code=422, detail="Reassignment requires deactivation")
    if payload.reassign_to_promoter_id and payload.reassign_individually is not None:
        raise HTTPException(status_code=422, detail="Choose bulk or individual reassignment")
    transfer_count = 0
    if changed.get("is_active") is False:
        assignments = database.scalars(select(PromoterAssignment).where(
            PromoterAssignment.organization_id == admin.organization_id,
            PromoterAssignment.promoter_id == promoter.id,
            PromoterAssignment.ended_at.is_(None),
        ).order_by(PromoterAssignment.prospect_id).with_for_update()).all()
        assigned_ids = {a.prospect_id for a in assignments}
        if payload.reassign_individually is not None:
            destinations = payload.reassign_individually
            if set(destinations) != assigned_ids:
                raise HTTPException(
                    status_code=409, detail="Assignments changed; reload before deactivating"
                )
        else:
            target_id = payload.reassign_to_promoter_id
            if assignments and (target_id is None or target_id == promoter.id):
                raise HTTPException(
                    status_code=422, detail="Select another active promoter for reassignment"
                )
            destinations = {a.prospect_id: target_id for a in assignments}
        target_ids = sorted({value for value in destinations.values() if value}, key=str)
        if promoter.id in target_ids:
            raise HTTPException(status_code=422, detail="Cannot reassign to the inactive promoter")
        targets = {target_id: _load(database, admin, target_id, lock=True)
                   for target_id in target_ids}
        if any(not target.is_active for target in targets.values()):
            raise HTTPException(status_code=409, detail="Replacement promoter is inactive")
        now = utc_now()
        for assignment in assignments:
            prospect = database.scalars(select(Prospect).where(
                Prospect.organization_id == admin.organization_id,
                Prospect.id == assignment.prospect_id,
            ).with_for_update()).one()
            assignment.ended_at = now
            assignment.ended_by_admin_id = admin.id
            prospect.version += 1
            prospect.updated_at = now
        database.flush()
        for assignment in assignments:
            destination = destinations[assignment.prospect_id]
            if destination is not None:
                database.add(PromoterAssignment(
                    organization_id=admin.organization_id,
                    promoter_id=destination, prospect_id=assignment.prospect_id,
                    assigned_by_admin_id=admin.id,
                ))
                transfer_count += 1
        for target in targets.values():
            target.version += 1
            target.updated_at = now
        # The current assignments, not stale scheduled summaries, determine recipients.
        database.flush()
    previous = promoter.version
    for key, value in changed.items():
        setattr(promoter, key, value)
    promoter.version += 1
    promoter.updated_at = utc_now()
    _audit(database, admin, promoter, "promoter.updated",
           before={"version": previous},
           after={"version": promoter.version, "changed_fields": sorted(changed),
                  "reassigned_sponsor_count": transfer_count,
                  "unassigned_sponsor_count": len(assigned_ids) - transfer_count if changed.get("is_active") is False else 0,
                  "active": promoter.is_active,
                  "replacement_promoter_id": (
                      str(payload.reassign_to_promoter_id) if transfer_count else None
                  )})
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
    kind: Literal["sponsors", "prospects"] | None = None,
) -> SponsorPage:
    promoter = _load(database, context[0], promoter_id)
    filters = [
        PromoterAssignment.organization_id == promoter.organization_id,
        PromoterAssignment.promoter_id == promoter.id,
        PromoterAssignment.ended_at.is_(None),
    ]
    if kind == "prospects":
        filters.append(Prospect.lifecycle_status == "new")
    elif kind == "sponsors":
        filters.append(Prospect.lifecycle_status != "new")
    total = database.scalar(select(func.count(PromoterAssignment.id))
                            .join(Prospect, Prospect.id == PromoterAssignment.prospect_id)
                            .where(*filters)) or 0
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


@router.get("/{promoter_id}/activity", response_model=list[dict[str, str]])
def promoter_activity(
    promoter_id: uuid.UUID,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
) -> list[dict[str, str]]:
    """Authenticated factual promoter changes and assignment history."""
    admin = context[0]
    promoter = _load(database, admin, promoter_id)
    entries: list[dict[str, str]] = []

    def add(key: str, kind: str, title: str, detail: str, when: datetime) -> None:
        entries.append({
            "id": key, "kind": kind, "title": title,
            "detail": detail, "occurred_at": when.isoformat(),
        })

    add("created", "created", "Promoter created", "Registered in the CRM", promoter.created_at)
    assignments = database.scalars(select(PromoterAssignment).where(
        PromoterAssignment.organization_id == admin.organization_id,
        PromoterAssignment.promoter_id == promoter.id,
    ).order_by(PromoterAssignment.assigned_at.desc()).limit(100)).all()
    for assignment in assignments:
        prospect = database.get(Prospect, assignment.prospect_id)
        name = prospect.full_name if prospect and prospect.organization_id == admin.organization_id else "prospect"
        add(str(assignment.id) + ":assigned", "assignment", "Person assigned",
            name + " assigned to this promoter", assignment.assigned_at)
        if assignment.ended_at:
            add(str(assignment.id) + ":ended", "assignment", "Assignment ended",
                name + " moved or unassigned", assignment.ended_at)
    changes = database.scalars(select(AuditEvent).where(
        AuditEvent.organization_id == admin.organization_id,
        AuditEvent.entity_type == "promoter",
        AuditEvent.entity_id == str(promoter.id),
        AuditEvent.action == "promoter.updated",
    ).order_by(AuditEvent.occurred_at.desc()).limit(100)).all()
    for row in changes:
        changed = (row.after_data or {}).get("changed_fields", [])
        if "is_active" in changed:
            active = (row.after_data or {}).get("active")
            title = "Promoter activated" if active is True else (
                "Promoter deactivated" if active is False else "Promoter status changed"
            )
        else:
            title = "Promoter details updated"
        count = (row.after_data or {}).get("reassigned_sponsor_count", 0)
        detail = f"{count} assignments transferred" if count else "Updated by Admin"
        add(str(row.id), "updated", title, detail, row.occurred_at)
    entries.sort(key=lambda entry: entry["occurred_at"], reverse=True)
    response.headers["Cache-Control"] = "no-store"
    return entries[:100]
