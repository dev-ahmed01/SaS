"""Saasyto-only, default-off collection acknowledgement queue.

Each payment outbox intent maps deterministically to one Saasyto campaign and
recipient claim. No Pabbly client, no historic backlog release and no
automatic retry of uncertain attempts. A newly recorded reversal or opt-out
will suppress sending when the queue is claimed.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.communication_consent import contact_address, evaluate_recipients
from app.models import (
    AdminUser,
    AuditEvent,
    CommunicationCampaign,
    ManualCollection,
    ManualCollectionReversal,
    MessageDispatch,
    MessageOutbox,
    OrganizationSettings,
    Prospect,
    SaasytoCampaignRecipient,
    SaasytoCampaignRun,
)
from app.security import as_utc, utc_now

ACK_MARKER = "sas_auto_collection_ack_v1"
ACK_NAMESPACE = uuid.UUID("854e7ed7-e31b-4755-998c-8bc119afc3a2")
MAX_RECEIPTS_PER_TICK = 20


def _key(outbox_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(ACK_NAMESPACE, str(outbox_id))


def live_receipt_message(
    db: Session, campaign: CommunicationCampaign, sponsor: Prospect,
    now: datetime, cfg,
) -> str | None:
    if not getattr(cfg, "saasyto_receipt_confirmations_enabled", False):
        return None
    if campaign.provider_template_id != ACK_MARKER or campaign.category != "thank_you":
        return None
    org = campaign.organization_id
    org_settings = db.get(OrganizationSettings, org)
    if not org_settings or not org_settings.automation_enabled:
        return None
    if sponsor.organization_id != org or sponsor.archived_at is not None:
        return None
    intents = db.scalars(select(MessageOutbox).where(
        MessageOutbox.organization_id == org,
        MessageOutbox.prospect_id == sponsor.id,
        MessageOutbox.status == "awaiting_integration",
    )).all()
    matched = next(
        (outbox for outbox in intents
         if _key(outbox.id) == campaign.request_id), None,
    )
    if matched is None:
        return None
    cutoff = getattr(cfg, "saasyto_enable_after", None)
    if cutoff is None or as_utc(matched.created_at) < as_utc(cutoff):
        return None
    if db.scalar(select(MessageDispatch.id).where(
        MessageDispatch.organization_id == org,
        MessageDispatch.outbox_id == matched.id,
    ).limit(1)) is not None:
        return None
    collection = db.scalars(select(ManualCollection).where(
        ManualCollection.organization_id == org,
        ManualCollection.id == matched.collection_id,
        ManualCollection.prospect_id == sponsor.id,
    )).one_or_none()
    if collection is None:
        return None
    reversed_id = db.scalar(select(ManualCollectionReversal.id).where(
        ManualCollectionReversal.organization_id == org,
        ManualCollectionReversal.collection_id == collection.id,
    ).limit(1))
    if reversed_id is not None:
        return None
    month = collection.period_month.strftime("%B %Y")
    amount = f"₹{collection.amount_paise / 100:,.2f}"
    return (
        f"Salaam {sponsor.full_name},\n"
        f"Thank you for your Sponsor a Salah contribution of {amount} "
        f"recorded for {month}. May Allah reward your support."
    )


def queue_saasyto_receipts(db: Session, cfg, now: datetime | None = None) -> int:
    if not (
        getattr(cfg, "saasyto_receipt_confirmations_enabled", False)
        and getattr(cfg, "saasyto_worker_enabled", False)
        and getattr(cfg, "saasyto_delivery_enabled", False)
        and getattr(cfg, "saasyto_sender_approved", False)
    ):
        return 0
    now = now or utc_now()
    cutoff = getattr(cfg, "saasyto_enable_after", None)
    if cutoff is None or now < as_utc(cutoff):
        return 0
    from app.saasyto_campaigns import _phone_digest

    candidates = db.scalars(select(MessageOutbox).where(
        MessageOutbox.status == "awaiting_integration",
        MessageOutbox.created_at >= cutoff,
        MessageOutbox.event_type.in_((
            "collection_recorded", "collection_confirmation_resend",
        )),
    ).order_by(MessageOutbox.created_at, MessageOutbox.id).limit(
        MAX_RECEIPTS_PER_TICK,
    ).with_for_update(skip_locked=True)).all()
    queued = 0
    for outbox in candidates:
        settings = db.get(OrganizationSettings, outbox.organization_id)
        if not settings or not settings.automation_enabled:
            continue
        if db.scalar(select(MessageDispatch.id).where(
            MessageDispatch.organization_id == outbox.organization_id,
            MessageDispatch.outbox_id == outbox.id,
        ).limit(1)) is not None:
            continue
        if db.scalar(select(CommunicationCampaign.id).where(
            CommunicationCampaign.organization_id == outbox.organization_id,
            CommunicationCampaign.request_id == _key(outbox.id),
        ).limit(1)) is not None:
            continue
        sponsor = db.scalars(select(Prospect).where(
            Prospect.organization_id == outbox.organization_id,
            Prospect.id == outbox.prospect_id,
        )).one_or_none()
        collection = db.scalars(select(ManualCollection).where(
            ManualCollection.organization_id == outbox.organization_id,
            ManualCollection.id == outbox.collection_id,
        )).one_or_none()
        if sponsor is None or collection is None or sponsor.archived_at is not None:
            continue
        if db.scalar(select(ManualCollectionReversal.id).where(
            ManualCollectionReversal.organization_id == outbox.organization_id,
            ManualCollectionReversal.collection_id == collection.id,
        ).limit(1)) is not None:
            continue
        eligible = evaluate_recipients(
            db, outbox.organization_id, [sponsor], "whatsapp", "thank_you", now=now,
        )
        if not eligible or eligible[0][2] != "eligible":
            continue
        admin = db.scalars(select(AdminUser).where(
            AdminUser.organization_id == outbox.organization_id,
            AdminUser.is_active.is_(True),
        ).order_by(AdminUser.id).limit(1)).first()
        if admin is None:
            continue
        campaign = CommunicationCampaign(
            organization_id=outbox.organization_id,
            request_id=_key(outbox.id),
            title=f"Collection acknowledgement — {collection.period_month:%b %Y}",
            channel="whatsapp", audience="prospects", segment="active",
            category="thank_you",
            body="Salaam {{name}}, thank you for your Sponsor a Salah contribution.",
            provider_template_id=ACK_MARKER, status="scheduled", planned_for=now,
            created_by_admin_id=admin.id,
            eligible_snapshot=1, candidate_snapshot=1,
        )
        db.add(campaign)
        db.flush()
        run = SaasytoCampaignRun(
            organization_id=outbox.organization_id, campaign_id=campaign.id,
            approved_at=now, approved_by_admin_id=admin.id,
            due_at=now, status="approved", eligible_count=1,
            suppressed_count=0,
        )
        db.add(run)
        db.flush()
        db.add(SaasytoCampaignRecipient(
            organization_id=outbox.organization_id, run_id=run.id,
            recipient_kind="prospect", recipient_id=sponsor.id,
            approved_phone_digest=_phone_digest(
                cfg, contact_address(sponsor, "whatsapp")
            ),
            status="queued",
        ))
        db.add(AuditEvent(
            organization_id=outbox.organization_id, actor_admin_id=admin.id,
            action="saasyto.collection_acknowledgement_queued",
            entity_type="message_outbox", entity_id=str(outbox.id),
            after_data={"queued": True, "sent": False},
        ))
        try:
            db.commit()
            queued += 1
        except IntegrityError:
            db.rollback()
    return queued
