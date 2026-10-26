"""One stable tenant-scoped registration pipeline stage, independent of its name."""
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProspectStageDefinition

REGISTRATION_STAGE_KEY = "registration_new_inquiry"
DEFAULT_DESCRIPTION = "Awaiting first documented follow-up"


def get_registration_stage(db: Session, organization_id: uuid.UUID) -> ProspectStageDefinition:
    stage = db.scalars(select(ProspectStageDefinition).where(
        ProspectStageDefinition.organization_id == organization_id,
        ProspectStageDefinition.system_key == REGISTRATION_STAGE_KEY,
    )).one_or_none()
    if stage is not None:
        return stage

    # Backfill any pre-migration organization lazily. Never make an activation
    # or payment decision based on a mutable stage name.
    rows = db.scalars(select(ProspectStageDefinition).where(
        ProspectStageDefinition.organization_id == organization_id,
    )).all()
    named = [row for row in rows if row.name_key == "new inquiry" and not row.system_key]
    described = [
        row for row in rows
        if row.description == DEFAULT_DESCRIPTION and not row.system_key
    ]
    candidates = named or described
    if len(candidates) == 1:
        stage = candidates[0]
        stage.system_key = REGISTRATION_STAGE_KEY
        db.flush()
        return stage

    if not candidates:
        stage = ProspectStageDefinition(
            organization_id=organization_id,
            name="New Inquiry", name_key="new inquiry",
            system_key=REGISTRATION_STAGE_KEY,
            description=DEFAULT_DESCRIPTION,
            color="#64748b", sort_order=0, version=1,
        )
        db.add(stage)
        db.flush()
        return stage

    raise HTTPException(
        status_code=409,
        detail="Ambiguous legacy registration stage. Review existing stages.",
    )
