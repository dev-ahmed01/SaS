"""Guarded, deterministic local CRM seed must never fabricate payments."""
import uuid

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.bootstrap_admin import provision_admin
from app.models import (
    AdminUser,
    Base,
    Promoter,
    PromoterAssignment,
    PayoutPlan,
    PayoutPayment,
    Prospect,
    ProspectStageDefinition,
    ProspectStageTransition,
    SponsorshipRate,
    VerifiedCredit,
)
from app.seed_local_crm import seed_synthetic_crm


def _database():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def test_synthetic_seed_creates_one_hundred_prospects_and_is_idempotent():
    engine = _database()
    with Session(engine) as db:
        provision_admin(
            db, email="admin@local.sas.example", password="synthetic-long-password",
            organization_name="Emlen Foundation",
        )
        admin = db.scalars(select(AdminUser)).one()
        counts = seed_synthetic_crm(db, admin.organization_id, admin.id)
        db.commit()
        assert counts == {
            "prospects": 100, "promoters": 10, "stage_definitions": 4,
            "assignments": 80, "stage_events": 25, "payout_plans": 20,
        }
        rows = db.scalars(select(Prospect)).all()
        assert len(rows) == 100
        assert all(p.full_name.startswith("Demo ") for p in rows)
        assert all(not p.whatsapp_opt_in and p.whatsapp_number is None for p in rows)
        assert all(p.lifecycle_status == "new" for p in rows)
        assert all(p.monthly_contribution_paise % 25000 == 0 for p in rows)
        assert sum(p.crm_stage == "inactive" for p in rows) == 25
        assert sum(p.crm_stage == "active" for p in rows) == 75
        assert len(db.scalars(select(Promoter)).all()) == 10
        assert db.scalar(select(func.count(PromoterAssignment.id))) == 80
        assert db.scalar(select(func.count(ProspectStageTransition.id))) == 25
        assert db.scalar(select(func.count(SponsorshipRate.id))) == 100
        assert db.scalar(select(func.count(VerifiedCredit.id))) == 0
        assert db.scalar(select(func.count(PayoutPlan.id))) == 20
        assert db.scalar(select(func.count(PayoutPayment.id))) == 0
        again = seed_synthetic_crm(db, admin.organization_id, admin.id)
        db.commit()
        assert all(n == 0 for n in again.values())
        assert db.scalar(select(func.count(Prospect.id))) == 100
        assert db.scalar(select(func.count(Promoter.id))) == 10
        assert db.scalar(select(func.count(PayoutPlan.id))) == 20
    engine.dispose()


def test_existing_configured_stages_are_not_overwritten():
    engine = _database()
    with Session(engine) as db:
        provision_admin(
            db, email="admin@local.sas.example", password="synthetic-long-password",
            organization_name="Emlen Foundation",
        )
        admin = db.scalars(select(AdminUser)).one()
        identifier = uuid.uuid4()
        db.add(ProspectStageDefinition(
            id=identifier, organization_id=admin.organization_id,
            name="Contact requested", name_key="contact requested",
            color="#075943", sort_order=7, version=1,
        ))
        db.commit()
        counts = seed_synthetic_crm(db, admin.organization_id, admin.id)
        db.commit()
        assert counts["stage_definitions"] == 0
        assert db.scalar(select(func.count(ProspectStageDefinition.id))) == 1
        prospects = db.scalars(select(Prospect)).all()
        assert all(p.pipeline_stage_id == identifier for p in prospects)
    engine.dispose()
