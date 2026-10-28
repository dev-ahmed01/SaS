"""Targeted send-time eligibility for large Saasyto queues.

Campaign approval still uses the complete recipient preview and documented
consent checks. This path verifies exactly one approved contact immediately
before sending, avoiding O(audience size) work for every queued message.
"""
from collections import defaultdict
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.accounting import (
    effective_credits, evaluate_status, ist_today, month_start, period_balance,
)
from app.communication_consent import contact_address
from app.models import (
    CommunicationConsentEvent, Promoter, PromoterAssignment, Prospect,
    SponsorshipRate,
)


def _unpaid_sponsor(db: Session, org, person: Prospect, now: datetime) -> bool:
    if person.archived_at is not None or person.crm_stage != "active":
        return False
    rates = list(db.scalars(select(SponsorshipRate).where(
        SponsorshipRate.organization_id == org,
        SponsorshipRate.prospect_id == person.id,
    )))
    credits = effective_credits(db, org, sponsor_id=person.id, as_of=now)
    today = ist_today(now)
    try:
        if evaluate_status(person, rates, credits, today, now) == "inactive":
            return False
        due, _, unpaid, _ = period_balance(
            person, rates, credits, month_start(today), now,
        )
        return due > 0 and unpaid > 0
    except ValueError:
        return False


def live_segment_member(
    db: Session, org, person: Prospect | Promoter,
    audience: str, segment: str, now: datetime,
) -> bool:
    kind = "prospects" if isinstance(person, Prospect) else "promoters"
    if audience not in (kind, "both"):
        return False
    if isinstance(person, Prospect):
        if person.archived_at is not None:
            return False
        active = person.crm_stage == "active"
    else:
        active = person.is_active
    if segment == "active":
        return active
    if segment == "inactive":
        return not active
    if segment == "all":
        return True
    if segment != "unpaid":
        return False
    if isinstance(person, Prospect):
        return _unpaid_sponsor(db, org, person, now)
    # Promoter unpaid segment includes a promoter with at least one currently
    # assigned, still-active, unpaid sponsor (same as the full preview).
    assigned = db.scalars(select(Prospect).join(
        PromoterAssignment,
        PromoterAssignment.prospect_id == Prospect.id,
    ).where(
        PromoterAssignment.organization_id == org,
        PromoterAssignment.promoter_id == person.id,
        PromoterAssignment.ended_at.is_(None),
        Prospect.organization_id == org,
        Prospect.archived_at.is_(None),
        Prospect.crm_stage == "active",
    ))
    return any(_unpaid_sponsor(db, org, sponsor, now) for sponsor in assigned)


def live_whatsapp_permission(
    db: Session, org, person: Prospect | Promoter, category: str, now: datetime,
) -> bool:
    """Re-evaluate opt-outs for every record sharing the *actual* address.

    Only records matching the selected phone are queried, rather than reading
    the entire organization's consent history on every message.
    """
    phone = contact_address(person, "whatsapp")
    if not phone:
        return False
    matching = []
    for model, kind in ((Prospect, "prospect"), (Promoter, "promoter")):
        # Phone numbers are stored as E.164; normalize legacy spaces as well.
        contacts = db.scalars(select(model).where(
            model.organization_id == org,
            or_(
                func.replace(model.whatsapp_number, " ", "") == phone,
                model.mobile_number == phone,
            ),
        ))
        matching.extend((kind, row) for row in contacts
                        if contact_address(row, "whatsapp") == phone)
    own_kind = "prospect" if isinstance(person, Prospect) else "promoter"
    if not any(k == own_kind and row.id == person.id for k, row in matching):
        matching.append((own_kind, person))
    ids_by_kind = defaultdict(list)
    for kind, row in matching:
        ids_by_kind[kind].append(row.id)
    latest = {}
    for kind, ids in ids_by_kind.items():
        events = db.scalars(select(CommunicationConsentEvent).where(
            CommunicationConsentEvent.organization_id == org,
            CommunicationConsentEvent.channel == "whatsapp",
            CommunicationConsentEvent.recipient_kind == kind,
            CommunicationConsentEvent.recipient_id.in_(ids),
        ).order_by(
            CommunicationConsentEvent.recorded_at,
            CommunicationConsentEvent.id,
        ))
        for event in events:
            latest[(kind, event.recipient_id)] = event
    # Any live opt-out on a shared address stops delivery to that number.
    if any(event.decision == "opted_out" for event in latest.values()):
        return False
    own_event = latest.get((own_kind, person.id))
    if not (
        person.whatsapp_opt_in or (
            own_event is not None and own_event.decision == "opted_in"
            and bool(own_event.evidence_reference)
        )
    ):
        return False
    if category != "reminder" and not (
        own_event is not None and own_event.decision == "opted_in"
        and bool(own_event.evidence_reference)
    ):
        return False
    if category == "reminder":
        if isinstance(person, Promoter):
            return person.is_active
        if person.crm_stage != "active":
            return False
        # Reminder-specific inactivity policy is separate from the campaign's
        # selected audience segment and must be checked even for "all".
        rates = list(db.scalars(select(SponsorshipRate).where(
            SponsorshipRate.organization_id == org,
            SponsorshipRate.prospect_id == person.id,
        )))
        credits = effective_credits(db, org, sponsor_id=person.id, as_of=now)
        try:
            return evaluate_status(person, rates, credits, ist_today(now), now) != "inactive"
        except ValueError:
            return False
    return True
