"""Secure communication planning and live IST audience preview.

This module never sends WhatsApp, emails, or schedules dispatch jobs. Existing
payment/reminder Pabbly transport is separately approved, gated and audited.
Saved plans cannot bypass that transport or manufacture delivery evidence.
"""
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounting import effective_credits, ist_today, month_start, period_balance
from app.auth import db_session, get_admin, require_csrf
from app.models import (
    AdminSession,
    AdminUser,
    AuditEvent,
    CommunicationCampaign,
    CommunicationConsentEvent,
    CommunicationPreparation,
    CommunicationRecipientSnapshot,
    CommunicationRule,
    CommunicationTemplate,
    Promoter,
    PromoterAssignment,
    Prospect,
    SponsorshipRate,
)
from app.communication_consent import evaluate_recipients
from app.security import utc_now

router = APIRouter(prefix="/v1/communication", tags=["Admin communication planning"])
Channel = Literal["whatsapp", "email"]
Audience = Literal["prospects", "promoters", "both"]
Segment = Literal["all", "active", "inactive", "unpaid"]
Category = Literal["update", "reminder", "announcement", "thank_you", "invitation", "other"]
Trigger = Literal[
    "monthly_sponsor", "monthly_promoter", "payment_received", "prospect_stage_changed",
    "scheduled_date", "manual",
]
IST = ZoneInfo("Asia/Kolkata")
MAX_AUDIENCE_ROWS = 2000


def _audit(db: Session, admin: AdminUser, action: str, kind: str, target: uuid.UUID,
           details: dict | None = None) -> None:
    db.add(AuditEvent(
        organization_id=admin.organization_id, actor_admin_id=admin.id,
        action=action, entity_type=kind, entity_id=str(target),
        after_data=details or {},
    ))


def _clean(text: str) -> str:
    return " ".join(text.split())


class TemplateFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=100)
    channel: Channel
    category: Category
    subject: str | None = Field(default=None, max_length=160)
    body: str = Field(min_length=3, max_length=1200)
    provider_template_id: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def clean(self) -> "TemplateFields":
        self.name = _clean(self.name)
        self.body = self.body.strip()
        self.subject = self.subject.strip() or None if self.subject else None
        self.provider_template_id = (
            self.provider_template_id.strip() or None if self.provider_template_id else None
        )
        if len(self.name) < 2 or len(self.body) < 3:
            raise ValueError("Provide a name and message body")
        if self.channel == "email" and not self.subject:
            raise ValueError("Email needs a subject")
        if self.channel == "whatsapp" and self.subject:
            raise ValueError("WhatsApp messages have no email subject")
        return self


class TemplateUpdate(TemplateFields):
    version: int = Field(ge=1)


class TemplateRead(TemplateFields):
    id: uuid.UUID
    version: int
    created_at: datetime
    archived: bool


class CampaignInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    title: str = Field(min_length=2, max_length=120)
    template_id: uuid.UUID | None = None
    channel: Channel
    audience: Audience
    segment: Segment
    category: Category
    subject: str | None = Field(default=None, max_length=160)
    body: str = Field(min_length=3, max_length=1200)
    provider_template_id: str | None = Field(default=None, max_length=160)
    planned_for: datetime | None = None

    @model_validator(mode="after")
    def check(self) -> "CampaignInput":
        self.title = _clean(self.title)
        self.body = self.body.strip()
        self.subject = self.subject.strip() or None if self.subject else None
        self.provider_template_id = (
            self.provider_template_id.strip() or None if self.provider_template_id else None
        )
        if len(self.title) < 2 or len(self.body) < 3:
            raise ValueError("Provide a campaign title and message")
        if self.channel == "email" and not self.subject:
            raise ValueError("Email needs a subject")
        if self.channel == "whatsapp" and self.subject:
            raise ValueError("WhatsApp does not have an email subject")
        if self.segment == "inactive" and self.category == "reminder":
            raise ValueError("Inactive contacts must not receive reminders")
        if self.planned_for is not None:
            if self.planned_for.tzinfo is None:
                raise ValueError("Schedule needs an explicit timezone")
            self.planned_for = self.planned_for.astimezone(IST)
            if self.planned_for <= utc_now().astimezone(IST):
                raise ValueError("Scheduled time must be in the future")
        return self


