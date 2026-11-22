"""Validated, audited, organization-scoped Admin configuration endpoints."""

import re
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import db_session, get_admin, require_csrf
from app.config import get_settings
from app.field_options import label_key, normalize_label
from app.models import (
    AdminSession,
    AdminUser,
    AuditEvent,
    OrganizationFieldOption,
    OrganizationSettings,
)
from app.security import as_utc, utc_now
from app.sponsorship_policy import (
    INACTIVITY_COMPLETED_MONTHS,
    SPONSORSHIP_STEP_PAISE,
)

router = APIRouter(prefix="/v1/settings", tags=["Admin settings"])

# Changing the primary timezone/currency is a migration decision, not a routine setting.
# Their *values* are persisted in PostgreSQL, not hardcoded into accounting rules.
EDITABLE = (
    "default_contribution_paise",
    "sponsor_reminder_day",
    "promoter_reminder_day",
    "inactivity_months",
)


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_contribution_paise: int | None = Field(
        None, ge=SPONSORSHIP_STEP_PAISE, le=1_000_000_000,
        multiple_of=SPONSORSHIP_STEP_PAISE,
    )
    sponsor_reminder_day: int | None = Field(None, ge=1, le=28)
    promoter_reminder_day: int | None = Field(None, ge=1, le=28)
    inactivity_months: int | None = Field(
        None, ge=INACTIVITY_COMPLETED_MONTHS, le=INACTIVITY_COMPLETED_MONTHS,
    )

    @model_validator(mode="after")
    def prohibit_null_updates(self) -> "SettingsPatch":
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Settings cannot be null")
        return self


def settings_body(row: OrganizationSettings) -> dict:
    return {
        "currency_code": row.currency_code,
        "timezone": row.timezone,
        "default_contribution_paise": row.default_contribution_paise,
        "sponsor_reminder_day": row.sponsor_reminder_day,
        "promoter_reminder_day": row.promoter_reminder_day,
        "inactivity_months": row.inactivity_months,
        "automation_enabled": row.automation_enabled,
    }


