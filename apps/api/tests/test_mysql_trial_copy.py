"""Cross-dialect synthetic-only transfer/reconciliation trial. No real records."""

import os
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import mysql_trial_copy as copier
from app.bootstrap_admin import provision_admin
from app.models import (
    AdminUser,
    AuditEvent,
    Base,
    CommunicationCampaign,
    ManualCollection,
    MessageOutbox,
    Prospect,
    SaasytoCampaignRecipient,
    SaasytoCampaignRun,
    SponsorOtpChallenge,
    VerifiedCredit,
)
from app.mysql_trial_schema import (
    create_trial_schema,
    install_trial_financial_guards,
    make_trial_engine,
)


@pytest.fixture(scope="module")
def disposable_pair():
    source_url = os.environ.get("SAS_PG_TRIAL_SOURCE_URL")
    target_url = os.environ.get("SAS_MYSQL_TRIAL_URL")
    if not source_url or not target_url:
        pytest.skip("Synthetic PostgreSQL and MySQL CI services not configured")
    source = create_engine(source_url, isolation_level="REPEATABLE READ")
    target = make_trial_engine(target_url)
    try:
        Base.metadata.create_all(source, checkfirst=False)
        create_trial_schema(target, defer_payment_guards=True)
        yield source, target
    finally:
        source.dispose()
        target.dispose()


def _seed_pg(source):
    # Both timestamps and stored JSON must survive across dialects.
    with Session(source) as db:
        provision_admin(
            db,
            email="mysql-copy-trial@example.com",
            password="ephemeral-test-password-never-in-production",
            organization_name="Synthetic Copy Foundation",
        )
        admin = db.scalars(select(AdminUser)).one()
        fixed = datetime(
            2026, 10, 28, 16, 28, 42, 123456,
            tzinfo=timezone(timedelta(hours=5, minutes=30)),
        )
        person = Prospect(
            organization_id=admin.organization_id,
            full_name="Synthetic source prospect",
            mobile_number="+919876501934",
            area_city="Synthetic Bengaluru",
            monthly_contribution_paise=25000,
            whatsapp_opt_in=False,
            status_updated_at=fixed,
            next_followup_at=fixed,
        )
        db.add(person)
        db.flush()
        otp = SponsorOtpChallenge(
            organization_id=admin.organization_id,
            prospect_id=person.id,
            phone_digest="b" * 64,
            code_digest="c" * 64,
            status="unknown",
            attempts=1,
            created_at=fixed,
            expires_at=fixed + timedelta(minutes=2),
        )
        db.add(otp)
        credit = VerifiedCredit(
            organization_id=admin.organization_id,
            prospect_id=person.id,
            period_month=date(2026, 10, 1),
            amount_paise=25000,
            source_type="manual_attested",
            source_key="synthetic-credit-copy-001",
            verified_at=fixed,
        )
        db.add(credit)
        db.flush()
        payment = ManualCollection(
            organization_id=admin.organization_id,
            prospect_id=person.id,
            verified_credit_id=credit.id,
            request_id=uuid.uuid4(),
            request_payload_hash="d" * 64,
            reference_digest="e" * 64,
            reference_mask="****1234",
            received_on=date(2026, 10, 28),
            period_month=date(2026, 10, 1),
            payment_method="upi",
            amount_paise=25000,
            recorded_by_admin_id=admin.id,
        )
        db.add(payment)
        db.flush()
        # A grandfathered historical payment predates the enforced ₹250
        # increment. Its exact amount and verified credit must survive.
        legacy_credit = VerifiedCredit(
            organization_id=admin.organization_id,
            prospect_id=person.id,
            period_month=date(2025, 5, 1),
            amount_paise=12500,
            source_type="manual_attested",
            source_key="legacy-half-tier-before-policy",
            verified_at=fixed,
        )
        db.add(legacy_credit)
        db.flush()
        legacy_payment = ManualCollection(
            organization_id=admin.organization_id,
            prospect_id=person.id,
            verified_credit_id=legacy_credit.id,
            request_id=uuid.uuid4(),
            request_payload_hash="2" * 64,
            reference_digest="3" * 64,
            reference_mask="****5678",
            received_on=date(2025, 5, 20),
            period_month=date(2025, 5, 1),
            payment_method="upi",
            amount_paise=12500,
            recorded_by_admin_id=admin.id,
        )
        db.add(legacy_payment)
        db.flush()
        db.add(MessageOutbox(
            organization_id=admin.organization_id,
            prospect_id=person.id,
            collection_id=payment.id,
            event_type="collection_confirmation",
            status="suppressed",
            suppress_reason="no_permission",
        ))
        campaign = CommunicationCampaign(
            organization_id=admin.organization_id,
            request_id=uuid.uuid4(),
            title="Synthetic historic campaign",
            channel="whatsapp",
            audience="prospects",
            segment="all",
            category="announcement",
            body="Do not send — synthetic test",
            status="scheduled",
            planned_for=fixed,
            created_by_admin_id=admin.id,
        )
        db.add(campaign)
        db.flush()
        run = SaasytoCampaignRun(
            organization_id=admin.organization_id,
            campaign_id=campaign.id,
            status="completed",
            due_at=fixed,
            approved_at=fixed,
            approved_by_admin_id=admin.id,
            eligible_count=1,
            suppressed_count=0,
        )
        db.add(run)
        db.flush()
        db.add(SaasytoCampaignRecipient(
            organization_id=admin.organization_id,
            run_id=run.id,
            recipient_kind="prospect",
            recipient_id=person.id,
            approved_phone_digest="f" * 64,
            status="unknown",
            reason="worker_interrupted",
            claimed_at=fixed,
            finished_at=fixed + timedelta(seconds=1),
        ))
        db.add(AuditEvent(
            organization_id=admin.organization_id,
            actor_admin_id=admin.id,
            action="mysql.synthetic_snapshot",
            entity_type="prospect",
            entity_id=str(person.id),
            before_data=None,
            after_data={"nested": {"keys": ["a", "b"], "value": 250}},
        ))
        db.commit()
        return person.id, payment.id, otp.id, legacy_payment.id, fixed.astimezone(UTC)


