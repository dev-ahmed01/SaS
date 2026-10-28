"""Single-recipient WhatsApp revalidation for large approved queues.

The legacy batch reviewer loads the whole 10k audience. Calling it once per
send would multiply work by 10k; this path evaluates only the claimed person,
their financial status and same-address consent revocations.
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.accounting import (
    effective_credits,
    evaluate_status,
    ist_today,
    month_start,
    period_balance,
)
from app.communication_consent import contact_address
from app.models import (
    CommunicationCampaign,
    CommunicationConsentEvent,
    Promoter,
    PromoterAssignment,
    Prospect,
    SponsorshipRate,
)


def _latest(
    db: Session, org: UUID, kind: str, identifier: UUID,
) -> CommunicationConsentEvent | None:
    return db.scalars(select(CommunicationConsentEvent).where(
        CommunicationConsentEvent.organization_id == org,
        CommunicationConsentEvent.recipient_kind == kind,
        CommunicationConsentEvent.recipient_id == identifier,
        CommunicationConsentEvent.channel == "whatsapp",
    ).order_by(
        CommunicationConsentEvent.recorded_at.desc(),
        CommunicationConsentEvent.id.desc(),
    ).limit(1)).first()


def _address_revoked(db: Session, org: UUID, address: str) -> bool:
    # One phone may appear under multiple CRM entities. Their most recent
    # explicit opt-out suppresses every send to that physical address.
    for kind, model in (("prospect", Prospect), ("promoter", Promoter)):
        ids = list(db.scalars(select(model.id).where(
            model.organization_id == org,
            or_(model.mobile_number == address, model.whatsapp_number == address),
        )))
        if not ids:
            continue
        history = db.scalars(select(CommunicationConsentEvent).where(
            CommunicationConsentEvent.organization_id == org,
            CommunicationConsentEvent.recipient_kind == kind,
            CommunicationConsentEvent.recipient_id.in_(ids),
            CommunicationConsentEvent.channel == "whatsapp",
        ).order_by(
            CommunicationConsentEvent.recorded_at.desc(),
            CommunicationConsentEvent.id.desc(),
        ))
        latest_ids = set()
        for event in history:
            if event.recipient_id in latest_ids:
                continue
            latest_ids.add(event.recipient_id)
            if event.decision != "opted_out":
                continue
            # Disallow false positives when mobile number matches but a
            # different explicit WhatsApp number is used for that person.
            person = db.get(model, event.recipient_id)
            if person and contact_address(person, "whatsapp") == address:
                return True
    return False


def _sponsor_financial(
    db: Session, org: UUID, person: Prospect, now: datetime,
) -> tuple[str, bool] | None:
    rates = db.scalars(select(SponsorshipRate).where(
        SponsorshipRate.organization_id == org,
        SponsorshipRate.prospect_id == person.id,
    )).all()
    credits = effective_credits(db, org, sponsor_id=person.id, as_of=now)
    today = ist_today(now)
    try:
        status = evaluate_status(person, rates, credits, today, now)
        due, paid, outstanding, settled = period_balance(
            person, rates, credits, month_start(today), now,
        )
    except ValueError:
        return None
    return status, (due > 0 and outstanding > 0)


def _has_unpaid_assigned(
    db: Session, org: UUID, promoter: Promoter, now: datetime,
) -> bool:
    prospects = db.scalars(select(Prospect).join(
        PromoterAssignment,
        PromoterAssignment.prospect_id == Prospect.id,
    ).where(
        PromoterAssignment.organization_id == org,
        PromoterAssignment.promoter_id == promoter.id,
        PromoterAssignment.ended_at.is_(None),
        Prospect.organization_id == org,
        Prospect.archived_at.is_(None),
        Prospect.crm_stage == "active",
    ))
    for person in prospects:
        result = _sponsor_financial(db, org, person, now)
        if result and result[0] != "inactive" and result[1]:
            return True
    return False


def eligible_for_approved_whatsapp(
    db: Session, org: UUID, person: Prospect | Promoter,
    campaign: CommunicationCampaign, now: datetime,
) -> bool:
    kind = "prospect" if isinstance(person, Prospect) else "promoter"
    if (kind == "prospect" and campaign.audience not in ("prospects", "both")
        or kind == "promoter" and campaign.audience not in ("promoters", "both")):
        return False
    active = (
        person.crm_stage == "active" if kind == "prospect"
        else person.is_active
    )
    if campaign.segment == "active" and not active:
        return False
    if campaign.segment == "inactive" and active:
        return False
    financial = None
    if kind == "prospect" and (campaign.category == "reminder"
                              or campaign.segment == "unpaid"):
        financial = _sponsor_financial(db, org, person, now)
        if financial is None:
            return False
    if campaign.segment == "unpaid":
        if kind == "prospect":
            if not active or financial[0] == "inactive" or not financial[1]:
                return False
        elif not _has_unpaid_assigned(db, org, person, now):
            return False
    if campaign.category == "reminder":
        if not active or (financial and financial[0] == "inactive"):
            return False

    address = contact_address(person, "whatsapp")
    if not address or _address_revoked(db, org, address):
        return False
    consent = _latest(db, org, kind, person.id)
    if consent and consent.decision == "opted_out":
        return False
    if not (person.whatsapp_opt_in or (consent and
                                      consent.decision == "opted_in" and
                                      bool(consent.evidence_reference))):
        return False
    # An active CRM status or old WhatsApp reminder checkbox alone
    # does not authorize unrelated announcement/update campaigns.
    if campaign.category != "reminder" and not (
        consent and consent.decision == "opted_in"
        and consent.evidence_reference
    ):
        return False
    return True
