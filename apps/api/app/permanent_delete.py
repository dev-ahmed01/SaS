"""Conservative, tenant-scoped permanent removal for unused CRM identities.

Financial entries, past assignments and communication/activation history block
hard-delete. Audit events remain immutable even after an unused identity is
removed; archiving remains available through the existing legacy endpoint.
"""
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Base


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
    """A real registration rate can be removed, but not any business history.

    Enumerate all mapped tables so future modules automatically fail closed
    when they add new direct CRM identity references.
    """
    field = "prospect_id" if kind == "prospect" else "promoter_id"
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
        if count:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Permanent deletion is blocked: this "
                    + kind + " has linked " + table.name.replace("_", " ")
                    + " history. Records with history must be retained."
                ),
            )
