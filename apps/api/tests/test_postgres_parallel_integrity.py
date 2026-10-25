"""True concurrent PostgreSQL invariants, isolated to synthetic CI tenants.

SQLite skips these cases. Each worker uses its own connection/transaction.
All sessions are bounded by a PostgreSQL lock timeout; no external delivery.
"""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounting import effective_credits
from app.models import (
    ManualCollection,
    ManualCollectionReversal,
    MessageOutbox,
    Organization,
    Promoter,
    PromoterAssignment,
    Prospect,
    VerifiedCredit,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL", "").startswith("postgresql+psycopg://"),
    reason="Requires explicit disposable PostgreSQL CI database",
)

MONTH = date(2026, 10, 1)
RECEIVED = date(2026, 10, 13)
VERIFIED = datetime(2026, 10, 13, 10, tzinfo=UTC)


def _seed(engine, *, with_promoters=False):
    with Session(engine) as db:
        org = Organization(name=f"Parallel synthetic tenant {uuid.uuid4().hex}")
        db.add(org)
        db.flush()
        sponsor = Prospect(
            organization_id=org.id, full_name="Concurrent QA Sponsor",
            mobile_number="+918109990001", area_city="Bengaluru",
            monthly_contribution_paise=50000, start_month=MONTH,
            whatsapp_opt_in=False, lifecycle_status="new", version=1,
        )
        db.add(sponsor)
        db.flush()
        promoter_ids = []
        if with_promoters:
            for number in ("+918109990002", "+918109990003"):
                promoter = Promoter(
                    organization_id=org.id, full_name="Concurrency QA Promoter",
                    mobile_number=number, area_city="Bengaluru",
                    whatsapp_opt_in=False, is_active=True, version=1,
                )
                db.add(promoter)
                db.flush()
                promoter_ids.append(promoter.id)
        identifiers = org.id, sponsor.id, promoter_ids
        db.commit()
        return identifiers


def _race(work):
    """Start separate transactions together; surface unexpected exceptions."""
    barrier = Barrier(2, timeout=10)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(work, i, barrier) for i in range(2)]
        return [future.result(timeout=15) for future in futures]


def _credit_and_receipt(db, org_id, sponsor_id, *, request, digest):
    credit = VerifiedCredit(
        organization_id=org_id, prospect_id=sponsor_id,
        period_month=MONTH, amount_paise=25000,
        source_type="manual_attested", source_key="manual:" + digest,
        verified_at=VERIFIED,
    )
    db.add(credit)
    db.flush()
    receipt = ManualCollection(
        organization_id=org_id, prospect_id=sponsor_id,
        verified_credit_id=credit.id, request_id=request,
        request_payload_hash="c" * 64, reference_digest=digest,
        reference_mask="****0001", received_on=RECEIVED, period_month=MONTH,
        payment_method="upi", amount_paise=25000,
    )
    db.add(receipt)
    db.flush()
    db.add(MessageOutbox(
        organization_id=org_id, prospect_id=sponsor_id,
        collection_id=receipt.id, event_type="collection_recorded",
        status="suppressed", suppress_reason="consent_missing",
    ))
    return receipt.id


def test_parallel_duplicate_attested_collection_is_atomic():
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        org_id, sponsor_id, _ = _seed(engine)
        request = uuid.uuid4()
        digest = uuid.uuid4().hex.ljust(64, "0")

        def worker(_index, barrier):
            with Session(engine) as db:
                db.execute(text("SET LOCAL lock_timeout = '5s'"))
                barrier.wait()
                try:
                    _credit_and_receipt(
                        db, org_id, sponsor_id, request=request, digest=digest,
                    )
                    db.commit()
                    return "committed"
                except IntegrityError:
                    db.rollback()
                    return "conflict"

        assert sorted(_race(worker)) == ["committed", "conflict"]
        with Session(engine) as db:
            filters = [VerifiedCredit.organization_id == org_id]
            assert db.scalar(select(func.count(VerifiedCredit.id)).where(*filters)) == 1
            assert db.scalar(select(func.count(ManualCollection.id)).where(
                ManualCollection.organization_id == org_id,
            )) == 1
            assert db.scalar(select(func.count(MessageOutbox.id)).where(
                MessageOutbox.organization_id == org_id,
            )) == 1
            assert sum(row.amount_paise for row in effective_credits(
                db, org_id, sponsor_id=sponsor_id,
            )) == 25000
    finally:
        engine.dispose()


