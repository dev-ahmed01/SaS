"""Verify that legacy threshold migration audits policy changes, not money."""
import uuid
from datetime import date
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditEvent, Organization, OrganizationSettings, SponsorshipRate


def test_existing_custom_inactivity_is_audited_without_rewriting_old_rates(
    tmp_path, monkeypatch,
):
    root = Path(__file__).resolve().parents[1]
    db_url = "sqlite+pysqlite:///" + str(tmp_path / "legacy-finance.sqlite")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.chdir(root)
    get_settings.cache_clear()
    cfg = Config(str(root / "alembic.ini"))

    try:
        command.upgrade(cfg, "0011_prospect_archive_intervals")
        engine = create_engine(db_url)
        with Session(engine) as db:
            org = Organization(name="Legacy Synthetic")
            db.add(org)
            db.flush()
            db.add(OrganizationSettings(
                organization_id=org.id, currency_code="INR",
                timezone="Asia/Kolkata", default_contribution_paise=37500,
                sponsor_reminder_day=5, promoter_reminder_day=20,
                inactivity_months=4, automation_enabled=False,
            ))
            # Seed the actual historical schema, not the latest ORM's new columns.
            sponsor_id = uuid.uuid4()
            db.execute(text("""
                INSERT INTO prospects (
                  id, organization_id, full_name, mobile_number, area_city,
                  monthly_contribution_paise, version, start_month,
                  lifecycle_status, whatsapp_opt_in
                ) VALUES (
                  :id, :org_id, :name, :mobile, :city, :amount, 1, :start, 'new', 0
                )
            """), {
                "id": sponsor_id.hex, "org_id": org.id.hex, "name": "Legacy Test Sponsor",
                "mobile": "+919876500099", "city": "Bengaluru",
                "amount": 37500, "start": "2026-06-01",
            })
            db.add(SponsorshipRate(
                organization_id=org.id, prospect_id=sponsor_id,
                effective_month=date(2026, 6, 1), amount_paise=37500,
            ))
            db.commit()
            org_id = org.id
        engine.dispose()

        command.upgrade(cfg, "head")
        engine = create_engine(db_url)
        with Session(engine) as db:
            setting = db.get(OrganizationSettings, org_id)
            assert setting.inactivity_months == 2
            assert setting.default_contribution_paise == 37500
            original = db.scalars(select(SponsorshipRate)).one()
            assert original.amount_paise == 37500
            event = db.scalars(select(AuditEvent).where(
                AuditEvent.action == "settings.inactivity_policy_migrated",
            )).one()
            assert event.before_data == {"inactivity_months": 4}
            assert event.after_data == {"inactivity_months": 2}
            assert str(event.organization_id) == str(org_id)
        engine.dispose()
        command.check(cfg)
    finally:
        get_settings.cache_clear()
