"""Honest, tenant-scoped campaign results, never inferred delivery/read receipts.

A Saasyto HTTP success is a gateway *submission*, not proof of phone delivery.
Unverified states and lack of webhook verification are represented explicitly.
No endpoint in this module invokes an outbound provider or updates the queue.
"""
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import db_session, get_admin
from app.models import (
    AdminSession,
    AdminUser,
    CommunicationCampaign,
    CommunicationPreparation,
    CommunicationRecipientSnapshot,
    Promoter,
    Prospect,
    SaasytoCampaignRecipient,
    SaasytoCampaignRun,
)

router = APIRouter(prefix="/v1/communication", tags=["Campaign results"])
MAX_RESULTS = 100
MAX_RECIPIENTS = 2000


class CampaignResultSummary(BaseModel):
    campaign_id: uuid.UUID
    run_status: Literal["not_approved", "approved", "cancelled", "completed"]
    planned: int
    submitted_unverified: int
    rejected: int
    unknown: int
    queued: int
    claimed: int
    suppressed_after_approval: int
    excluded_in_review: int = 0
    delivered: int | None = None
    read: int | None = None


class RecipientResult(BaseModel):
    recipient_kind: Literal["prospect", "promoter"]
    recipient_id: uuid.UUID
    name: str
    phone_masked: str
    status: str
    reason: str | None = None
    finished_at: datetime | None = None


class CampaignResultDetail(BaseModel):
    campaign_id: uuid.UUID
    title: str
    audience: str
    segment: str
    category: str
    channel: str
    planned_for: datetime | None
    created_at: datetime
    summary: CampaignResultSummary
    latest_review_at: datetime | None = None
    eligible_in_review: int = 0
    excluded_in_review: int = 0
    excluded_reasons: dict[str, int] = Field(default_factory=dict)
    recipients: list[RecipientResult] = Field(default_factory=list)
    excluded_recipients: list[RecipientResult] = Field(default_factory=list)
    delivery_notice: str = (
        "Saasyto acceptance confirms only gateway submission. Delivered/read "
        "counts are unavailable until authenticated provider status callbacks "
        "are verified. Unknown outcomes must never be retried automatically."
    )


def _masked(number: str | None) -> str:
    """Never include full donor phone numbers in campaign analytics responses."""
    digits = "".join(ch for ch in (number or "") if ch.isdigit())
    return "•••• " + digits[-4:] if len(digits) >= 4 else "Not available"


def _people(db: Session, org: uuid.UUID, pairs: set[tuple[str, uuid.UUID]]):
    by_kind = defaultdict(set)
    for kind, identifier in pairs:
        by_kind[kind].add(identifier)
    lookup = {}
    for kind, model in (("prospect", Prospect), ("promoter", Promoter)):
        ids = by_kind[kind]
        if not ids:
            continue
        for item in db.scalars(select(model).where(
            model.organization_id == org, model.id.in_(ids),
        )):
            lookup[(kind, item.id)] = item
    return lookup


def _recipient(row, lookup) -> RecipientResult:
    person = lookup.get((row.recipient_kind, row.recipient_id))
    number = (
        person.whatsapp_number or person.mobile_number if person else None
    )
    return RecipientResult(
        recipient_kind=row.recipient_kind, recipient_id=row.recipient_id,
        name=person.full_name if person else "Contact no longer available",
        phone_masked=_masked(number), status=row.status, reason=row.reason,
        finished_at=row.finished_at,
    )


def _summary(campaign_id: uuid.UUID, run: SaasytoCampaignRun | None,
             states: Counter, excluded_in_review: int = 0) -> CampaignResultSummary:
    return CampaignResultSummary(
        campaign_id=campaign_id,
        run_status=run.status if run else "not_approved",
        planned=run.eligible_count if run else 0,
        submitted_unverified=states["accepted_unverified"],
        rejected=states["rejected"],
        unknown=states["unknown"],
        queued=states["queued"],
        claimed=states["claimed"],
        suppressed_after_approval=states["suppressed"],
        excluded_in_review=excluded_in_review,
        delivered=None, read=None,
    )