class CampaignRead(BaseModel):
    id: uuid.UUID
    title: str
    channel: str
    audience: str
    segment: str
    category: str
    subject: str | None
    body: str
    status: str
    planned_for: datetime | None
    eligible_snapshot: int
    candidate_snapshot: int
    created_at: datetime


class RuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=100)
    template_id: uuid.UUID
    trigger_kind: Trigger
    audience: Audience
    segment: Segment

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        clean = _clean(value)
        if len(clean) < 2:
            raise ValueError("Give the automation a name")
        return clean


class RuleRead(BaseModel):
    id: uuid.UUID
    name: str
    trigger_kind: str
    channel: str
    audience: str
    segment: str
    template_id: uuid.UUID
    active: Literal[False] = False
    created_at: datetime


class AudiencePreview(BaseModel):
    candidate_count: int
    eligible_count: int
    suppressed_count: int
    sample_names: list[str]
    channel_ready: bool
    notice: str
    as_of_ist: datetime


def _template(db: Session, admin: AdminUser, identifier: uuid.UUID, lock=False):
    statement = select(CommunicationTemplate).where(
        CommunicationTemplate.id == identifier,
        CommunicationTemplate.organization_id == admin.organization_id,
        CommunicationTemplate.archived_at.is_(None),
    )
    if lock:
        statement = statement.with_for_update()
    row = db.scalars(statement).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return row


def _template_read(t: CommunicationTemplate) -> TemplateRead:
    return TemplateRead(
        id=t.id, name=t.name, channel=t.channel, category=t.category,
        subject=t.subject, body=t.body, provider_template_id=t.provider_template_id,
        version=t.version, archived=t.archived_at is not None, created_at=t.created_at,
    )


def _audience_rows(
    db: Session, admin: AdminUser, audience: Audience, segment: Segment, now: datetime,
) -> list:
    org = admin.organization_id
    prospects = []
    promoters = []
    if audience in ("prospects", "both"):
        prospects = list(db.scalars(select(Prospect).where(
            Prospect.organization_id == org, Prospect.archived_at.is_(None),
        ).limit(MAX_AUDIENCE_ROWS + 1)).all())
    if audience in ("promoters", "both"):
        promoters = list(db.scalars(select(Promoter).where(
            Promoter.organization_id == org,
        ).limit(MAX_AUDIENCE_ROWS + 1)).all())
    if len(prospects) + len(promoters) > MAX_AUDIENCE_ROWS:
        raise HTTPException(status_code=422, detail="Audience too large to preview safely")
    month = month_start(ist_today(now))
    unpaid_ids = set()
    if segment == "unpaid":
        relevant = [p for p in prospects if p.crm_stage == "active"]
        # For promoter reminders, include all active sponsor assignments.
        if audience == "promoters":
            relevant = list(db.scalars(select(Prospect).where(
                Prospect.organization_id == org, Prospect.archived_at.is_(None),
                Prospect.crm_stage == "active",
            ).limit(MAX_AUDIENCE_ROWS + 1)).all())
        if len(relevant) > MAX_AUDIENCE_ROWS:
            raise HTTPException(status_code=422, detail="Audience too large to preview safely")
        rates = db.scalars(select(SponsorshipRate).where(
            SponsorshipRate.organization_id == org,
        )).all()
        by_sponsor = defaultdict(list)
        for rate in rates:
            by_sponsor[rate.prospect_id].append(rate)
        credits = defaultdict(list)
        for row in effective_credits(db, org, as_of=now):
            credits[row.prospect_id].append(row)
        for person in relevant:
            due, paid, unpaid, _ = period_balance(
                person, by_sponsor[person.id], credits[person.id], month, now,
            )
            if due > 0 and unpaid > 0:
                unpaid_ids.add(person.id)

    assignments = defaultdict(set)
    if segment == "unpaid" and promoters:
        for row in db.scalars(select(PromoterAssignment).where(
            PromoterAssignment.organization_id == org,
            PromoterAssignment.ended_at.is_(None),
        )):
            if row.prospect_id in unpaid_ids:
                assignments[row.promoter_id].add(row.prospect_id)

    candidates = []
    for person in prospects:
        is_active = person.crm_stage == "active"
        if ((segment == "active" and not is_active)
            or (segment == "inactive" and is_active)
            or (segment == "unpaid" and person.id not in unpaid_ids)):
            continue
        candidates.append(person)
    for person in promoters:
        is_active = person.is_active
        if ((segment == "active" and not is_active)
            or (segment == "inactive" and is_active)
            or (segment == "unpaid" and not assignments[person.id])):
            continue
        candidates.append(person)

    return candidates


