"""Tenant-scoped, versioned, auditable configuration for payout purpose choices.

No financial ledger value is mutated when an option is renamed/deactivated.
"""
import uuid
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OrganizationFieldOption

FieldKey = Literal["payout_purpose"]
DEFAULT_PAYOUT_PURPOSES = (
    "Rent", "Utilities", "Maintenance", "Salary",
    "Vendor payment", "Reimbursement", "Other",
)


def normalize_label(value: str) -> str:
    return " ".join(value.split())


def label_key(value: str) -> str:
    return normalize_label(value).casefold()


def seed_payout_purposes(db: Session, organization_id: uuid.UUID) -> None:
    """Only for new organizations, before their first financial entry."""
    for order, label in enumerate(DEFAULT_PAYOUT_PURPOSES, start=1):
        db.add(OrganizationFieldOption(
            organization_id=organization_id,
            field_key="payout_purpose",
            code="default-" + label_key(label).replace(" ", "-"),
            label=label,
            label_key=label_key(label),
            sort_order=order * 10,
            version=1, is_active=True,
        ))


def resolve_payout_purpose(
    db: Session, organization_id: uuid.UUID,
    purpose: str, option_id: uuid.UUID | None,
) -> OrganizationFieldOption:
    """Reject unapproved labels, inactive choices and cross-tenant IDs.

    The optional identifier preserves older API consumers that submit an
    *existing approved label*; new clients should always send the ID.
    """
    norm = normalize_label(purpose)
    if option_id is not None:
        choice = db.scalars(select(OrganizationFieldOption).where(
            OrganizationFieldOption.organization_id == organization_id,
            OrganizationFieldOption.id == option_id,
            OrganizationFieldOption.field_key == "payout_purpose",
        )).one_or_none()
        if choice is None:
            raise HTTPException(status_code=422, detail="Unknown payout purpose")
        if label_key(norm) != choice.label_key:
            raise HTTPException(
                status_code=422, detail="Payout purpose does not match the selected option",
            )
    else:
        choice = db.scalars(select(OrganizationFieldOption).where(
            OrganizationFieldOption.organization_id == organization_id,
            OrganizationFieldOption.field_key == "payout_purpose",
            OrganizationFieldOption.label_key == label_key(norm),
        )).one_or_none()
    if choice is None or not choice.is_active:
        raise HTTPException(
            status_code=422, detail="Choose an active payout purpose from Settings",
        )
    return choice
