"""Explicit synthetic financial examples for a disposable local-demo database.

NEVER run this on a database containing real Foundation records. The guard checks
that *every* existing prospect, promoter, collection, and payout is demo-only.
These are not real receipts or disbursements. Messaging is never enabled.
"""
import argparse
import hashlib
import hmac
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounting import evaluate_status, ist_today, month_start
from app.config import get_settings
from app.db import get_engine
from app.models import (
    AdminUser,
    AuditEvent,
    ManualCollection,
    ManualCollectionReversal,
    MessageOutbox,
    PayoutPayment,
    PayoutPlan,
    PayoutPlanTerm,
    Promoter,
    Prospect,
    SponsorshipRate,
    VerifiedCredit,
)
from app.seed_local_crm import _fixed_uuid

COLLECTIONS = 20
PAYOUT_PLANS = 12
PAYOUT_PAYMENTS = 5


def assert_disposable_demo(database: Session, org_id: uuid.UUID) -> None:
    """Fail closed if any existing contacts or financial data aren't synthetic."""
    if database.scalar(select(func.count(Prospect.id)).where(
        Prospect.organization_id == org_id, ~Prospect.full_name.startswith("Demo "),
    )):
        raise ValueError("Non-demo prospects exist. Use a disposable synthetic-only database.")
    if database.scalar(select(func.count(Promoter.id)).where(
        Promoter.organization_id == org_id, ~Promoter.full_name.startswith("Demo "),
    )):
        raise ValueError("Non-demo promoters exist. Use a disposable synthetic-only database.")
    if database.scalar(select(func.count(PayoutPlan.id)).where(
        PayoutPlan.organization_id == org_id, ~PayoutPlan.payee_name.startswith("Demo "),
    )):
        raise ValueError("Non-demo payout plans exist. Use a disposable synthetic-only database.")
    if database.scalar(select(func.count(ManualCollection.id))
                       .join(Prospect, Prospect.id == ManualCollection.prospect_id)
                       .where(ManualCollection.organization_id == org_id,
                              ~Prospect.full_name.startswith("Demo "))):
        raise ValueError("Non-demo receipts exist. Use a disposable synthetic-only database.")
    # External or bank-reconciled credits are real accounting evidence, never demo.
    if database.scalar(select(func.count(VerifiedCredit.id)).where(
        VerifiedCredit.organization_id == org_id,
        VerifiedCredit.source_type != "manual_attested",
    )):
        raise ValueError("External verified credits exist. No finance examples allowed.")


