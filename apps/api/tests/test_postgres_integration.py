"""Production-dialect smoke tests, run only after migrations on the CI PostgreSQL service."""

import os
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AdminUser,
    AuditEvent,
    ManualCollection,
    ManualCollectionReversal,
    Organization,
    OrganizationSettings,
    PayoutPayment,
    PayoutPlan,
    PayoutPlanTerm,
    Promoter,
    PromoterAssignment,
    Prospect,
    ProspectUpiIdentifier,
    SponsorshipRate,
    VerifiedCredit,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql+psycopg://"),
    reason="Requires explicit PostgreSQL CI database",
)


def test_postgres_org_settings_admin_and_audit() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    uid = uuid.uuid4().hex
    with Session(engine) as session:
        org = Organization(name=f"Emlen test organization {uid}")
        session.add(org)
        session.flush()
        settings = OrganizationSettings(
            organization_id=org.id,
            currency_code="INR",
            timezone="Asia/Kolkata",
            default_contribution_paise=25000,
            sponsor_reminder_day=5,
            promoter_reminder_day=20,
            inactivity_months=2,
            automation_enabled=False,
        )
        admin = AdminUser(
            organization_id=org.id,
            email=f"{uid}@example.invalid",
            password_hash="fixture-only-not-a-real-password",
        )
        session.add_all([settings, admin])
        session.flush()
        session.add(
            AuditEvent(
                organization_id=org.id,
                actor_admin_id=admin.id,
                action="settings.initialized",
                entity_type="organization_settings",
                entity_id=str(org.id),
                before_data=None,
                after_data={"currency_code": "INR"},
            )
        )
        session.commit()
        row = session.scalars(
            select(OrganizationSettings).where(OrganizationSettings.organization_id == org.id)
        ).one()
        assert row.currency_code == "INR"
        assert row.default_contribution_paise == 25000
        assert session.scalars(
            select(AuditEvent).where(AuditEvent.organization_id == org.id)
        ).one().action == "settings.initialized"
    engine.dispose()


