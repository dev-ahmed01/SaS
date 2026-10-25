"""Admin-reviewed bulk confirmation of genuinely existing WhatsApp permissions.

Never infer opt-in from Active status, override STOP, or invoke a sender.
One evidence source/reference is required for the selected Active prospect set.
"""
import hashlib
import hmac
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import db_session, get_admin, require_csrf
from app.communication_consent import (
    _latest_events,
    _revoked_addresses,
    contact_address,
)
from app.models import (
    AdminSession,
    AdminUser,
    AuditEvent,
    CommunicationConsentEvent,
    Prospect,
)
from app.security import utc_now

router = APIRouter(prefix="/v1/communication", tags=["WhatsApp consent review"])
MAX_BULK_CONSENTS = 500


class ConsentPreview(BaseModel):
    active: int
    already_documented: int
    needs_confirmation: int
    opted_out: int
    no_number: int
    review_fingerprint: str


class ConsentConfirmInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: Literal["I_HAVE_VERIFIED_EXISTING_CONSENT"]
    expected_needs_confirmation: int = Field(ge=1, le=MAX_BULK_CONSENTS)
    expected_review_fingerprint: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$",
    )
    source: str = Field(min_length=3, max_length=80)
    evidence_reference: str = Field(min_length=3, max_length=160)

    @model_validator(mode="after")
    def clean_fields(self):
        self.source = " ".join(self.source.split())
        self.evidence_reference = self.evidence_reference.strip()
        if len(self.source) < 3 or len(self.evidence_reference) < 3:
            raise ValueError("Describe the existing permission register and its reference")
        return self


def _selection(db: Session, org, *, lock=False):
    query = select(Prospect).where(
        Prospect.organization_id == org,
        Prospect.crm_stage == "active",
        Prospect.archived_at.is_(None),
    ).order_by(Prospect.id).limit(MAX_BULK_CONSENTS + 1)
    if lock:
        query = query.with_for_update()
    people = db.scalars(query).all()
    if len(people) > MAX_BULK_CONSENTS:
        raise HTTPException(
            status_code=409, detail="Too many active contacts for one attestation batch",
        )
    latest = _latest_events(db, org, "whatsapp")
    blocked_numbers = _revoked_addresses(db, org, "whatsapp", latest)
    eligible = []
    digest = hashlib.sha256()
    digest.update(f"{org}|whatsapp|active-consent-review-v1\n".encode("utf-8"))
    summary = dict(
        active=len(people), already_documented=0,
        needs_confirmation=0, opted_out=0, no_number=0,
    )
    for person in people:
        address = contact_address(person, "whatsapp")
        event = latest.get(("prospect", person.id))
        # The count alone is insufficient: a reviewed person may be swapped
        # for a different Active person without changing that count.
        # Bind consent confirmation to recipient identity, current address,
        # entity version, latest consent event, and shared-address STOP state.
        digest.update(json.dumps([
            str(person.id), person.version, address,
            str(event.id) if event else "", address in blocked_numbers,
        ], separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
        if not address:
            summary["no_number"] += 1
        elif address in blocked_numbers or (
            event is not None and event.decision == "opted_out"
        ):
            summary["opted_out"] += 1
        elif event and event.decision == "opted_in" and event.evidence_reference:
            summary["already_documented"] += 1
        else:
            summary["needs_confirmation"] += 1
            eligible.append(person)
    summary["review_fingerprint"] = digest.hexdigest()
    return ConsentPreview(**summary), eligible


@router.get("/active-consent-review", response_model=ConsentPreview)
def preview_existing_whatsapp_consent(
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    db: Annotated[Session, Depends(db_session)],
) -> ConsentPreview:
    summary, _ = _selection(db, context[0].organization_id)
    response.headers["Cache-Control"] = "no-store"
    return summary


@router.post("/active-consent-review", response_model=ConsentPreview)
def confirm_existing_whatsapp_consent(
    payload: ConsentConfirmInput,
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    db: Annotated[Session, Depends(db_session)],
) -> ConsentPreview:
    """Only the Admin can attest a pre-existing register; NEVER an auto-opt-in.

    Locks the selected Active records, applies STOP/opt-out constraints, and
    records source/evidence for each confirmation. Never invokes Saasyto.
    """
    admin = context[0]
    summary, chosen = _selection(db, admin.organization_id, lock=True)
    if (summary.needs_confirmation != payload.expected_needs_confirmation
            or not hmac.compare_digest(
                summary.review_fingerprint, payload.expected_review_fingerprint,
            )):
        raise HTTPException(status_code=409, detail="Audience changed; review again")
    now = utc_now()
    for person in chosen:
        event = CommunicationConsentEvent(
            organization_id=admin.organization_id,
            recipient_kind="prospect", recipient_id=person.id,
            channel="whatsapp", decision="opted_in",
            source=payload.source, evidence_reference=payload.evidence_reference,
            actor_admin_id=admin.id, recorded_at=now,
        )
        db.add(event)
        if not person.whatsapp_opt_in:
            person.whatsapp_opt_in = True
            person.version += 1
        db.add(AuditEvent(
            organization_id=admin.organization_id, actor_admin_id=admin.id,
            action="communication.existing_consent_attested",
            entity_type="prospect", entity_id=str(person.id),
            after_data={"channel":"whatsapp","decision":"opted_in",
                        "source":payload.source},
        ))
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    updated, _ = _selection(db, admin.organization_id)
    return updated