def test_copy_rejects_non_trial_urls_before_connection(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SAS_MYSQL_TRIAL_ONLY", "1")
    monkeypatch.setenv("SAS_MYSQL_COPY_TRIAL_ONLY", "1")
    # URL-only stubs avoid importing optional PyMySQL in the regular backend
    # job and demonstrate that production-shaped URLs are rejected pre-connect.
    source = SimpleNamespace(url=make_url(
        "postgresql+psycopg://bad:bad@127.0.0.1:5432/production_data"
    ))
    target = SimpleNamespace(url=make_url(
        "mysql+pymysql://bad:bad@127.0.0.1:3306/production_data"
    ))
    with pytest.raises(RuntimeError, match="loopback databases"):
        copier.transfer_synthetic_snapshot(source, target, hmac_key=b"x" * 32)


def test_complete_snapshot_copy_rolls_back_on_mismatch(disposable_pair, monkeypatch):
    source, target = disposable_pair
    sponsor_id, collection_id, otp_id, legacy_collection_id, timestamp = _seed_pg(source)
    source_counts = {}
    with source.connect() as db:
        for table in Base.metadata.tables.values():
            source_counts[table.name] = db.scalar(
                select(func.count()).select_from(table)
            )

    original = copier._utc_mysql_copy

    def wrong_copy(row):
        converted = original(row)
        if converted.get("mobile_number") == "+919876501934":
            converted["area_city"] = "wrong synthetic city"
        return converted

    monkeypatch.setattr(copier, "_utc_mysql_copy", wrong_copy)
    with pytest.raises(RuntimeError, match="content mismatch"):
        copier.transfer_synthetic_snapshot(source, target, hmac_key=b"x" * 32)
    with target.connect() as db:
        assert all(
            db.scalar(select(func.count()).select_from(table)) == 0
            for table in Base.metadata.tables.values()
        )

    monkeypatch.setattr(copier, "_utc_mysql_copy", original)
    result = copier.transfer_synthetic_snapshot(source, target, hmac_key=b"x" * 32)
    assert result == {
        "result": "verified_synthetic_copy",
        "tables": len(Base.metadata.tables),
        "rows": sum(source_counts.values()),
        "cutover_authorized": False,
    }

    # After verifying every historical record, restore new-write guards.
    # This runs after the transaction commits: MySQL DDL is not transactional.
    install_trial_financial_guards(target)
    with target.connect() as conn:
        assert conn.scalar(text("""
            SELECT COUNT(*) FROM information_schema.triggers
            WHERE trigger_schema = DATABASE()
              AND trigger_name IN ('sas_manual_collection_tier_insert',
                                   'sas_manual_collection_tier_update')
        """)) == 2
    with Session(target) as db:
        with pytest.raises(DBAPIError):
            db.execute(
                text("UPDATE manual_collections SET amount_paise = 37500 WHERE id = :id"),
                {"id": legacy_collection_id.hex},
            )
            db.commit()
        db.rollback()
    with Session(target) as db:
        restored = db.get(Prospect, sponsor_id)
        assert restored.mobile_number == "+919876501934"
        assert restored.next_followup_at == timestamp.replace(tzinfo=None)
        assert restored.next_followup_at.microsecond == 123456
        assert db.get(ManualCollection, collection_id).amount_paise == 25000
        assert db.get(ManualCollection, legacy_collection_id).amount_paise == 12500
        assert db.get(SponsorOtpChallenge, otp_id).status == "unknown"
        assert db.scalars(select(SaasytoCampaignRecipient)).one().status == "unknown"
        assert db.scalars(select(MessageOutbox)).one().status == "suppressed"
        assert db.scalars(select(AuditEvent).where(
            AuditEvent.action == "mysql.synthetic_snapshot"
        )).one().after_data["nested"]["keys"] == ["a", "b"]

    with pytest.raises(RuntimeError, match="not empty"):
        copier.transfer_synthetic_snapshot(source, target, hmac_key=b"x" * 32)

    # The source must never be altered by either a failed or successful copy.
    with source.connect() as db:
        assert all(db.scalar(select(func.count()).select_from(table)) == count
                   for table, count in (
                       (Base.metadata.tables[name], amount)
                       for name, amount in source_counts.items()
                   ))
