"""Tenant-scoped hard deletion of CRM records with no protected business history."""
import uuid
from datetime import timedelta

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models import Base, Promoter, PromoterAssignment, Prospect, SponsorOtpChallenge
from app.security import utc_now

# These are CRM metadata, not posted transactions or communication evidence.
# All other linked tables retain the existing fail-closed protection.
REMOVABLE_PROSPECT = {
    "sponsor_otp_challenges", "promoter_assignments", "prospect_followups",
    "prospect_stage_transitions", "prospect_archive_intervals", "prospect_upi_ids",
}
REMOVABLE_PROMOTER = {"promoter_assignments"}


class DeleteConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    confirmation: str


def require_confirmation(value: str) -> None:
    if value != "DELETE":
        raise HTTPException(status_code=422, detail="Explicit DELETE confirmation is required")


def check_dependencies(
    db: Session, organization_id: uuid.UUID, identity_id: uuid.UUID,
    *, kind: str,
) -> None:
    """Reject financial, consent, dispatch and unrecognized dependencies."""
    field = "prospect_id" if kind == "prospect" else "promoter_id"
    allowed = REMOVABLE_PROSPECT if kind == "prospect" else REMOVABLE_PROMOTER
    for table in Base.metadata.tables.values():
        if table.name in ("prospects", "promoters"):
            continue
        if field in table.c:
            clause = table.c[field] == identity_id
        elif "recipient_id" in table.c and "recipient_kind" in table.c:
            clause = (
                (table.c.recipient_id == identity_id)
                & (table.c.recipient_kind == kind)
            )
        else:
            continue
        if "organization_id" in table.c:
            clause = clause & (table.c.organization_id == organization_id)
        count = db.scalar(select(func.count()).select_from(table).where(clause)) or 0
        if table.name == "sponsorship_rates" and kind == "prospect" and count <= 1:
            continue
        if table.name in allowed:
            if table.name == "sponsor_otp_challenges" and count:
                # OTP issuance is rate-limited per phone over the preceding 24h.
                # Do not delete those counters or an in-flight provider request.
                recent = db.scalar(select(func.count()).select_from(SponsorOtpChallenge).where(
                    SponsorOtpChallenge.organization_id == organization_id,
                    SponsorOtpChallenge.prospect_id == identity_id,
                    SponsorOtpChallenge.created_at >= utc_now() - timedelta(days=1),
                ))
                if recent:
                    raise HTTPException(
                        status_code=409,
                        detail="Recent OTP history must be retained for 24 hours after issuance.",
                    )
            continue
        if count:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Permanent deletion is blocked: this "
                    + kind + " has protected " + table.name.replace("_", " ")
                    + " history. Financial and communication evidence must be retained."
                ),
            )


def purge_removable_dependencies(
    db: Session, organization_id: uuid.UUID, identity_id: uuid.UUID,
    *, kind: str,
) -> dict[str, int]:
    """Remove permitted metadata after the guard has passed, in the same transaction."""
    field = "prospect_id" if kind == "prospect" else "promoter_id"
    allowed = REMOVABLE_PROSPECT if kind == "prospect" else REMOVABLE_PROMOTER
    assignments = PromoterAssignment.__table__
    other_field = "promoter_id" if kind == "prospect" else "prospect_id"
    other = Promoter.__table__ if kind == "prospect" else Prospect.__table__
    linked = select(assignments.c[other_field]).where(
        assignments.c.organization_id == organization_id,
        assignments.c[field] == identity_id,
        assignments.c.ended_at.is_(None),
    )
    # A current assignment disappears, so invalidate stale versions on the
    # surviving contacts. Never delete those contacts.
    db.execute(update(other).where(
        other.c.organization_id == organization_id,
        other.c.id.in_(linked),
    ).values(version=other.c.version + 1, updated_at=utc_now()))
    counts: dict[str, int] = {}
    for name in sorted(allowed):
        table = Base.metadata.tables[name]
        result = db.execute(delete(table).where(
            table.c.organization_id == organization_id,
            table.c[field] == identity_id,
        ))
        if result.rowcount:
            counts[name] = result.rowcount
    return counts
