"""Consent evidence and fail-closed, provider-free recipient decisions.

Never create a dispatch, claim delivery, or treat an address as permission.
This module is also used by the separately gated legacy Pabbly sender so a
newly recorded WhatsApp opt-out takes effect before its next attempt.
"""
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounting import effective_credits, evaluate_status, ist_today
from app.models import (
    CommunicationConsentEvent,
    Promoter,
    Prospect,
    SponsorshipRate,
)
from app.security import utc_now


def contact_address(person: Prospect | Promoter, channel: str) -> str:
    raw = (
        person.email if channel == "email"
        else person.whatsapp_number or person.mobile_number
    )
    return (raw or "").strip().casefold().replace(" ", "")


def _latest_events(db: Session, organization_id, channel: str):
    rows = db.scalars(
        select(CommunicationConsentEvent).where(
            CommunicationConsentEvent.organization_id == organization_id,
            CommunicationConsentEvent.channel == channel,
        ).order_by(
            CommunicationConsentEvent.recorded_at,
            CommunicationConsentEvent.id,
        )
    ).all()
    latest = {}
    for row in rows:
        latest[(row.recipient_kind, row.recipient_id)] = row
    return latest


def _revoked_addresses(db: Session, organization_id, channel: str, latest: dict):
    revoked = defaultdict(list)
    for (kind, identifier), event in latest.items():
        if event.decision == "opted_out":
            revoked[kind].append(identifier)
    blocked = set()
    for kind, model in (("prospect", Prospect), ("promoter", Promoter)):
        if not revoked[kind]:
            continue
        for person in db.scalars(select(model).where(
            model.organization_id == organization_id,
            model.id.in_(revoked[kind]),
        )):
            address = contact_address(person, channel)
            if address:
                blocked.add(address)
    return blocked


def address_opted_out(db: Session, organization_id, channel: str, address: str) -> bool:
    """Re-check opt-outs for legacy dispatch, including shared contact numbers."""
    if not address:
        return True
    latest = _latest_events(db, organization_id, channel)
    return address.strip().casefold().replace(" ", "") in _revoked_addresses(
        db, organization_id, channel, latest
    )


def _inactive_reminder_sponsors(
    db: Session, organization_id, candidates: list, now: datetime,
) -> set:
    """Recompute the net-credit inactivity rule, not the stale status cache.

    Approval previews and actual dispatches must apply the same live policy.
    Missing rate history fails closed for reminder delivery.
    """
    prospects = [p for p in candidates if isinstance(p, Prospect)]
    if not prospects:
        return set()
    rates = defaultdict(list)
    for row in db.scalars(select(SponsorshipRate).where(
        SponsorshipRate.organization_id == organization_id,
        SponsorshipRate.prospect_id.in_([p.id for p in prospects]),
    )):
        rates[row.prospect_id].append(row)
    credits = defaultdict(list)
    for row in effective_credits(db, organization_id, as_of=now):
        credits[row.prospect_id].append(row)
    inactive = set()
    today = ist_today(now)
    for person in prospects:
        if person.archived_at is not None:
            inactive.add(person.id)
            continue
        try:
            state = evaluate_status(
                person, rates[person.id], credits[person.id], today, now,
            )
        except ValueError:
            # Missing effective rate is a data-integrity error; never send.
            inactive.add(person.id)
            continue
        if state == "inactive":
            inactive.add(person.id)
    return inactive


def evaluate_recipients(
    db: Session, organization_id, candidates: list, channel: str, category: str,
    now: datetime | None = None,
):
    """Return (person, recipient kind, state, reason) in stable input order.

    No address or donor message copy is persisted in the preparation table.
    A previous consent snapshot is never treated as send-time permission.
    """
    latest = _latest_events(db, organization_id, channel)
    blocked = _revoked_addresses(db, organization_id, channel, latest)
    inactive_reminders = (
        _inactive_reminder_sponsors(db, organization_id, candidates, now or utc_now())
        if category == "reminder" else set()
    )
    seen = set()
    decisions = []
    for person in candidates:
        kind = "prospect" if isinstance(person, Prospect) else "promoter"
        address = contact_address(person, channel)
        event = latest.get((kind, person.id))
        reason = None
        if not address:
            reason = "missing_address"
        elif address in blocked or (event and event.decision == "opted_out"):
            reason = "opted_out"
        elif category == "reminder" and (
            (kind == "prospect" and (
                person.crm_stage != "active" or person.id in inactive_reminders
            )) or
            (kind == "promoter" and not person.is_active)
        ):
            reason = "inactive_reminder"
        elif channel == "email":
            if not event or event.decision != "opted_in" or not event.evidence_reference:
                reason = "no_email_consent"
        elif not person.whatsapp_opt_in:
            reason = "no_whatsapp_consent"
        elif category != "reminder" and (
            not event or event.decision != "opted_in" or not event.evidence_reference
        ):
            # Old checkbox covers reminders, not marketing or general announcements.
            reason = "no_general_consent"
        if reason is None and address in seen:
            reason = "duplicate_address"
        if reason is None:
            seen.add(address)
        decisions.append((
            person, kind, "suppressed" if reason else "eligible", reason
        ))
    return decisions
