"""Validated, audited, organization-scoped Admin configuration endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import db_session, get_admin, require_csrf
from app.models import AdminSession, AdminUser, AuditEvent, OrganizationSettings

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
    default_contribution_paise: int | None = Field(None, ge=1, le=1_000_000_000)
    sponsor_reminder_day: int | None = Field(None, ge=1, le=28)
    promoter_reminder_day: int | None = Field(None, ge=1, le=28)
    inactivity_months: int | None = Field(None, ge=1, le=24)

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
