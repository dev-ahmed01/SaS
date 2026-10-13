"""Phase-1 executable acceptance tests: API, schema, configuration and constraints."""

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.main import app
from app.models import AdminUser, AuditEvent, Base, Organization, OrganizationSettings


def test_liveness_is_public_and_minimal() -> None:
    response = TestClient(app).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_uses_database(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    monkeypatch.setattr("app.main.get_engine", lambda: engine)
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    engine.dispose()


def test_ready_returns_safe_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable():
        raise ValueError("secret database host and password")

    monkeypatch.setattr("app.main.get_engine", unavailable)
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "password" not in response.text


def test_production_rejects_sqlite() -> None:
    with pytest.raises(ValidationError, match="require PostgreSQL"):
        Settings(app_env="production", database_url="sqlite+pysqlite:///:memory:")


def make_settings(org_id: uuid.UUID, **updates: object) -> OrganizationSettings:
    values: dict[str, object] = {
        "organization_id": org_id,
        "currency_code": "INR",
        "timezone": "Asia/Kolkata",
        "default_contribution_paise": 25000,
        "sponsor_reminder_day": 5,
        "promoter_reminder_day": 20,
        "inactivity_months": 2,
        "automation_enabled": False,
    }
    values.update(updates)
    return OrganizationSettings(**values)


def test_org_settings_are_persisted_not_hardcoded() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        org = Organization(name="Emlen Foundation")
        session.add(org)
        session.flush()
        session.add(make_settings(org.id))
        session.commit()
        saved = session.scalars(select(OrganizationSettings)).one()
        assert saved.default_contribution_paise == 25000
        assert saved.timezone == "Asia/Kolkata"
        saved.default_contribution_paise = 30000
        saved.sponsor_reminder_day = 8
        session.commit()
    with Session(engine) as session:
        updated = session.scalars(select(OrganizationSettings)).one()
        assert (updated.default_contribution_paise, updated.sponsor_reminder_day) == (30000, 8)
    engine.dispose()


@pytest.mark.parametrize(
    "field,bad_value",
    [("default_contribution_paise", 0), ("sponsor_reminder_day", 32),
     ("promoter_reminder_day", 0), ("inactivity_months", 0)],
)
def test_invalid_business_settings_rejected_by_db(field: str, bad_value: int) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        org = Organization(name="Emlen Foundation")
        session.add(org)
        session.flush()
        session.add(make_settings(org.id, **{field: bad_value}))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    engine.dispose()


def test_admin_has_hashed_password_column_and_audit_table() -> None:
    assert "password_hash" in AdminUser.__table__.columns
    assert "password" not in AdminUser.__table__.columns
    assert {"action", "entity_type", "before_data", "after_data"}.issubset(
        AuditEvent.__table__.columns.keys()
    )
