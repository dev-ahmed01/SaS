"""Only marked synthetic local-demo records are eligible for removal."""
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.bootstrap_admin import provision_admin
from app.cleanup_local_seed import cleanup_synthetic_crm
from app.models import (
    AdminUser,
    AuditEvent,
    Base,
    CommunicationCampaign,
    CommunicationTemplate,
    PayoutPlan,
    Promoter,
    PromoterAssignment,
    Prospect,
    ProspectStageDefinition,
    SponsorshipRate,
    VerifiedCredit,
)
from app.seed_local_crm import _fixed_uuid, seed_synthetic_crm


def _fixture():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        provision_admin(
            db, email="admin@local.sas.example",
            password="synthetic-password-with-enough-length",
            organization_name="Synthetic Foundation",
        )
        admin = db.scalars(select(AdminUser)).one()
        seed_synthetic_crm(db, admin.organization_id, admin.id)
        db.commit()
        return engine, admin.organization_id


def _add_danny(engine, org):
    with Session(engine) as db:
        linked_promoter = db.scalar(select(Promoter).where(
            Promoter.organization_id == org,
            Promoter.mobile_number == "+916000100003",
        ))
        danny = Prospect(
            organization_id=org, full_name="Danny Danyal",
            mobile_number="+918801117700", area_city="Bengaluru",
            monthly_contribution_paise=25000, start_month=date(2026, 10, 1),
            crm_stage="active", lifecycle_status="new",
            whatsapp_opt_in=False, version=1,
        )
        db.add(danny)
        db.flush()
        db.add(PromoterAssignment(
            organization_id=org, promoter_id=linked_promoter.id,
            prospect_id=danny.id,
        ))
        db.commit()
        return danny.id, linked_promoter.id


def test_guarded_cleanup_keeps_first_danny_and_their_linked_promoters():
    engine, org = _fixture()
    try:
        danny_id, linked_promoter = _add_danny(engine, org)
        with Session(engine) as db:
            before_audits = db.scalar(select(func.count(AuditEvent.id)))
            preview = cleanup_synthetic_crm(db, org)
            assert preview["applied"] is False
            assert preview["remove"] == {
                "prospects": 99, "promoters": 8, "payout_plans": 20,
                "communication_campaigns": 3, "communication_rules": 2,
                "communication_templates": 4, "unused_sample_stages": 3,
            }
            assert db.scalar(select(func.count(Prospect.id))) == 101
            assert db.scalar(select(func.count(Promoter.id))) == 10

            actual = cleanup_synthetic_crm(db, org, apply=True)
            assert actual["remove"] == preview["remove"]
            db.commit()
            kept = db.scalars(select(Prospect).where(
                Prospect.organization_id == org,
            )).all()
            first_id = db.scalar(select(Prospect.id).where(
                Prospect.registration_request_id == _fixed_uuid(org, "prospect", 1),
            ))
            assert {p.id for p in kept} == {danny_id, first_id}
            assert {p.full_name for p in kept} == {"Danny Danyal", "Demo Omar Khan"}
            assert db.scalar(select(func.count(SponsorshipRate.id))) == 1
            assert db.scalar(select(func.count(PayoutPlan.id))) == 0
            assert db.scalar(select(func.count(CommunicationCampaign.id))) == 0
            assert db.scalar(select(func.count(CommunicationTemplate.id))) == 0
            assert db.scalar(select(func.count(ProspectStageDefinition.id))) == 1
            assert db.scalar(select(func.count(AuditEvent.id))) == before_audits
            assignments = db.scalars(select(PromoterAssignment).where(
                PromoterAssignment.organization_id == org,
            )).all()
            assert len(assignments) == 2
            kept_promoters = {p.id for p in db.scalars(select(Promoter))}
            assert len(kept_promoters) == 2
            assert linked_promoter in kept_promoters
            assert {a.prospect_id for a in assignments} == {first_id, danny_id}

            after = cleanup_synthetic_crm(db, org)
            assert all(amount == 0 for amount in after["remove"].values())
    finally:
        engine.dispose()


def test_cleanup_refuses_missing_danny_without_removing_seed():
    engine, org = _fixture()
    try:
        with Session(engine) as db:
            with pytest.raises(ValueError, match="Danny Danyal"):
                cleanup_synthetic_crm(db, org, apply=True)
            assert db.scalar(select(func.count(Prospect.id))) == 100
    finally:
        engine.dispose()


def test_cleanup_refuses_any_synthetic_contact_with_credit_history():
    engine, org = _fixture()
    try:
        _add_danny(engine, org)
        with Session(engine) as db:
            person = db.scalar(select(Prospect).where(
                Prospect.registration_request_id == _fixed_uuid(org, "prospect", 2),
            ))
            db.add(VerifiedCredit(
                organization_id=org, prospect_id=person.id,
                period_month=date(2026, 10, 1), amount_paise=25000,
                source_type="bank_reconciled",
                source_key="synthetic-guard-payment-evidence",
                verified_at=datetime(2026, 10, 15, tzinfo=UTC),
            ))
            db.commit()
            with pytest.raises(ValueError, match="payment, consent or other history"):
                cleanup_synthetic_crm(db, org, apply=True)
            db.rollback()
            assert db.scalar(select(func.count(Prospect.id))) == 101
            assert db.scalar(select(func.count(PayoutPlan.id))) == 20
            assert db.scalar(select(func.count(VerifiedCredit.id))) == 1
    finally:
        engine.dispose()