def test_postgres_rejects_invalid_reminder_day() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with Session(engine) as session:
        org = Organization(name=f"Emlen invalid-settings test {uuid.uuid4()}")
        session.add(org)
        session.flush()
        session.add(
            OrganizationSettings(
                organization_id=org.id,
                currency_code="INR",
                timezone="Asia/Kolkata",
                default_contribution_paise=25000,
                sponsor_reminder_day=32,
                promoter_reminder_day=20,
                inactivity_months=2,
                automation_enabled=False,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
    engine.dispose()


def test_postgres_prospect_upi_enforces_same_organization() -> None:
    """A UPI identifier cannot point across organization boundaries at database level."""
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with Session(engine) as session:
        org1 = Organization(name="Prospect integrity A")
        org2 = Organization(name="Prospect integrity B")
        session.add_all([org1, org2])
        session.flush()
        candidate = Prospect(
            organization_id=org1.id, full_name="Synthetic Candidate",
            mobile_number="+919876543210", area_city="Bengaluru",
            monthly_contribution_paise=25000, whatsapp_opt_in=False,
            lifecycle_status="new", version=1,
        )
        session.add(candidate)
        session.commit()
        session.refresh(candidate)
        wrong_org = ProspectUpiIdentifier(
            organization_id=org2.id, prospect_id=candidate.id,
            digest="a" * 64, masked_vpa="s***@upi", is_verified=False,
        )
        session.add(wrong_org)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
    engine.dispose()


def test_postgres_enforces_prospect_status_and_amount_constraints() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with Session(engine) as session:
        org = Organization(name="Prospect status validation")
        session.add(org)
        session.flush()
        session.add(Prospect(
            organization_id=org.id, full_name="Synthetic Candidate",
            mobile_number="+919876543210", area_city="Bengaluru",
            monthly_contribution_paise=0, whatsapp_opt_in=False,
            lifecycle_status="unknown", version=1,
        ))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
    engine.dispose()


def test_postgres_rejects_cross_organization_promoter_assignments() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with Session(engine) as db:
        org_a = Organization(name="Promoter FK test A")
        org_b = Organization(name="Promoter FK test B")
        db.add_all([org_a, org_b])
        db.flush()
        promoter = Promoter(
            organization_id=org_a.id, full_name="Synthetic Promoter",
            mobile_number="+919151515151", area_city="Bengaluru",
            whatsapp_opt_in=False, is_active=True, version=1,
        )
        prospect = Prospect(
            organization_id=org_b.id, full_name="Synthetic Sponsor",
            mobile_number="+919414141414", area_city="Bengaluru",
            monthly_contribution_paise=50000, whatsapp_opt_in=False,
            lifecycle_status="new", version=1,
        )
        db.add_all([promoter, prospect])
        db.flush()
        db.add(PromoterAssignment(
            organization_id=org_a.id, promoter_id=promoter.id,
            prospect_id=prospect.id,
        ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    engine.dispose()


def test_postgres_unique_current_sponsor_assignment_with_historical_rows() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with Session(engine) as db:
        org = Organization(name="Unique primary promoter test")
        db.add(org)
        db.flush()
        first = Promoter(
            organization_id=org.id, full_name="First Coordinator",
            mobile_number="+919333300001", area_city="Bengaluru",
            whatsapp_opt_in=False, is_active=True, version=1,
        )
        second = Promoter(
            organization_id=org.id, full_name="Second Coordinator",
            mobile_number="+919333300002", area_city="Bengaluru",
            whatsapp_opt_in=False, is_active=True, version=1,
        )
        prospect = Prospect(
            organization_id=org.id, full_name="Sponsored Person",
            mobile_number="+919333300003", area_city="Bengaluru",
            monthly_contribution_paise=50000, whatsapp_opt_in=False,
            lifecycle_status="new", version=1,
        )
        db.add_all([first, second, prospect])
        db.flush()
        db.add(PromoterAssignment(
            organization_id=org.id, promoter_id=first.id,
            prospect_id=prospect.id,
        ))
        db.flush()
        db.add(PromoterAssignment(
            organization_id=org.id, promoter_id=second.id,
            prospect_id=prospect.id,
        ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    engine.dispose()


def test_postgres_effective_rate_requires_same_organization() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with Session(engine) as db:
        home = Organization(name="Finance rate constraint A")
        foreign = Organization(name="Finance rate constraint B")
        db.add_all([home, foreign])
        db.flush()
        sponsor = Prospect(
            organization_id=home.id, full_name="Synthetic Rate Sponsor",
            mobile_number="+919311100100", area_city="Bengaluru",
            monthly_contribution_paise=50000, start_month=date(2026, 10, 1),
            whatsapp_opt_in=False, lifecycle_status="new", version=1,
        )
        db.add(sponsor)
        db.flush()
        db.add(SponsorshipRate(
            organization_id=foreign.id, prospect_id=sponsor.id,
            effective_month=date(2026, 10, 1), amount_paise=50000,
        ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    engine.dispose()


def test_postgres_rejects_duplicate_verified_credit_evidence() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with Session(engine) as db:
        org = Organization(name="Verified evidence uniqueness")
        db.add(org)
        db.flush()
        sponsor = Prospect(
            organization_id=org.id, full_name="Synthetic Credit Sponsor",
            mobile_number="+919311100101", area_city="Bengaluru",
            monthly_contribution_paise=50000, start_month=date(2026, 10, 1),
            whatsapp_opt_in=False, lifecycle_status="new", version=1,
        )
        db.add(sponsor)
        db.flush()
        for idx in range(2):
            db.add(VerifiedCredit(
                organization_id=org.id, prospect_id=sponsor.id,
                period_month=date(2026, 10, 1), amount_paise=25000,
                source_type="bank_reconciled", source_key="synthetic-bank-ref-dup",
                verified_at=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
            ))
            if idx == 0:
                db.flush()
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    engine.dispose()


def test_postgres_manual_collection_cannot_cross_tenant() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with Session(engine) as db:
        first = Organization(name="Manual collection org A")
        second = Organization(name="Manual collection org B")
        db.add_all([first, second])
        db.flush()
        sponsor = Prospect(
            organization_id=first.id, full_name="Synthetic Manual Sponsor",
            mobile_number="+919311100103", area_city="Bengaluru",
            monthly_contribution_paise=50000, start_month=date(2026, 10, 1),
            whatsapp_opt_in=True, lifecycle_status="new", version=1,
        )
        db.add(sponsor)
        db.flush()
        credit = VerifiedCredit(
            organization_id=first.id, prospect_id=sponsor.id,
            period_month=date(2026, 10, 1), amount_paise=50000,
            source_type="manual_attested", source_key="manual:cross-org-fixture",
            verified_at=datetime(2026, 10, 13, 10, 0, tzinfo=UTC),
        )
        db.add(credit)
        db.flush()
        db.add(ManualCollection(
            organization_id=second.id, prospect_id=sponsor.id,
            verified_credit_id=credit.id, request_id=uuid.uuid4(),
            request_payload_hash="a" * 64, reference_digest="b" * 64,
            reference_mask="****1003", received_on=date(2026, 10, 13),
            period_month=date(2026, 10, 1), payment_method="upi",
            amount_paise=50000,
        ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    engine.dispose()


def _insert_manual_receipt_for_reversal(db, org: Organization) -> ManualCollection:
    person = Prospect(
        organization_id=org.id, full_name="Synthetic Correction Sponsor",
        mobile_number="+919311101990", area_city="Bengaluru",
        monthly_contribution_paise=50000, start_month=date(2026, 10, 1),
        whatsapp_opt_in=False, lifecycle_status="new", version=1,
    )
    db.add(person)
    db.flush()
    credit = VerifiedCredit(
        organization_id=org.id, prospect_id=person.id,
        period_month=date(2026, 10, 1), amount_paise=50000,
        source_type="manual_attested", source_key="manual:correction-pg-sample",
        verified_at=datetime(2026, 10, 13, 10, 0, tzinfo=UTC),
    )
    db.add(credit)
    db.flush()
    receipt = ManualCollection(
        organization_id=org.id, prospect_id=person.id,
        verified_credit_id=credit.id, request_id=uuid.uuid4(),
        request_payload_hash="a" * 64, reference_digest="b" * 64,
        reference_mask="****1990", received_on=date(2026, 10, 13),
        period_month=date(2026, 10, 1), payment_method="upi",
        amount_paise=50000,
    )
    db.add(receipt)
    db.flush()
    return receipt


def test_postgres_prevents_two_reversals_for_same_collection() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with Session(engine) as db:
        org = Organization(name="Reversal uniqueness source")
        db.add(org)
        db.flush()
        receipt = _insert_manual_receipt_for_reversal(db, org)
        db.add(ManualCollectionReversal(
            organization_id=org.id, collection_id=receipt.id,
            request_id=uuid.uuid4(), reason_code="duplicate_entry",
        ))
        db.flush()
        db.add(ManualCollectionReversal(
            organization_id=org.id, collection_id=receipt.id,
            request_id=uuid.uuid4(), reason_code="wrong_amount",
        ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    engine.dispose()


def test_postgres_reversal_cannot_reference_foreign_tenant_collection() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with Session(engine) as db:
        first = Organization(name="Reversal same-org original")
        second = Organization(name="Reversal cross-org attacker")
        db.add_all([first, second])
        db.flush()
        receipt = _insert_manual_receipt_for_reversal(db, first)
        db.add(ManualCollectionReversal(
            organization_id=second.id, collection_id=receipt.id,
            request_id=uuid.uuid4(), reason_code="wrong_sponsor",
        ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    engine.dispose()


def test_postgres_rejects_unknown_reversal_reason_code() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with Session(engine) as db:
        org = Organization(name="Reversal check constraint")
        db.add(org)
        db.flush()
        receipt = _insert_manual_receipt_for_reversal(db, org)
        db.add(ManualCollectionReversal(
            organization_id=org.id, collection_id=receipt.id,
            request_id=uuid.uuid4(), reason_code="erase_all_records",
        ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    engine.dispose()


def _pg_payout_plan(db: Session, org: Organization) -> PayoutPlan:
    plan = PayoutPlan(
        organization_id=org.id,
        create_request_id=uuid.uuid4(), create_hash="a" * 64,
        payee_name="Synthetic Payout Payee",
        purpose="Safety benchmark fixture", cadence="recurring",
        start_month=date(2026, 10, 1), amount_paise=50000,
    )
    db.add(plan)
    db.flush()
    db.add(PayoutPlanTerm(
        organization_id=org.id, plan_id=plan.id,
        effective_month=date(2026, 10, 1), status="active",
    ))
    db.flush()
    return plan


def test_postgres_payout_term_cannot_reference_different_organization() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with Session(engine) as db:
        source = Organization(name="Payout tenant source")
        foreign = Organization(name="Payout tenant foreign")
        db.add_all([source, foreign])
        db.flush()
        plan = _pg_payout_plan(db, source)
        db.add(PayoutPlanTerm(
            organization_id=foreign.id, plan_id=plan.id,
            effective_month=date(2026, 11, 1), status="active",
        ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    engine.dispose()


def test_postgres_payout_payment_cannot_reference_different_organization() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with Session(engine) as db:
        source = Organization(name="Payout receipt tenant source")
        foreign = Organization(name="Payout receipt tenant foreign")
        db.add_all([source, foreign])
        db.flush()
        plan = _pg_payout_plan(db, source)
        db.add(PayoutPayment(
            organization_id=foreign.id, plan_id=plan.id,
            request_id=uuid.uuid4(), request_payload_hash="a" * 64,
            period_month=date(2026, 10, 1), paid_on=date(2026, 10, 13),
            amount_paise=50000, payment_method="upi",
            reference_digest="a" * 64, reference_mask="****1000",
        ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    engine.dispose()


def test_postgres_blocks_double_outgoing_payment_for_same_month() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with Session(engine) as db:
        org = Organization(name="Payout evidence idempotency")
        db.add(org)
        db.flush()
        plan = _pg_payout_plan(db, org)
        for index in range(2):
            db.add(PayoutPayment(
                organization_id=org.id, plan_id=plan.id,
                request_id=uuid.uuid4(), request_payload_hash="a" * 64,
                period_month=date(2026, 10, 1), paid_on=date(2026, 10, 13),
                amount_paise=50000, payment_method="bank_transfer",
                reference_digest=("a" if index == 0 else "b") * 64,
                reference_mask="****1001",
            ))
            if index == 0:
                db.flush()
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    engine.dispose()


def test_postgres_rejects_negative_or_zero_payout_obligations() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    with Session(engine) as db:
        org = Organization(name="Payout positive amount constraint")
        db.add(org)
        db.flush()
        db.add(PayoutPlan(
            organization_id=org.id, create_request_id=uuid.uuid4(),
            create_hash="a" * 64, payee_name="Synthetic Payee",
            purpose="Positive amount policy", cadence="one_time",
            start_month=date(2026, 10, 1), scheduled_on=date(2026, 10, 13),
            amount_paise=0,
        ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    engine.dispose()