def test_parallel_reversals_only_remove_one_net_credit():
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        org_id, sponsor_id, _ = _seed(engine)
        with Session(engine) as db:
            receipt_id = _credit_and_receipt(
                db, org_id, sponsor_id,
                request=uuid.uuid4(), digest=uuid.uuid4().hex.ljust(64, "0"),
            )
            db.commit()

        def worker(_index, barrier):
            with Session(engine) as db:
                db.execute(text("SET LOCAL lock_timeout = '5s'"))
                db.add(ManualCollectionReversal(
                    organization_id=org_id, collection_id=receipt_id,
                    request_id=uuid.uuid4(), reason_code="wrong_amount",
                ))
                barrier.wait()
                try:
                    db.commit()
                    return "committed"
                except IntegrityError:
                    db.rollback()
                    return "conflict"

        assert sorted(_race(worker)) == ["committed", "conflict"]
        with Session(engine) as db:
            assert db.scalar(select(func.count(ManualCollectionReversal.id)).where(
                ManualCollectionReversal.organization_id == org_id,
            )) == 1
            assert db.scalar(select(func.count(ManualCollection.id)).where(
                ManualCollection.organization_id == org_id,
            )) == 1
            assert effective_credits(db, org_id, sponsor_id=sponsor_id) == []
    finally:
        engine.dispose()


def test_parallel_competing_promoter_assignments_allow_one_current_owner():
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        org_id, sponsor_id, promoters = _seed(engine, with_promoters=True)

        def worker(index, barrier):
            with Session(engine) as db:
                db.execute(text("SET LOCAL lock_timeout = '5s'"))
                db.add(PromoterAssignment(
                    organization_id=org_id,
                    promoter_id=promoters[index],
                    prospect_id=sponsor_id,
                ))
                barrier.wait()
                try:
                    db.commit()
                    return "committed"
                except IntegrityError:
                    db.rollback()
                    return "conflict"

        assert sorted(_race(worker)) == ["committed", "conflict"]
        with Session(engine) as db:
            owners = db.scalars(select(PromoterAssignment).where(
                PromoterAssignment.organization_id == org_id,
                PromoterAssignment.prospect_id == sponsor_id,
                PromoterAssignment.ended_at.is_(None),
            )).all()
            assert len(owners) == 1
            assert owners[0].promoter_id in promoters
    finally:
        engine.dispose()


def test_parallel_tenants_can_use_the_same_receipt_evidence_independently():
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        tenants = [_seed(engine), _seed(engine)]
        request = uuid.uuid4()
        digest = uuid.uuid4().hex.ljust(64, "0")

        def worker(index, barrier):
            org_id, sponsor_id, _ = tenants[index]
            with Session(engine) as db:
                db.execute(text("SET LOCAL lock_timeout = '5s'"))
                barrier.wait()
                _credit_and_receipt(
                    db, org_id, sponsor_id, request=request, digest=digest,
                )
                db.commit()
                return org_id

        assert set(_race(worker)) == {tenant[0] for tenant in tenants}
        with Session(engine) as db:
            for org_id, sponsor_id, _ in tenants:
                assert db.scalar(select(func.count(ManualCollection.id)).where(
                    ManualCollection.organization_id == org_id,
                )) == 1
                assert sum(x.amount_paise for x in effective_credits(
                    db, org_id, sponsor_id=sponsor_id,
                )) == 25000
    finally:
        engine.dispose()