def _audience_preview(
    db: Session, admin: AdminUser, audience: Audience, segment: Segment,
    channel: Channel, now: datetime, category: Category = "reminder",
) -> AudiencePreview:
    candidates = _audience_rows(db, admin, audience, segment, now)
    decisions = evaluate_recipients(
        db, admin.organization_id, candidates, channel, category
    )
    eligible = [person.full_name for person, _, state, _ in decisions if state == "eligible"]
    return AudiencePreview(
        candidate_count=len(candidates),
        eligible_count=len(eligible),
        suppressed_count=len(candidates) - len(eligible),
        sample_names=eligible[:6],
        channel_ready=False,
        notice=(
            "Email eligibility needs recorded explicit consent. No email "
            "provider is connected; this is only a review."
            if channel == "email" else
            "Consent-ready is not approval to send. WhatsApp requires provider "
            "templates and renewed send-time permission checks."
        ),
        as_of_ist=now.astimezone(IST),
    )

class ConsentDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient_kind: Literal["prospect", "promoter"]
    recipient_id: uuid.UUID
    channel: Channel
    decision: Literal["opted_in", "opted_out"]
    source: str = Field(min_length=3, max_length=80)
    evidence_reference: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def evidence_required(self) -> "ConsentDecisionInput":
        self.source = _clean(self.source)
        self.evidence_reference = (
            self.evidence_reference.strip() or None if self.evidence_reference else None
        )
        if len(self.source) < 3:
            raise ValueError("Consent source required")
        if self.decision == "opted_in" and not self.evidence_reference:
            raise ValueError("A reference to documented permission is required")
        return self


class ConsentDecisionRead(BaseModel):
    id: uuid.UUID
    recipient_kind: str
    recipient_id: uuid.UUID
    channel: str
    decision: str
    source: str
    recorded_at: datetime


class PreparationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    simulation_only: Literal[True]