@router.get("/campaigns/results", response_model=list[CampaignResultSummary])
def campaign_summaries(
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    db: Annotated[Session, Depends(db_session)],
) -> list[CampaignResultSummary]:
    """Bounded list matched to the CRM's most recent 100 campaigns."""
    org = context[0].organization_id
    campaigns = db.scalars(select(CommunicationCampaign).where(
        CommunicationCampaign.organization_id == org,
    ).order_by(
        CommunicationCampaign.created_at.desc(), CommunicationCampaign.id.desc(),
    ).limit(MAX_RESULTS)).all()
    if not campaigns:
        response.headers["Cache-Control"] = "no-store"
        return []
    ids = [row.id for row in campaigns]
    runs = {row.campaign_id: row for row in db.scalars(
        select(SaasytoCampaignRun).where(
            SaasytoCampaignRun.organization_id == org,
            SaasytoCampaignRun.campaign_id.in_(ids),
        ),
    )}
    totals = defaultdict(Counter)
    run_ids = [row.id for row in runs.values()]
    if run_ids:
        for run_id, state in db.execute(select(
            SaasytoCampaignRecipient.run_id, SaasytoCampaignRecipient.status,
        ).where(
            SaasytoCampaignRecipient.organization_id == org,
            SaasytoCampaignRecipient.run_id.in_(run_ids),
        )):
            totals[run_id][state] += 1
    # Show pre-approval failures too, not only worker-run failures.
    # Latest snapshot per campaign, not an accumulated total of rechecks.
    latest = {}
    for prep in db.scalars(select(CommunicationPreparation).where(
        CommunicationPreparation.organization_id == org,
        CommunicationPreparation.campaign_id.in_(ids),
    ).order_by(
        CommunicationPreparation.evaluated_at.desc(),
        CommunicationPreparation.id.desc(),
    )):
        latest.setdefault(prep.campaign_id, prep.suppressed_count)
    response.headers["Cache-Control"] = "no-store"
    return [
        _summary(c.id, runs.get(c.id),
                 totals[runs[c.id].id] if c.id in runs else Counter(),
                 latest.get(c.id, 0))
        for c in campaigns
    ]


@router.get("/campaigns/{identifier}/results", response_model=CampaignResultDetail)
def campaign_detail(
    identifier: uuid.UUID, response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    db: Annotated[Session, Depends(db_session)],
) -> CampaignResultDetail:
    org = context[0].organization_id
    campaign = db.scalars(select(CommunicationCampaign).where(
        CommunicationCampaign.id == identifier,
        CommunicationCampaign.organization_id == org,
    )).one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    run = db.scalars(select(SaasytoCampaignRun).where(
        SaasytoCampaignRun.organization_id == org,
        SaasytoCampaignRun.campaign_id == campaign.id,
    )).one_or_none()
    queue = db.scalars(select(SaasytoCampaignRecipient).where(
        SaasytoCampaignRecipient.organization_id == org,
        SaasytoCampaignRecipient.run_id == run.id,
    ).order_by(SaasytoCampaignRecipient.id)).limit(MAX_RECIPIENTS)).all() if run else []
    preflight = db.scalars(select(CommunicationPreparation).where(
        CommunicationPreparation.organization_id == org,
        CommunicationPreparation.campaign_id == campaign.id,
    ).order_by(
        CommunicationPreparation.evaluated_at.desc(),
        CommunicationPreparation.id.desc(),
    ).limit(1)).one_or_none()
    excluded = db.scalars(select(CommunicationRecipientSnapshot).where(
        CommunicationRecipientSnapshot.organization_id == org,
        CommunicationRecipientSnapshot.preparation_id == preflight.id,
        CommunicationRecipientSnapshot.status == "suppressed",
    ).order_by(CommunicationRecipientSnapshot.id).limit(MAX_RECIPIENTS)).all() if preflight else []

    keys = {(row.recipient_kind, row.recipient_id) for row in [*queue, *excluded]}
    lookup = _people(db, org, keys)
    counts = Counter(row.status for row in queue)
    reasons = Counter(row.suppression_reason for row in excluded)
    reasons.pop(None, None)
    response.headers["Cache-Control"] = "no-store"
    return CampaignResultDetail(
        campaign_id=campaign.id, title=campaign.title,
        audience=campaign.audience, segment=campaign.segment,
        category=campaign.category, channel=campaign.channel,
        planned_for=campaign.planned_for, created_at=campaign.created_at,
        summary=_summary(campaign.id, run, counts,
                         preflight.suppressed_count if preflight else 0),
        latest_review_at=preflight.evaluated_at if preflight else None,
        eligible_in_review=preflight.eligible_count if preflight else 0,
        excluded_in_review=preflight.suppressed_count if preflight else 0,
        excluded_reasons=dict(reasons),
        recipients=[_recipient(row, lookup) for row in queue],
        excluded_recipients=[
            RecipientResult(
                recipient_kind=row.recipient_kind, recipient_id=row.recipient_id,
                name=(lookup.get((row.recipient_kind, row.recipient_id)).full_name
                      if lookup.get((row.recipient_kind, row.recipient_id))
                      else "Contact no longer available"),
                phone_masked=_masked(
                    (person.whatsapp_number or person.mobile_number)
                    if (person := lookup.get((row.recipient_kind, row.recipient_id)))
                    else None
                ),
                status="excluded", reason=row.suppression_reason,
            ) for row in excluded
        ],
    )
