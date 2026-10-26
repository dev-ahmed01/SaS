"""Admin-managed, tenant-scoped pipeline stages for Prospects only.

Pipeline stages are independent from financial lifecycle and CRM Active/Inactive.
No labels, orders, or stage definitions are preseeded or hard-coded.
"""
import re
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import db_session, get_admin, require_csrf
from app.models import (
    AdminSession,
    AdminUser,
    AuditEvent,
    Prospect,
    ProspectStageDefinition,
)
from app.prospect_defaults import REGISTRATION_STAGE_KEY
from app.security import utc_now

router = APIRouter(prefix="/v1/prospect-stages", tags=["Admin prospect pipeline stages"])
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class StageFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    color: str = "#64748b"
    sort_order: int = Field(default=0, ge=0, le=9999)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Stage name is required")
        return cleaned

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return " ".join(value.split()) or None if value is not None else None

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str) -> str:
        if not COLOR.fullmatch(value):
            raise ValueError("Color must be a six-digit hex value")
        return value.lower()


class StageCreate(StageFields):
    pass


class StagePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    color: str | None = None
    sort_order: int | None = Field(default=None, ge=0, le=9999)

    @model_validator(mode="after")
    def validate_changes(self) -> "StagePatch":
        data = self.model_dump(exclude_unset=True, exclude={"version"})
        if not data:
            raise ValueError("At least one change is required")
        if "name" in data:
            if self.name is None or not " ".join(self.name.split()):
                raise ValueError("Stage name cannot be empty")
            self.name = " ".join(self.name.split())
        if "description" in data and self.description is not None:
            self.description = " ".join(self.description.split()) or None
        if "color" in data:
            if self.color is None or not COLOR.fullmatch(self.color):
                raise ValueError("Invalid stage color")
            self.color = self.color.lower()
        if "sort_order" in data and self.sort_order is None:
            raise ValueError("Order cannot be cleared")
        return self


class StageRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    color: str
    sort_order: int
    version: int
    prospect_count: int
    is_registration_default: bool
    created_at: datetime


def _fetch(db: Session, admin: AdminUser, stage_id: uuid.UUID, *, lock=False):
    query = select(ProspectStageDefinition).where(
        ProspectStageDefinition.id == stage_id,
        ProspectStageDefinition.organization_id == admin.organization_id,
    )
    if lock:
        query = query.with_for_update()
    stage = db.scalars(query).one_or_none()
    if stage is None:
        raise HTTPException(status_code=404, detail="Stage not found")
    return stage


def _present(db: Session, stage: ProspectStageDefinition) -> StageRead:
    count = db.scalar(select(func.count(Prospect.id)).where(
        Prospect.organization_id == stage.organization_id,
        Prospect.pipeline_stage_id == stage.id,
        Prospect.archived_at.is_(None),
    )) or 0
    return StageRead(
        id=stage.id, name=stage.name, description=stage.description,
        color=stage.color, sort_order=stage.sort_order, version=stage.version,
        prospect_count=count, is_registration_default=(stage.system_key == REGISTRATION_STAGE_KEY),
        created_at=stage.created_at,
    )


def _audit(db: Session, admin: AdminUser, stage: ProspectStageDefinition,
           action: str, *, fields: list[str] | None = None) -> None:
    db.add(AuditEvent(
        organization_id=admin.organization_id, actor_admin_id=admin.id,
        action=action, entity_type="prospect_stage", entity_id=str(stage.id),
        before_data=None, after_data={"fields": fields or []},
    ))


@router.get("", response_model=list[StageRead])
def list_stages(
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
) -> list[StageRead]:
    rows = database.scalars(select(ProspectStageDefinition).where(
        ProspectStageDefinition.organization_id == context[0].organization_id,
    ).order_by(
        ProspectStageDefinition.sort_order,
        ProspectStageDefinition.name_key,
        ProspectStageDefinition.id,
    )).all()
    response.headers["Cache-Control"] = "no-store"
    return [_present(database, stage) for stage in rows]


@router.post("", response_model=StageRead, status_code=201)
def create_stage(
    payload: StageCreate,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
) -> StageRead:
    admin = context[0]
    stage = ProspectStageDefinition(
        organization_id=admin.organization_id,
        name=payload.name, name_key=payload.name.casefold(),
        description=payload.description, color=payload.color,
        sort_order=payload.sort_order, version=1,
    )
    database.add(stage)
    try:
        database.flush()
        _audit(database, admin, stage, "prospect_stage.created")
        database.commit()
    except IntegrityError as exc:
        database.rollback()
        raise HTTPException(status_code=409, detail="Stage name already exists") from exc
    response.headers["Cache-Control"] = "no-store"
    return _present(database, stage)


@router.patch("/{stage_id}", response_model=StageRead)
def update_stage(
    stage_id: uuid.UUID,
    payload: StagePatch,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
    response: Response,
) -> StageRead:
    admin = context[0]
    stage = _fetch(database, admin, stage_id, lock=True)
    if stage.version != payload.version:
        raise HTTPException(status_code=409, detail="Stage changed; reload and retry")
    changes = payload.model_dump(exclude_unset=True, exclude={"version"})
    changed_fields = []
    for key, value in changes.items():
        if getattr(stage, key) != value:
            setattr(stage, key, value)
            changed_fields.append(key)
    if "name" in changed_fields:
        stage.name_key = stage.name.casefold()
    if changed_fields:
        stage.version += 1
        stage.updated_at = utc_now()
        _audit(database, admin, stage, "prospect_stage.updated", fields=changed_fields)
        try:
            database.commit()
        except IntegrityError as exc:
            database.rollback()
            raise HTTPException(status_code=409, detail="Stage name already exists") from exc
    response.headers["Cache-Control"] = "no-store"
    return _present(database, stage)


@router.delete("/{stage_id}", status_code=204)
def delete_stage(
    stage_id: uuid.UUID,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
    version: Annotated[int | None, Header(alias="If-Match")] = None,
) -> Response:
    admin = context[0]
    stage = _fetch(database, admin, stage_id, lock=True)
    if version is None:
        raise HTTPException(status_code=428, detail="Stage version required")
    if version != stage.version:
        raise HTTPException(status_code=409, detail="Stage changed; reload and retry")
    if stage.system_key == REGISTRATION_STAGE_KEY:
        raise HTTPException(status_code=409, detail="Registration default cannot be deleted")
    assigned = database.scalar(select(func.count(Prospect.id)).where(
        Prospect.organization_id == admin.organization_id,
        Prospect.pipeline_stage_id == stage.id,
    )) or 0
    if assigned:
        raise HTTPException(
            status_code=409,
            detail="Reassign all prospects, including archived ones, before deleting this stage",
        )
    _audit(database, admin, stage, "prospect_stage.deleted")
    try:
        database.delete(stage)
        database.commit()
    except IntegrityError as exc:
        database.rollback()
        raise HTTPException(status_code=409, detail="Stage is still assigned") from exc
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
