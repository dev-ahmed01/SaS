"""Validated, audited, organization-scoped Admin configuration endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import db_session, get_admin, require_csrf
from app.config import get_settings
from app.models import AdminSession, AdminUser, AuditEvent, OrganizationSettings
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
        if not (
            cfg.app_env == "production"
            and cfg.messaging_delivery_enabled
            and cfg.messaging_sender_approved
            and cfg.messaging_enable_after is not None
            and cfg.messaging_enable_after.tzinfo is not None
        ):
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
