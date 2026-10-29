"""Standing-approved monthly IST reminders using Saasyto's durable queue only.

No vendor-side campaign API is assumed. The same one-recipient Saasyto sender
used by explicitly approved campaigns submits each opted-in recipient; no
Pabbly transport is involved. New reminders are created only on the approved
IST calendar day, after separate deployment and organization approvals.

The deterministic campaign request key and unique monthly ReminderBatch guard
prevent duplicate monthly schedules. Actual dispatch rechecks consent, amount,
assignments and due date, and never replays an uncertain claim.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
    AdminUser,
    AuditEvent,
    CommunicationCampaign,
    MessageDispatch,
    OrganizationSettings,
    Promoter,
    PromoterAssignment,
    Prospect,
    ReminderBatch,
    ReminderIntent,
    SaasytoCampaignRecipient,
    SaasytoCampaignRun,
    SponsorshipRate,
)
from app.reminders import _build_preview
from app.security import as_utc, utc_now

MARKER = {
    "sponsor": "sas_auto_sponsor_v1",
    "promoter": "sas_auto_promoter_v1",
}
NAMESPACE = uuid.UUID("4d93ff1a-3ef3-4476-9747-221e38f60749")


def _request_id(organization_id: uuid.UUID, kind: str, month) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{organization_id}/{kind}/{month.isoformat()}")


def _kind(campaign: CommunicationCampaign) -> str | None:
    for kind, marker in MARKER.items():
        if campaign.provider_template_id == marker:
            return kind
    return None


def _money(paise: int) -> str:
    return f"₹{Decimal(paise) / 100:,.2f}"


def _due_sponsor(db: Session, org: uuid.UUID, sponsor: Prospect, now: datetime) -> int:
    today = ist_today(now)
    if (
        sponsor.organization_id != org
        or sponsor.archived_at is not None
        or sponsor.crm_stage != "active"
        or sponsor.start_month is None
        or sponsor.start_month > month_start(today)
    ):
        return 0
    rates = db.scalars(select(SponsorshipRate).where(
        SponsorshipRate.organization_id == org,
        SponsorshipRate.prospect_id == sponsor.id,
    )).all()
    credits = effective_credits(db, org, sponsor_id=sponsor.id, as_of=now)
    try:
        if evaluate_status(sponsor, rates, credits, today, now) == "inactive":
            return 0
        due, _, outstanding, paid = period_balance(
            sponsor, rates, credits, month_start(today), now,
        )
    except ValueError:
        return 0
    return outstanding if due > 0 and outstanding > 0 and not paid else 0


def live_monthly_message(
    db: Session, campaign: CommunicationCampaign,
    person: Prospect | Promoter, now: datetime, cfg,
) -> str | None:
    """Verify a generated monthly reminder and recompose its live amount.

    Nothing in a previously materialized snapshot is send authority.
    """
    kind = _kind(campaign)
    if kind is None:
        return None
    if not getattr(cfg, "saasyto_auto_reminders_enabled", False):
        return None
    org = campaign.organization_id
    settings = db.get(OrganizationSettings, org)
    if (
        settings is None
        or not settings.automation_enabled
        or settings.currency_code != "INR"
        or settings.timezone != "Asia/Kolkata"
    ):
        return None
    today = ist_today(now)
    month = month_start(today)
    day = settings.sponsor_reminder_day if kind == "sponsor" else settings.promoter_reminder_day
    if today.day != day:
        return None
    if campaign.request_id != _request_id(org, kind, month):
        return None
    if campaign.audience != ("prospects" if kind == "sponsor" else "promoters"):
        return None
    if campaign.segment != "unpaid" or campaign.category != "reminder":
        return None
    batch = db.scalars(select(ReminderBatch).where(
        ReminderBatch.organization_id == org,
        ReminderBatch.request_id == campaign.request_id,
        ReminderBatch.kind == kind,
        ReminderBatch.period_month == month,
        ReminderBatch.scheduled_on == today,
    )).one_or_none()
    if batch is None:
        return None
    recipient_id = person.id
    intent = db.scalars(select(ReminderIntent).where(
        ReminderIntent.organization_id == org,
        ReminderIntent.batch_id == batch.id,
        ReminderIntent.kind == kind,
        ReminderIntent.prospect_id == recipient_id if kind == "sponsor"
        else ReminderIntent.promoter_id == recipient_id,
        ReminderIntent.status == "prepared",
    )).one_or_none()
    if intent is None:
        return None
    # A historically imported Pabbly attempt must never be sent again.
    old_attempt = db.scalar(select(MessageDispatch.id).where(
        MessageDispatch.organization_id == org,
        MessageDispatch.reminder_intent_id == intent.id,
    ).limit(1))
    if old_attempt is not None:
        return None
    label = month.strftime("%B %Y")
    if kind == "sponsor":
        if not isinstance(person, Prospect):
            return None
        outstanding = _due_sponsor(db, org, person, now)
        if outstanding <= 0:
            return None
        body = (
            f"Salaam {person.full_name},\n"
            f"This is your Sponsor a Salah reminder for {label}. "
            f"Your current outstanding sponsorship is {_money(outstanding)}. "
            "Thank you for helping support the masjid."
        )
    else:
        if not isinstance(person, Promoter) or not person.is_active:
            return None
        if not getattr(cfg, "promoter_disclosure_approved", False):
            return None
        links = db.scalars(select(PromoterAssignment).where(
            PromoterAssignment.organization_id == org,
            PromoterAssignment.promoter_id == recipient_id,
            PromoterAssignment.ended_at.is_(None),
        )).all()
        if not links or len(links) > 20:
            return None
        details = []
        total = 0
        for link in links:
            sponsor = db.scalars(select(Prospect).where(
                Prospect.organization_id == org,
                Prospect.id == link.prospect_id,
            )).one_or_none()
            if sponsor is None:
                continue
            balance = _due_sponsor(db, org, sponsor, now)
            if balance > 0:
                details.append((sponsor.full_name, str(sponsor.id), balance))
                total += balance
        if not details:
            return None
        details.sort(key=lambda x: (x[0], x[1]))
        summary = "; ".join(f"{name}: {_money(balance)}" for name, _, balance in details)
        if len(summary) > 900:
            return None
        body = (
            f"Salaam {person.full_name},\n"
            f"Your Sponsor a Salah follow-up for {label} includes "
            f"{len(details)} unpaid sponsorship(s), totaling {_money(total)}.\n"
            f"{summary}\nThank you for following up."
        )
    return body if len(body) <= 1200 else None


def prepare_due_saasyto_reminders(db: Session, cfg, now: datetime | None = None) -> int:
    """Create the unique approved run on its IST day, without sending messages.

    Called by the private Saasyto worker. This is a standing organization
    automation approval, not permission to send ordinary marketing campaigns.
    """
    if not (
        getattr(cfg, "saasyto_auto_reminders_enabled", False)
        and getattr(cfg, "saasyto_worker_enabled", False)
        and getattr(cfg, "saasyto_delivery_enabled", False)
        and getattr(cfg, "saasyto_sender_approved", False)
    ):
        return 0
    now = now or utc_now()
    cutoff = getattr(cfg, "saasyto_enable_after", None)
    if cutoff is None or now < as_utc(cutoff):
        return 0
    from app.saasyto_campaigns import MAX_APPROVAL_RECIPIENTS, _phone_digest

    today = ist_today(now)
    month = month_start(today)
    count = 0
    org_ids = list(db.scalars(select(OrganizationSettings.organization_id).where(
        OrganizationSettings.automation_enabled.is_(True),
        OrganizationSettings.currency_code == "INR",
        OrganizationSettings.timezone == "Asia/Kolkata",
    ).order_by(OrganizationSettings.organization_id)))
    for org_id in org_ids:
        settings = db.scalars(select(OrganizationSettings).where(
            OrganizationSettings.organization_id == org_id,
        ).with_for_update()).one_or_none()
        if settings is None or not settings.automation_enabled:
            db.rollback()
            continue
        admin = db.scalars(select(AdminUser).where(
            AdminUser.organization_id == org_id,
            AdminUser.is_active.is_(True),
        ).order_by(AdminUser.id).limit(1)).first()
        if admin is None:
            db.rollback()
            continue
        for kind in ("sponsor", "promoter"):
            day = (
                settings.sponsor_reminder_day if kind == "sponsor"
                else settings.promoter_reminder_day
            )
            if day != today.day:
                continue
            if kind == "promoter" and not getattr(cfg, "promoter_disclosure_approved", False):
                continue
            prior_batch = db.scalar(select(ReminderBatch.id).where(
                ReminderBatch.organization_id == org_id,
                ReminderBatch.kind == kind,
                ReminderBatch.period_month == month,
            ).limit(1))
            if prior_batch is not None:
                continue
            preview = _build_preview(db, admin, settings, kind, now)
            if preview.eligible_recipients > MAX_APPROVAL_RECIPIENTS:
                db.rollback()
                continue
            request_id = _request_id(org_id, kind, month)
            batch = ReminderBatch(
                organization_id=org_id, request_id=request_id, kind=kind,
                period_month=month, scheduled_on=today,
                recipient_count=preview.eligible_recipients,
                created_by_admin_id=admin.id,
            )
            db.add(batch)
            db.flush()
            for recipient in preview.recipients:
                db.add(ReminderIntent(
                    organization_id=org_id, batch_id=batch.id, kind=kind,
                    prospect_id=recipient.recipient_id if kind == "sponsor" else None,
                    promoter_id=recipient.recipient_id if kind == "promoter" else None,
                    period_month=month, scheduled_on=today,
                    sponsor_count=recipient.sponsor_count,
                    outstanding_paise=recipient.outstanding_paise,
                    sponsor_snapshot=[
                        {"prospect_id": str(p.prospect_id),
                         "outstanding_paise": p.outstanding_paise}
                        for p in recipient.unpaid_sponsors
                    ],
                    status="prepared",
                ))
            if preview.eligible_recipients:
                campaign = CommunicationCampaign(
                    organization_id=org_id, request_id=request_id,
                    title=f"{kind.capitalize()} reminders — {month.strftime('%B %Y')}",
                    channel="whatsapp",
                    audience="prospects" if kind == "sponsor" else "promoters",
                    segment="unpaid", category="reminder",
                    body="Salaam {{name}}, your Sponsor a Salah reminder for {{month}}.",
                    provider_template_id=MARKER[kind],
                    status="scheduled", planned_for=now,
                    eligible_snapshot=preview.eligible_recipients,
                    candidate_snapshot=preview.eligible_recipients,
                    created_by_admin_id=admin.id,
                )
                db.add(campaign)
                db.flush()
                run = SaasytoCampaignRun(
                    organization_id=org_id, campaign_id=campaign.id,
                    approved_by_admin_id=admin.id, approved_at=now,
                    due_at=now, status="approved",
                    eligible_count=preview.eligible_recipients, suppressed_count=0,
                )
                db.add(run)
                db.flush()
                model = Prospect if kind == "sponsor" else Promoter
                for recipient in preview.recipients:
                    person = db.get(model, recipient.recipient_id)
                    db.add(SaasytoCampaignRecipient(
                        organization_id=org_id, run_id=run.id,
                        recipient_kind="prospect" if kind == "sponsor" else "promoter",
                        recipient_id=person.id,
                        approved_phone_digest=_phone_digest(
                            cfg, contact_address(person, "whatsapp")
                        ),
                        status="queued",
                    ))
            db.add(AuditEvent(
                organization_id=org_id, actor_admin_id=admin.id,
                action="saasyto.monthly_reminders_queued",
                entity_type="reminder_batch", entity_id=str(batch.id),
                after_data={
                    "kind": kind, "month": month.isoformat(),
                    "recipients": preview.eligible_recipients,
                    "standing_automation_approval": True,
                    "sent": False,
                },
            ))
            try:
                db.commit()
                count += 1
            except IntegrityError:
                # Concurrent workers may race to schedule the same month.
                # One unique batch/campaign wins; never retry on collision.
                db.rollback()
        db.rollback()
    return count
