"""Tenant-scoped CRM removal with financial and communication safeguards."""
import uuid
from datetime import timedelta

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models import Base, Promoter, PromoterAssignment, SponsorOtpChallenge
from app.security import utc_now


class DeleteConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    confirmation: str


def require_confirmation(value: str) -> None:
    if value != "DELETE":
        raise HTTPException(status_code=422, detail="Explicit DELETE confirmation is required")


def check_dependencies(
    db: Session, organization_id: uuid.UUID, identity_id: uuid.UUID,
    *, kind: str, allowed_tables: frozenset[str] = frozenset(),
) -> None:
    """A real registration rate can be removed, but not any business history.

    Enumerate all mapped tables so future modules automatically fail closed
    when they add new direct CRM identity references.
    """
    field = "prospect_id" if kind == "prospect" else "promoter_id"
    for table in Base.metadata.tables.values():
        if table.name in ("prospects", "promoters") or table.name in allowed_tables:
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
        if count:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Permanent deletion is blocked: this "
                    + kind + " has linked " + table.name.replace("_", " ")
                    + " history. Records with history must be retained."
                ),
            )


# Only these non-financial prospect dependencies may be removed.
REMOVABLE_PROSPECT = frozenset({
    "sponsor_otp_challenges", "promoter_assignments", "prospect_followups",
    "prospect_stage_transitions", "prospect_archive_intervals", "prospect_upi_ids",
})


def purge_prospect_dependencies(
    db: Session, organization_id: uuid.UUID, prospect_id: uuid.UUID,
) -> dict[str, int]:
    """Check and remove eligible CRM metadata in the prospect deletion transaction."""
    check_dependencies(
        db, organization_id, prospect_id, kind="prospect",
        allowed_tables=REMOVABLE_PROSPECT,
    )
    now = utc_now()
    recent = db.scalar(select(func.count()).select_from(SponsorOtpChallenge).where(
        SponsorOtpChallenge.organization_id == organization_id,
        SponsorOtpChallenge.prospect_id == prospect_id,
        SponsorOtpChallenge.created_at >= now - timedelta(days=1),
    ))
    if recent:
        raise HTTPException(
            status_code=409,
            detail="Recent OTP history must be retained for 24 hours after issuance.",
        )
    assignments = PromoterAssignment.__table__
    linked = select(assignments.c.promoter_id).where(
        assignments.c.organization_id == organization_id,
        assignments.c.prospect_id == prospect_id,
        assignments.c.ended_at.is_(None),
    )
    other = Promoter.__table__
    db.execute(update(other).where(
        other.c.organization_id == organization_id,
        other.c.id.in_(linked),
    ).values(version=other.c.version + 1, updated_at=now))
    counts: dict[str, int] = {}
    for name in sorted(REMOVABLE_PROSPECT):
        table = Base.metadata.tables[name]
        result = db.execute(delete(table).where(
            table.c.organization_id == organization_id,
            table.c.prospect_id == prospect_id,
        ))
        if result.rowcount:
            counts[name] = result.rowcount
    return counts
