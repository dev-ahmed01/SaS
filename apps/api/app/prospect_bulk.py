"""Preview-first, all-or-nothing tenant-scoped prospect batch registration.

No payment, CRM activation, WhatsApp dispatch or consent attestation occurs.
"""
import hashlib
import hmac
import json
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import auth as auth_module
from app.auth import db_session, require_csrf
from app.models import (
    AdminSession, AdminUser, AuditEvent, OrganizationSettings, Prospect,
    ProspectStageDefinition, SponsorshipRate,
)
from app.prospects import ProspectFields, _ist_month
from app.security import utc_now
from app.sponsorship_policy import SPONSORSHIP_STEP_PAISE, valid_commitment

router = APIRouter(prefix="/v1/prospects/bulk", tags=["Admin prospects"])


class BulkPerson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=2, max_length=160)
    mobile_number: str = Field(min_length=9, max_length=16)
    area_city: str = Field(default="", max_length=120)
    email: EmailStr | None = None
    monthly_contribution_paise: int | None = Field(
        default=None, ge=SPONSORSHIP_STEP_PAISE, le=1_000_000_000,
        multiple_of=SPONSORSHIP_STEP_PAISE,
    )
    start_month: date | None = None

    @field_validator("full_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return ProspectFields.normalize_labels(value)

    @field_validator("area_city")
    @classmethod
    def normalize_city(cls, value: str) -> str:
        return ProspectFields.normalize_area(value)

    @field_validator("mobile_number")
    @classmethod
    def normalize_mobile(cls, value: str) -> str:
        return ProspectFields.validate_phone(value)

    @field_validator("start_month")
    @classmethod
    def normalize_month(cls, value: date | None) -> date | None:
        return ProspectFields.valid_start_month(value)


class BulkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: uuid.UUID
    commit: bool = False
    rows: list[BulkPerson] = Field(min_length=1, max_length=100)
    expected_month: date | None = None
    expected_default_amount_paise: int | None = None


class BulkRowResult(BaseModel):
    row: int
    full_name: str
    mobile_number: str
    status: str
    detail: str | None = None
    prospect_id: uuid.UUID | None = None


class BulkResponse(BaseModel):
    preview_only: bool
    total: int
    ready: int
    already_imported: int
    added: int
    blocked: int
    default_amount_paise: int
    default_start_month: date
    rows: list[BulkRowResult]


def _row_hash(row: BulkPerson) -> str:
    secret = auth_module.get_settings().auth_secret
    if not secret or len(secret) < 32:
        raise HTTPException(status_code=503, detail="Import fingerprint unavailable")
    canonical = json.dumps(
        row.model_dump(mode="json"), sort_keys=True, ensure_ascii=True
    ).encode("utf-8")
    return hmac.new(
        secret.encode("utf-8"), b"sas:bulk-prospect:v1:" + canonical, hashlib.sha256,
    ).hexdigest()


@router.post("", response_model=BulkResponse)
def import_prospects(
    payload: BulkRequest,
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    db: Annotated[Session, Depends(db_session)],
) -> BulkResponse:
    admin = context[0]
    settings = db.get(OrganizationSettings, admin.organization_id)
    if settings is None or not valid_commitment(settings.default_contribution_paise):
        raise HTTPException(status_code=503, detail="Sponsorship settings unavailable")
    month = _ist_month()
    default_amount = settings.default_contribution_paise
    if payload.commit and (
        payload.expected_month != month
        or payload.expected_default_amount_paise != default_amount
    ):
        raise HTTPException(
            status_code=409,
            detail="Sponsorship settings or current month changed. Preview again.",
        )

    ids = [uuid.uuid5(payload.batch_id, str(index)) for index in range(len(payload.rows))]
    phones = [item.mobile_number for item in payload.rows]
    duplicates = {
        row.mobile_number: row for row in db.scalars(select(Prospect).where(
            Prospect.organization_id == admin.organization_id,
            Prospect.mobile_number.in_(phones),
        )).all()
    }
    previous = {
        row.registration_request_id: row for row in db.scalars(select(Prospect).where(
            Prospect.organization_id == admin.organization_id,
            Prospect.registration_request_id.in_(ids),
        )).all()
    }

    seen: set[str] = set()
    results: list[BulkRowResult] = []
    for index, row in enumerate(payload.rows):
        status, detail = "ready", None
        original = previous.get(ids[index])
        if row.mobile_number in seen:
            status, detail = "blocked", "Repeated mobile number in this CSV"
        elif original is not None:
            if (original.registration_payload_hash == _row_hash(row)
                    and original.mobile_number == row.mobile_number):
                status, detail = "already_imported", "Already imported in this batch"
            else:
                status, detail = "blocked", "Batch ID was already used for different data"
        elif row.mobile_number in duplicates:
            status, detail = "blocked", "Mobile already registered (including archived)"
        amount = row.monthly_contribution_paise or default_amount
        if not valid_commitment(amount):
            status, detail = "blocked", "Invalid ₹250 sponsorship increment"
        results.append(BulkRowResult(
            row=index + 1, full_name=row.full_name, mobile_number=row.mobile_number,
            status=status, detail=detail,
            prospect_id=original.id if status == "already_imported" else None,
        ))
        seen.add(row.mobile_number)

    blocked = sum(item.status == "blocked" for item in results)
    ready = sum(item.status == "ready" for item in results)
    replayed = sum(item.status == "already_imported" for item in results)
    if payload.commit and blocked:
        raise HTTPException(
            status_code=409,
            detail={"message": "Correct all blocked rows before saving; nothing was added.",
                    "rows": [item.model_dump(mode="json") for item in results]},
        )

    added = 0
    try:
        if payload.commit and ready:
            inquiry = db.scalars(select(ProspectStageDefinition).where(
                ProspectStageDefinition.organization_id == admin.organization_id,
                ProspectStageDefinition.name_key == "new inquiry",
            )).one_or_none()
            if inquiry is None:
                inquiry = ProspectStageDefinition(
                    organization_id=admin.organization_id, name="New Inquiry",
                    name_key="new inquiry", color="#64748b", sort_order=0, version=1,
                    description="Awaiting first documented follow-up",
                )
                db.add(inquiry)
                db.flush()
            now = utc_now()
            for index, row in enumerate(payload.rows):
                if results[index].status != "ready":
                    continue
                amount = row.monthly_contribution_paise or default_amount
                beginning = row.start_month or month
                person = Prospect(
                    organization_id=admin.organization_id,
                    full_name=row.full_name, mobile_number=row.mobile_number,
                    whatsapp_number=row.mobile_number, area_city=row.area_city,
                    email=str(row.email) if row.email else None,
                    monthly_contribution_paise=amount, start_month=beginning,
                    lifecycle_status="new", crm_stage="inactive",
                    crm_stage_changed_at=now, pipeline_stage_id=inquiry.id,
                    whatsapp_opt_in=False, version=1, registration_request_id=ids[index],
                    registration_payload_hash=_row_hash(row),
                )
                db.add(person)
                db.flush()
                db.add(SponsorshipRate(
                    organization_id=admin.organization_id, prospect_id=person.id,
                    effective_month=beginning, amount_paise=amount,
                ))
                db.add(AuditEvent(
                    organization_id=admin.organization_id, actor_admin_id=admin.id,
                    action="prospect.bulk_created", entity_type="prospect",
                    entity_id=str(person.id), before_data=None,
                    after_data={"batch_id": str(payload.batch_id), "row": index + 1,
                                "status": "new", "version": 1},
                ))
                results[index].status = "added"
                results[index].prospect_id = person.id
                added += 1
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Another registration changed during import. Preview again.",
        ) from exc

    response.headers["Cache-Control"] = "no-store"
    return BulkResponse(
        preview_only=not payload.commit, total=len(results),
        ready=ready if not payload.commit else 0,
        already_imported=replayed, added=added, blocked=blocked,
        default_amount_paise=default_amount, default_start_month=month, rows=results,
    )