def seed_finance_examples(
    database: Session, organization_id: uuid.UUID, admin_id: uuid.UUID,
    secret: str,
) -> dict[str, int]:
    """Insert deterministic demo financial examples; transaction managed by caller."""
    if len(secret) < 32:
        raise ValueError("Demo receipt secret must be at least 32 characters")
    assert_disposable_demo(database, organization_id)
    sponsors = list(database.scalars(select(Prospect).where(
        Prospect.organization_id == organization_id,
        Prospect.full_name.startswith("Demo "),
        Prospect.archived_at.is_(None),
    ).order_by(Prospect.registration_request_id)).all())
    if len(sponsors) < 100:
        raise ValueError("Seed the 100 synthetic CRM prospects before demo finance")
    today = ist_today()
    month = month_start(today)
    now = datetime.now(UTC)
    counts = {"collections": 0, "collection_reversals": 0, "payout_plans": 0,
              "payout_payments": 0}
    for i, sponsor in enumerate(sponsors[:COLLECTIONS], 1):
        request = _fixed_uuid(organization_id, "demo-receipt", i)
        if database.scalar(select(ManualCollection.id).where(
            ManualCollection.organization_id == organization_id,
            ManualCollection.request_id == request,
        )):
            continue
        reference = f"DEMO-COLL-{i:04d}"
        digest = hmac.new(secret.encode(), b"sas:manual-receipt-ref:v2:"+
                          reference.encode(), hashlib.sha256).hexdigest()
        amount = sponsor.monthly_contribution_paise
        credit = VerifiedCredit(
            organization_id=organization_id, prospect_id=sponsor.id,
            period_month=month, amount_paise=amount,
            source_type="manual_attested", source_key="manual:"+digest,
            verified_at=now,
        )
        database.add(credit)
        database.flush()
        method = ("upi", "bank_transfer", "cash")[i % 3]
        receipt = ManualCollection(
            organization_id=organization_id, prospect_id=sponsor.id,
            verified_credit_id=credit.id, request_id=request,
            request_payload_hash=hashlib.sha256(reference.encode()).hexdigest(),
            reference_digest=digest, reference_mask="****"+reference[-4:],
            received_on=today, period_month=month, payment_method=method,
            amount_paise=amount, recorded_by_admin_id=admin_id,
        )
        database.add(receipt)
        database.flush()
        database.add(MessageOutbox(
            organization_id=organization_id, prospect_id=sponsor.id,
            collection_id=receipt.id, event_type="collection_recorded",
            status="suppressed", suppress_reason="consent_missing",
        ))
        if i in (4, 11):
            database.add(ManualCollectionReversal(
                organization_id=organization_id, collection_id=receipt.id,
                request_id=_fixed_uuid(organization_id, "demo-reversal", i),
                reason_code="duplicate_entry", actor_admin_id=admin_id,
            ))
            counts["collection_reversals"] += 1
        else:
            rates = list(database.scalars(select(SponsorshipRate).where(
                SponsorshipRate.prospect_id == sponsor.id,
                SponsorshipRate.organization_id == organization_id,
            )).all())
            sponsor.last_verified_payment_at = now
            sponsor.lifecycle_status = evaluate_status(
                sponsor, rates, [credit], today, now,
            )
            sponsor.status_updated_at = now
            sponsor.version += 1
        counts["collections"] += 1

    categories = (
        "Facility support", "Electricity", "Community program", "Staff services",
        "Utilities", "Maintenance",
    )
    for i in range(1, PAYOUT_PLANS+1):
        request = _fixed_uuid(organization_id, "demo-payout-plan", i)
        plan = database.scalar(select(PayoutPlan).where(
            PayoutPlan.organization_id == organization_id,
            PayoutPlan.create_request_id == request,
        ))
        if plan is None:
            recurring = i <= 8
            plan = PayoutPlan(
                organization_id=organization_id, create_request_id=request,
                create_hash=hashlib.sha256(str(request).encode()).hexdigest(),
                payee_name=f"Demo Vendor {i:02d}",
                purpose=categories[(i-1) % len(categories)],
                notes="SYNTHETIC DEMO ONLY; not an actual commitment",
                cadence="recurring" if recurring else "one_time",
                start_month=month, scheduled_on=None if recurring else today,
                amount_paise=(i+2)*100000,
                created_by_admin_id=admin_id,
            )
            database.add(plan)
            database.flush()
            database.add(PayoutPlanTerm(
                organization_id=organization_id, plan_id=plan.id,
                effective_month=month, status="active",
                recorded_by_admin_id=admin_id,
            ))
            counts["payout_plans"] += 1
        if i > PAYOUT_PAYMENTS:
            continue
        payment_request = _fixed_uuid(organization_id, "demo-payout-payment", i)
        if database.scalar(select(PayoutPayment.id).where(
            PayoutPayment.organization_id == organization_id,
            PayoutPayment.request_id == payment_request,
        )):
            continue
        ref = f"DEMO-OUT-{i:04d}"
        database.add(PayoutPayment(
            organization_id=organization_id, plan_id=plan.id,
            request_id=payment_request,
            request_payload_hash=hashlib.sha256(ref.encode()).hexdigest(),
            period_month=month, paid_on=today,
            amount_paise=plan.amount_paise,
            payment_method=("upi","bank_transfer","cash")[i%3],
            reference_digest=hashlib.sha256(ref.encode()).hexdigest(),
            reference_mask="****"+ref[-4:], recorded_by_admin_id=admin_id,
        ))
        counts["payout_payments"] += 1

    if any(counts.values()):
        database.add(AuditEvent(
            organization_id=organization_id, actor_admin_id=admin_id,
            action="local_demo.finance_examples_seeded", entity_type="organization",
            entity_id=str(organization_id), before_data=None,
            after_data={"synthetic":True,"actual_funds":False,"counts":counts},
        ))
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic-only local finance examples")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-synthetic-only", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if (
        settings.app_env != "development"
        or not settings.local_demo_login_enabled
        or settings.messaging_delivery_enabled
    ):
        raise SystemExit("Refusing: must use local demo database with all messaging disabled")
    if not settings.auth_secret or len(settings.auth_secret)<32:
        raise SystemExit("Unique local AUTH_SECRET of 32+ characters required")
    with Session(get_engine()) as database:
        admins = list(database.scalars(select(AdminUser)).all())
        if len(admins)!=1 or admins[0].email!="admin@local.sas.example" or not admins[0].is_active:
            raise SystemExit("Refusing: local-only Admin required")
        admin=admins[0]
        try:
            assert_disposable_demo(database, admin.organization_id)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print("Synthetic financial records only; NO genuine receipts or transfers.")
        if not args.apply:
            print("Dry run. Use --apply --confirm-synthetic-only to create examples.")
            return
        if not args.confirm_synthetic_only:
            raise SystemExit("Refusing without explicit synthetic-only confirmation")
        try:
            created=seed_finance_examples(database, admin.organization_id, admin.id,
                                          settings.auth_secret)
            database.commit()
        except ValueError as exc:
            database.rollback()
            raise SystemExit(str(exc)) from exc
        print("Created:",created)
        print("All examples are synthetic, in a disposable demo database only.")
        print("No bank transfer or message delivery was attempted.")


if __name__=="__main__":
    main()