class PreparationRead(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    eligible_count: int
    suppressed_count: int
    evaluated_at: datetime
    delivery_activated: Literal[False] = False


def _preparation_read(row: CommunicationPreparation) -> PreparationRead:
    return PreparationRead(
        id=row.id, campaign_id=row.campaign_id,
        eligible_count=row.eligible_count, suppressed_count=row.suppressed_count,
        evaluated_at=row.evaluated_at, delivery_activated=False,
    )


@router.post("/consent-events", response_model=ConsentDecisionRead, status_code=201)
def record_consent(
    payload: ConsentDecisionInput,
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
) -> ConsentDecisionRead:
    admin = context[0]
    model = Prospect if payload.recipient_kind == "prospect" else Promoter
    person = database.scalars(select(model).where(
        model.organization_id == admin.organization_id,
        model.id == payload.recipient_id,
    )).one_or_none()
    if person is None:
        raise HTTPException(status_code=404, detail="Recipient not found")
    if payload.decision == "opted_in" and (
        (payload.channel == "email" and not person.email) or
        (payload.channel == "whatsapp" and not (
            person.whatsapp_number or person.mobile_number
        ))
    ):
        raise HTTPException(status_code=422, detail="Recipient has no channel address")
    event = CommunicationConsentEvent(
        organization_id=admin.organization_id,
        recipient_kind=payload.recipient_kind, recipient_id=person.id,
        channel=payload.channel, decision=payload.decision,
        source=payload.source, evidence_reference=payload.evidence_reference,
        actor_admin_id=admin.id, recorded_at=utc_now(),
    )
    database.add(event)
    database.flush()
    _audit(database, admin, "communication.consent_recorded", "comm_consent", event.id,
           {"channel": event.channel, "decision": event.decision,
            "recipient_kind": event.recipient_kind})
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return ConsentDecisionRead(
        id=event.id, recipient_kind=event.recipient_kind, recipient_id=event.recipient_id,
        channel=event.channel, decision=event.decision, source=event.source,
        recorded_at=event.recorded_at,
    )


@router.post(
    "/campaigns/{identifier}/preparations", response_model=PreparationRead, status_code=201,
)
def simulate_preparation(
    identifier: uuid.UUID, payload: PreparationInput,
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
) -> PreparationRead:
    """Immutable read-time recipient review. It has no outbound transport."""
    admin = context[0]
    campaign = database.scalars(select(CommunicationCampaign).where(
        CommunicationCampaign.id == identifier,
        CommunicationCampaign.organization_id == admin.organization_id,
    ).with_for_update()).one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status == "cancelled":
        raise HTTPException(status_code=409, detail="Cancelled campaign cannot be prepared")
    prior = database.scalars(select(CommunicationPreparation).where(
        CommunicationPreparation.organization_id == admin.organization_id,
        CommunicationPreparation.request_id == payload.request_id,
    )).one_or_none()
    if prior:
        if prior.campaign_id != campaign.id:
            raise HTTPException(status_code=409, detail="Request ID already used")
        response.status_code = 200
        response.headers["Cache-Control"] = "no-store"
        return _preparation_read(prior)
    count = database.scalar(select(func.count(CommunicationPreparation.id)).where(
        CommunicationPreparation.organization_id == admin.organization_id,
        CommunicationPreparation.campaign_id == campaign.id,
    )) or 0
    if count >= 20:
        raise HTTPException(status_code=409, detail="Preparation history limit reached")
    now = utc_now()
    candidates = _audience_rows(
        database, admin, campaign.audience, campaign.segment, now
    )
    decisions = evaluate_recipients(
        database, admin.organization_id, candidates, campaign.channel, campaign.category
    )
    eligible = sum(state == "eligible" for _, _, state, _ in decisions)
    prep = CommunicationPreparation(
        organization_id=admin.organization_id, campaign_id=campaign.id,
        request_id=payload.request_id, eligible_count=eligible,
        suppressed_count=len(decisions) - eligible, evaluated_at=now,
        created_by_admin_id=admin.id,
    )
    database.add(prep)
    database.flush()
    for person, kind, state, reason in decisions:
        database.add(CommunicationRecipientSnapshot(
            organization_id=admin.organization_id, preparation_id=prep.id,
            recipient_kind=kind, recipient_id=person.id,
            channel=campaign.channel, status=state, suppression_reason=reason,
        ))
    _audit(database, admin, "communication.preflight_completed", "comm_prep", prep.id,
           {"campaign_id": str(campaign.id), "eligible": eligible,
            "suppressed": prep.suppressed_count, "simulation_only": True})
    try:
        database.commit()
    except IntegrityError as exc:
        database.rollback()
        raise HTTPException(status_code=409, detail="Preparation already recorded") from exc
    response.headers["Cache-Control"] = "no-store"
    return _preparation_read(prep)


@router.get("/campaigns/{identifier}/preparations", response_model=list[PreparationRead])
def list_preparations(
    identifier: uuid.UUID, response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
) -> list[PreparationRead]:
    organization_id = context[0].organization_id
    exists = database.scalar(select(CommunicationCampaign.id).where(
        CommunicationCampaign.organization_id == organization_id,
        CommunicationCampaign.id == identifier,
    ))
    if exists is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    response.headers["Cache-Control"] = "no-store"
    return [_preparation_read(row) for row in database.scalars(
        select(CommunicationPreparation).where(
            CommunicationPreparation.organization_id == organization_id,
            CommunicationPreparation.campaign_id == identifier,
        ).order_by(CommunicationPreparation.evaluated_at.desc()).limit(20)
    )]


@router.get("/clock")
def clock(
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return {"now_ist": utc_now().astimezone(IST).isoformat(),
            "timezone": "Asia/Kolkata", "server_authoritative": True}


@router.get("/audience", response_model=AudiencePreview)
def preview_audience(
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
    audience: Audience = "prospects", segment: Segment = "active",
    channel: Channel = "whatsapp", category: Category = "reminder",
) -> AudiencePreview:
    response.headers["Cache-Control"] = "no-store"
    return _audience_preview(
        database, context[0], audience, segment, channel, utc_now(), category
    )


@router.get("/templates", response_model=list[TemplateRead])
def list_templates(
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
) -> list[TemplateRead]:
    response.headers["Cache-Control"] = "no-store"
    return [_template_read(row) for row in database.scalars(
        select(CommunicationTemplate).where(
            CommunicationTemplate.organization_id == context[0].organization_id,
            CommunicationTemplate.archived_at.is_(None),
        ).order_by(CommunicationTemplate.name_key).limit(200)
    )]


@router.post("/templates", response_model=TemplateRead, status_code=201)
def create_template(
    payload: TemplateFields,
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
) -> TemplateRead:
    admin = context[0]
    row = CommunicationTemplate(
        organization_id=admin.organization_id, name=payload.name,
        name_key=payload.name.casefold(), channel=payload.channel,
        category=payload.category, subject=payload.subject, body=payload.body,
        provider_template_id=payload.provider_template_id, version=1,
    )
    database.add(row)
    try:
        database.flush()
        _audit(database, admin, "communication.template_created", "comm_template", row.id)
        database.commit()
    except IntegrityError as exc:
        database.rollback()
        raise HTTPException(status_code=409, detail="Template name already exists") from exc
    database.refresh(row)
    response.headers["Cache-Control"] = "no-store"
    return _template_read(row)


@router.patch("/templates/{identifier}", response_model=TemplateRead)
def update_template(
    identifier: uuid.UUID, payload: TemplateUpdate,
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
) -> TemplateRead:
    admin = context[0]
    row = _template(database, admin, identifier, lock=True)
    if row.version != payload.version:
        raise HTTPException(status_code=409, detail="Template changed; refresh")
    changed = []
    for key in ("name", "channel", "category", "subject", "body", "provider_template_id"):
        value = getattr(payload, key)
        if getattr(row, key) != value:
            setattr(row, key, value)
            changed.append(key)
    if changed:
        row.name_key = row.name.casefold()
        row.version += 1
        row.updated_at = utc_now()
        _audit(database, admin, "communication.template_updated", "comm_template", row.id,
               {"fields": changed})
        try:
            database.commit()
        except IntegrityError as exc:
            database.rollback()
            raise HTTPException(status_code=409, detail="Template name exists") from exc
    response.headers["Cache-Control"] = "no-store"
    return _template_read(row)


@router.delete("/templates/{identifier}", status_code=204)
def archive_template(
    identifier: uuid.UUID,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
    version: int = Query(ge=1),
) -> Response:
    admin = context[0]
    row = _template(database, admin, identifier, lock=True)
    if row.version != version:
        raise HTTPException(status_code=409, detail="Template changed; refresh")
    # Preserve both campaign snapshots and automation references.
    if database.scalar(select(func.count(CommunicationRule.id)).where(
        CommunicationRule.organization_id == admin.organization_id,
        CommunicationRule.template_id == row.id,
    )):
        raise HTTPException(status_code=409, detail="Remove linked automations first")
    row.archived_at = utc_now()
    row.version += 1
    _audit(database, admin, "communication.template_archived", "comm_template", row.id)
    database.commit()
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


def _campaign_read(row: CommunicationCampaign) -> CampaignRead:
    return CampaignRead(
        id=row.id, title=row.title, channel=row.channel, audience=row.audience,
        segment=row.segment, category=row.category, subject=row.subject, body=row.body,
        status=row.status, planned_for=row.planned_for,
        eligible_snapshot=row.eligible_snapshot, candidate_snapshot=row.candidate_snapshot,
        created_at=row.created_at,
    )


@router.get("/campaigns", response_model=list[CampaignRead])
def list_campaigns(
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
) -> list[CampaignRead]:
    response.headers["Cache-Control"] = "no-store"
    return [_campaign_read(row) for row in database.scalars(
        select(CommunicationCampaign).where(
            CommunicationCampaign.organization_id == context[0].organization_id,
        ).order_by(CommunicationCampaign.created_at.desc(), CommunicationCampaign.id.desc())
        .limit(100)
    )]


@router.post("/campaigns", response_model=CampaignRead, status_code=201)
def create_campaign(
    payload: CampaignInput, response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
) -> CampaignRead:
    admin = context[0]
    prior = database.scalars(select(CommunicationCampaign).where(
        CommunicationCampaign.organization_id == admin.organization_id,
        CommunicationCampaign.request_id == payload.request_id,
    )).one_or_none()
    if prior:
        if (prior.title != payload.title or prior.body != payload.body
            or prior.audience != payload.audience or prior.segment != payload.segment):
            raise HTTPException(status_code=409, detail="Request identifier reused")
        response.status_code = 200
        return _campaign_read(prior)
    if payload.template_id:
        template = _template(database, admin, payload.template_id)
        if template.channel != payload.channel:
            raise HTTPException(status_code=422, detail="Template channel mismatch")
    else:
        template = None
    now = utc_now()
    preview = _audience_preview(
        database, admin, payload.audience, payload.segment, payload.channel, now,
        payload.category
    )
    if payload.planned_for and payload.planned_for <= now:
        raise HTTPException(status_code=422, detail="Schedule is in the past")
    row = CommunicationCampaign(
        organization_id=admin.organization_id, request_id=payload.request_id,
        title=payload.title, template_id=template.id if template else None,
        channel=payload.channel, audience=payload.audience, segment=payload.segment,
        category=payload.category, subject=payload.subject, body=payload.body,
        provider_template_id=payload.provider_template_id,
        planned_for=payload.planned_for,
        status="scheduled" if payload.planned_for else "draft",
        eligible_snapshot=preview.eligible_count,
        candidate_snapshot=preview.candidate_count,
        created_by_admin_id=admin.id,
    )
    database.add(row)
    database.flush()
    _audit(database, admin, "communication.campaign_planned", "comm_campaign", row.id,
           {"channel": row.channel, "status": row.status,
            "eligible": row.eligible_snapshot})
    database.commit()
    database.refresh(row)
    response.headers["Cache-Control"] = "no-store"
    return _campaign_read(row)


@router.post("/campaigns/{identifier}/cancel", response_model=CampaignRead)
def cancel_campaign(
    identifier: uuid.UUID,
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
) -> CampaignRead:
    admin = context[0]
    row = database.scalars(select(CommunicationCampaign).where(
        CommunicationCampaign.organization_id == admin.organization_id,
        CommunicationCampaign.id == identifier,
    ).with_for_update()).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if row.status != "cancelled":
        row.status = "cancelled"
        _audit(database, admin, "communication.campaign_cancelled", "comm_campaign", row.id)
        database.commit()
    response.headers["Cache-Control"] = "no-store"
    return _campaign_read(row)


def _rule_read(row: CommunicationRule) -> RuleRead:
    return RuleRead(
        id=row.id, name=row.name, trigger_kind=row.trigger_kind,
        channel=row.channel, audience=row.audience,
        segment=row.segment, template_id=row.template_id,
        active=False, created_at=row.created_at,
    )


@router.get("/rules", response_model=list[RuleRead])
def list_rules(
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
) -> list[RuleRead]:
    response.headers["Cache-Control"] = "no-store"
    return [_rule_read(row) for row in database.scalars(
        select(CommunicationRule).where(
            CommunicationRule.organization_id == context[0].organization_id,
        ).order_by(CommunicationRule.created_at.desc()).limit(100)
    )]


@router.post("/rules", response_model=RuleRead, status_code=201)
def create_rule(
    payload: RuleInput, response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
) -> RuleRead:
    admin = context[0]
    template = _template(database, admin, payload.template_id)
    if payload.trigger_kind == "monthly_sponsor":
        if payload.audience != "prospects" or payload.segment != "unpaid":
            raise HTTPException(
                status_code=422, detail="Sponsor reminders require unpaid prospects"
            )
    if payload.trigger_kind == "monthly_promoter":
        if payload.audience != "promoters" or payload.segment != "unpaid":
            raise HTTPException(
                status_code=422, detail="Promoter reminders require unpaid assignments"
            )
    if payload.segment == "inactive" and template.category == "reminder":
        raise HTTPException(status_code=422, detail="Inactive contacts cannot receive reminders")
    row = CommunicationRule(
        organization_id=admin.organization_id,
        name=payload.name, name_key=payload.name.casefold(),
        trigger_kind=payload.trigger_kind, channel=template.channel,
        audience=payload.audience, segment=payload.segment, template_id=template.id,
    )
    database.add(row)
    try:
        database.flush()
        _audit(database, admin, "communication.rule_created", "comm_rule", row.id,
               {"trigger": row.trigger_kind, "active": False})
        database.commit()
    except IntegrityError as exc:
        database.rollback()
        raise HTTPException(status_code=409, detail="Automation name already exists") from exc
    database.refresh(row)
    response.headers["Cache-Control"] = "no-store"
    return _rule_read(row)


@router.delete("/rules/{identifier}", status_code=204)
def delete_rule(
    identifier: uuid.UUID,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
) -> Response:
    admin = context[0]
    row = database.scalars(select(CommunicationRule).where(
        CommunicationRule.organization_id == admin.organization_id,
        CommunicationRule.id == identifier,
    ).with_for_update()).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    _audit(database, admin, "communication.rule_deleted", "comm_rule", row.id)
    database.delete(row)
    database.commit()
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
