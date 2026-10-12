"""Production-dialect smoke tests, run only after migrations on the CI PostgreSQL service."""

import os
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AdminUser,
    AuditEvent,
    Organization,
    OrganizationSettings,
    Prospect,
    ProspectUpiIdentifier,
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
