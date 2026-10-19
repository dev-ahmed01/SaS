"""Historic collections are retained; new direct DB writes follow ₹250 tiers."""
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ManualCollection, Organization, VerifiedCredit


def _receipt(db: Session, organization_id, sponsor_id, amount: int, label: str):
    credit = VerifiedCredit(
        organization_id=organization_id, prospect_id=sponsor_id,
        period_month=date(2026, 10, 1), amount_paise=amount,
        source_type="manual_attested", source_key="manual:" + label,
        verified_at=datetime(2026, 10, 13, 10, tzinfo=UTC),
    )
    db.add(credit)
    db.flush()
    collection = ManualCollection(
        organization_id=organization_id, prospect_id=sponsor_id,
        verified_credit_id=credit.id, request_id=uuid.uuid4(),
        request_payload_hash=label[:1] * 64,
        reference_digest=label[-1:] * 64, reference_mask="****" + label[-4:],
        received_on=date(2026, 10, 13), period_month=date(2026, 10, 1),
        payment_method="upi", amount_paise=amount,
    )
    db.add(collection)
    db.flush()
    return collection


def test_new_denomination_policy_preserves_historical_receipt(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    url = "sqlite+pysqlite:///" + str(tmp_path / "historic-tiers.sqlite")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.chdir(root)
    get_settings.cache_clear()
    config = Config(str(root / "alembic.ini"))
    try:
        command.upgrade(config, "0012_fixed_inactivity_policy")
        engine = create_engine(url)
        with Session(engine) as db:
            org = Organization(name="Synthetic pre-policy organization")
            db.add(org)
            db.flush()
            sponsor_id = uuid.uuid4()
            # Use a version-specific INSERT so future model fields aren't
            # included when testing pre-migration schema behavior.
            db.execute(text("""
                INSERT INTO prospects (
                  id, organization_id, full_name, mobile_number, area_city,
                  monthly_contribution_paise, version, start_month,
                  lifecycle_status, whatsapp_opt_in
                ) VALUES (
                  :id, :org_id, :name, :mobile, :city, 50000, 1, :start, 'new', 0
                )
            """), {
                "id": sponsor_id.hex, "org_id": org.id.hex,
                "name": "Synthetic historical sponsor",
                "mobile": "+919876512333", "city": "Bengaluru", "start": "2026-10-01",
            })
            old = _receipt(db, org.id, sponsor_id, 12500, "hist-a")
            db.commit()
            original_id, org_id = old.id, org.id
        engine.dispose()

        command.upgrade(config, "head")
        engine = create_engine(url)
        with Session(engine) as db:
            historical = db.get(ManualCollection, original_id)
            assert historical.amount_paise == 12500  # immutable old evidence
            with pytest.raises(IntegrityError):
                _receipt(db, org_id, sponsor_id, 37500, "bad-b")
            db.rollback()
        with Session(engine) as db:
            accepted = _receipt(db, org_id, sponsor_id, 25000, "good-c")
            db.commit()
            accepted_id = accepted.id
        with Session(engine) as db:
            amounts = sorted(row.amount_paise for row in db.scalars(
                select(ManualCollection).order_by(ManualCollection.created_at)
            ).all())
            assert amounts == [12500, 25000]
            assert db.get(ManualCollection, accepted_id) is not None
            # SQLite '%' coerces REAL to INTEGER; ensure trigger protects
            # fractional paise even for direct bypassing database writers.
            with pytest.raises(IntegrityError):
                db.execute(
                    text("UPDATE manual_collections SET amount_paise = 25000.5 "
                         "WHERE id = :id"),
                    {"id": accepted_id.hex},
                )
                db.flush()
            db.rollback()
        engine.dispose()
        command.check(config)
    finally:
        get_settings.cache_clear()
