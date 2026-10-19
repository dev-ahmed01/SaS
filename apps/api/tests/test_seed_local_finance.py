"""Synthetic finance fixtures cover received/outstanding/planned/disbursed states.

These are only written to in-memory SQLite for testing. No genuine payments.
"""
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.bootstrap_admin import provision_admin
from app.models import (
    AdminUser, Base, ManualCollection, ManualCollectionReversal, MessageOutbox,
    PayoutPayment, PayoutPlan, Prospect, VerifiedCredit,
)
from app.seed_local_crm import seed_synthetic_crm
from app.seed_local_finance import seed_finance_examples, assert_disposable_demo

SECRET="synthetic-only-fixture-key-more-than-thirty-two-characters"

@pytest.fixture
def system():
    engine=create_engine("sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread":False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        provision_admin(db,email="admin@local.sas.example",
            password="synthetic-long-password",organization_name="Emlen Foundation")
        admin=db.scalars(select(AdminUser)).one()
        seed_synthetic_crm(db,admin.organization_id,admin.id)
        db.commit()
    yield engine
    engine.dispose()

def test_opt_in_finance_examples_are_idempotent_and_accounted_for(system):
    with Session(system) as db:
        admin=db.scalars(select(AdminUser)).one()
        counts=seed_finance_examples(db,admin.organization_id,admin.id,SECRET)
        db.commit()
        assert counts=={
            "collections":20,"collection_reversals":2,
            "payout_plans":12,"payout_payments":5,
        }
        assert db.scalar(select(func.count(ManualCollection.id)))==20
        assert db.scalar(select(func.count(ManualCollectionReversal.id)))==2
        assert db.scalar(select(func.count(VerifiedCredit.id)))==20
        assert db.scalar(select(func.count(MessageOutbox.id)))==20
        assert {x.status for x in db.scalars(select(MessageOutbox))}=={"suppressed"}
        assert db.scalar(select(func.count(PayoutPlan.id)))==12
        assert db.scalar(select(func.count(PayoutPayment.id)))==5
        assert all(x.payee_name.startswith("Demo ")
                   for x in db.scalars(select(PayoutPlan)))
        assert all(x.whatsapp_opt_in is False for x in db.scalars(select(Prospect)))
        again=seed_finance_examples(db,admin.organization_id,admin.id,SECRET)
        db.commit()
        assert not any(again.values())
        assert db.scalar(select(func.count(VerifiedCredit.id)))==20

def test_guard_rejects_mixed_real_and_synthetic_contacts(system):
    with Session(system) as db:
        admin=db.scalars(select(AdminUser)).one()
        prospect=db.scalars(select(Prospect)).first()
        prospect.full_name="A real-looking user"
        db.flush()
        with pytest.raises(ValueError,match="Non-demo prospects"):
            assert_disposable_demo(db,admin.organization_id)
        with pytest.raises(ValueError,match="Non-demo prospects"):
            seed_finance_examples(db,admin.organization_id,admin.id,SECRET)
        db.rollback()
        assert db.scalar(select(func.count(VerifiedCredit.id)))==0