@router.get("")
def read_settings(
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
) -> dict:
    admin = context[0]
    row = database.get(OrganizationSettings, admin.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Organization settings not provisioned")
    response.headers["Cache-Control"] = "no-store"
    return settings_body(row)


@router.patch("")
def update_settings(
    patch: SettingsPatch, response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
) -> dict:
    admin = context[0]
    row = database.scalars(
        select(OrganizationSettings)
        .where(OrganizationSettings.organization_id == admin.organization_id)
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Organization settings not provisioned")

    updates = patch.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="Specify at least one setting")
    # No additional business-side effects in Phase 03; future reminder plans are
    # recalculated through the tested eligibility engine in Phase 10.
    old = {field: getattr(row, field) for field in EDITABLE if field in updates}
    new = {field: value for field, value in updates.items() if old[field] != value}
    if new:
        for field, value in new.items():
            setattr(row, field, value)
        database.add(
            AuditEvent(
                organization_id=admin.organization_id,
                actor_admin_id=admin.id,
                action="settings.updated",
                entity_type="organization_settings",
                entity_id=str(admin.organization_id),
                before_data={field: old[field] for field in new},
                after_data=new,
            )
        )
        database.commit()
    response.headers["Cache-Control"] = "no-store"
    return settings_body(row)


class AutomationChange(BaseModel):
    """Separate high-impact operation; never part of general Settings PATCH."""
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    confirmation: str = Field(min_length=1, max_length=32)


@router.post("/automation")
def change_automation(
    payload: AutomationChange,
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
) -> dict:
    """Audited organization kill switch; it never directly sends a message."""
    expected = "ENABLE WHATSAPP" if payload.enabled else "DISABLE WHATSAPP"
    if payload.confirmation != expected:
        raise HTTPException(status_code=422, detail="Type the required exact confirmation")
    admin = context[0]
    row = database.scalars(
        select(OrganizationSettings)
        .where(OrganizationSettings.organization_id == admin.organization_id)
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Organization settings not found")

    if payload.enabled:
        cfg = get_settings()
        # Two independent transports share the organization automation
        # approval. Saasyto does not require (and must not enable) Pabbly.
        # Enabling this switch only authorizes future scheduled reminders;
        # the private worker and standing-reminder flags remain separate.
        legacy_ready = (
            cfg.messaging_delivery_enabled
            and cfg.messaging_sender_approved
            and cfg.messaging_enable_after is not None
            and cfg.messaging_enable_after.tzinfo is not None
        )
        saasyto_cutoff = getattr(cfg, "saasyto_enable_after", None)
        saasyto_ready = (
            getattr(cfg, "saasyto_delivery_enabled", False)
            and getattr(cfg, "saasyto_sender_approved", False)
            and getattr(cfg, "saasyto_worker_enabled", False)
            and getattr(cfg, "saasyto_auto_reminders_enabled", False)
            and not cfg.messaging_delivery_enabled
            and saasyto_cutoff is not None
            and saasyto_cutoff.tzinfo is not None
            and as_utc(saasyto_cutoff) <= utc_now()
        )
        if not (cfg.app_env == "production" and (legacy_ready or saasyto_ready)):
            raise HTTPException(
                status_code=409,
                detail="Approved production sender and activation cutoff are required",
            )

    previous = row.automation_enabled
    if previous != payload.enabled:
        row.automation_enabled = payload.enabled
        database.add(AuditEvent(
            organization_id=admin.organization_id,
            actor_admin_id=admin.id,
            action="settings.automation_changed",
            entity_type="organization_settings",
            entity_id=str(admin.organization_id),
            before_data={"automation_enabled": previous},
            after_data={"automation_enabled": payload.enabled},
        ))
        database.commit()
    response.headers["Cache-Control"] = "no-store"
    return settings_body(row)


# Field Options live inside the existing Settings module and router.
FieldKey = Literal["payout_purpose"]


class FieldOptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_key: FieldKey
    label: str = Field(min_length=2, max_length=240)
    sort_order: int | None = Field(default=None, ge=0, le=100000)

    @field_validator("label")
    @classmethod
    def clean_label(cls, value: str) -> str:
        label = normalize_label(value)
        if not 2 <= len(label) <= 240:
            raise ValueError("Use an option label of 2 to 240 characters")
        return label


class FieldOptionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    label: str | None = Field(default=None, min_length=2, max_length=240)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100000)

    @field_validator("label")
    @classmethod
    def clean_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        label = normalize_label(value)
        if len(label) < 2:
            raise ValueError("Option label is too short")
        return label

    @model_validator(mode="after")
    def require_change(self) -> "FieldOptionPatch":
        fields = self.model_fields_set
        if not fields.intersection({"label", "is_active", "sort_order"}):
            raise ValueError("Specify an option change")
        if any(getattr(self, name) is None for name in
               fields.intersection({"label", "is_active", "sort_order"})):
            raise ValueError("Option changes cannot be null")
        return self


def option_body(row: OrganizationFieldOption) -> dict:
    return {
        "id": str(row.id), "field_key": row.field_key, "code": row.code,
        "label": row.label, "is_active": row.is_active,
        "sort_order": row.sort_order, "version": row.version,
    }


@router.get("/field-options")
def read_field_options(
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
    field_key: FieldKey = "payout_purpose",
    include_inactive: bool = True,
) -> dict:
    admin = context[0]
    query = select(OrganizationFieldOption).where(
        OrganizationFieldOption.organization_id == admin.organization_id,
        OrganizationFieldOption.field_key == field_key,
    )
    if not include_inactive:
        query = query.where(OrganizationFieldOption.is_active.is_(True))
    rows = database.scalars(
        query.order_by(OrganizationFieldOption.sort_order,
                       OrganizationFieldOption.label_key)
    ).all()
    response.headers["Cache-Control"] = "no-store"
    return {"field_key": field_key, "items": [option_body(x) for x in rows]}


@router.post("/field-options", status_code=201)
def add_field_option(
    payload: FieldOptionCreate, response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
) -> dict:
    admin = context[0]
    # Lock settings to serialize option changes per organization.
    settings = database.scalars(
        select(OrganizationSettings).where(
            OrganizationSettings.organization_id == admin.organization_id
        ).with_for_update()
    ).one_or_none()
    if settings is None:
        raise HTTPException(status_code=404, detail="Settings unavailable")
    rows = database.scalars(select(OrganizationFieldOption).where(
        OrganizationFieldOption.organization_id == admin.organization_id,
        OrganizationFieldOption.field_key == payload.field_key,
    )).all()
    if len(rows) >= 100:
        raise HTTPException(status_code=409, detail="Maximum of 100 field options")
    if any(r.label_key == label_key(payload.label) for r in rows):
        raise HTTPException(status_code=409, detail="This option already exists")
    option_id = uuid.uuid4()
    slug = re.sub(r"[^a-z0-9]+", "-", payload.label.casefold()).strip("-")[:42]
    row = OrganizationFieldOption(
        id=option_id, organization_id=admin.organization_id,
        field_key=payload.field_key, label=payload.label,
        label_key=label_key(payload.label),
        code=f"{slug or 'option'}-{option_id.hex[:8]}",
        sort_order=(payload.sort_order if payload.sort_order is not None
                    else max((x.sort_order for x in rows), default=0) + 10),
        is_active=True, version=1,
    )
    database.add(row)
    database.add(AuditEvent(
        organization_id=admin.organization_id, actor_admin_id=admin.id,
        action="settings.field_option_added", entity_type="field_option",
        entity_id=str(option_id), after_data=option_body(row),
    ))
    try:
        database.commit()
    except IntegrityError as exc:
        database.rollback()
        raise HTTPException(status_code=409, detail="Duplicate field option") from exc
    response.headers["Cache-Control"] = "no-store"
    return option_body(row)


@router.patch("/field-options/{option_id}")
def edit_field_option(
    option_id: uuid.UUID, payload: FieldOptionPatch, response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
) -> dict:
    admin = context[0]
    row = database.scalars(select(OrganizationFieldOption).where(
        OrganizationFieldOption.id == option_id,
        OrganizationFieldOption.organization_id == admin.organization_id,
        OrganizationFieldOption.field_key == "payout_purpose",
    ).with_for_update()).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Option not found")
    if row.version != payload.version:
        raise HTTPException(status_code=409, detail="Option changed; refresh and retry")
    changes = payload.model_dump(exclude_unset=True, exclude={"version"})
    if "label" in changes:
        key = label_key(changes["label"])
        existing = database.scalars(select(OrganizationFieldOption).where(
            OrganizationFieldOption.organization_id == admin.organization_id,
            OrganizationFieldOption.field_key == row.field_key,
            OrganizationFieldOption.label_key == key,
            OrganizationFieldOption.id != row.id,
        )).first()
        if existing is not None:
            raise HTTPException(status_code=409, detail="This option already exists")
        changes["label_key"] = key
    if changes.get("is_active") is False and row.is_active:
        other_active = database.scalar(select(func.count()).select_from(
            OrganizationFieldOption
        ).where(
            OrganizationFieldOption.organization_id == admin.organization_id,
            OrganizationFieldOption.field_key == row.field_key,
            OrganizationFieldOption.is_active.is_(True),
            OrganizationFieldOption.id != row.id,
        )) or 0
        if other_active == 0:
            raise HTTPException(status_code=409, detail="Keep at least one active purpose")
    before = option_body(row)
    dirty = False
    for name, value in changes.items():
        if getattr(row, name) != value:
            setattr(row, name, value)
            dirty = True
    if dirty:
        row.version += 1
        database.add(AuditEvent(
            organization_id=admin.organization_id, actor_admin_id=admin.id,
            action="settings.field_option_updated",
            entity_type="field_option", entity_id=str(row.id),
            before_data=before, after_data=option_body(row),
        ))
        try:
            database.commit()
        except IntegrityError as exc:
            database.rollback()
            raise HTTPException(status_code=409, detail="Option conflict") from exc
    response.headers["Cache-Control"] = "no-store"
    return option_body(row)


class FieldOptionReorder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_key: FieldKey
    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


@router.post("/field-options/reorder")
def reorder_field_options(
    payload: FieldOptionReorder, response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
) -> dict:
    admin = context[0]
    rows = list(database.scalars(select(OrganizationFieldOption).where(
        OrganizationFieldOption.organization_id == admin.organization_id,
        OrganizationFieldOption.field_key == payload.field_key,
    ).with_for_update()).all())
    if len(rows) != len(payload.item_ids) or (
        {row.id for row in rows} != set(payload.item_ids)
    ):
        raise HTTPException(status_code=409, detail="Options changed; refresh and retry")
    if len(set(payload.item_ids)) != len(payload.item_ids):
        raise HTTPException(status_code=422, detail="Option order contains duplicates")
    by_id = {row.id: row for row in rows}
    before = [str(row.id) for row in sorted(rows, key=lambda x: x.sort_order)]
    for order, option_id in enumerate(payload.item_ids, start=1):
        row = by_id[option_id]
        new_order = order * 10
        if row.sort_order != new_order:
            row.sort_order = new_order
            row.version += 1
    database.add(AuditEvent(
        organization_id=admin.organization_id, actor_admin_id=admin.id,
        action="settings.field_options_reordered",
        entity_type="field_options", entity_id=str(admin.organization_id),
        before_data={"item_ids": before},
        after_data={"item_ids": [str(i) for i in payload.item_ids]},
    ))
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"field_key": payload.field_key,
            "items": [option_body(by_id[i]) for i in payload.item_ids]}
