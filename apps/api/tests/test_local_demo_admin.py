"""Local Admin is opt-in and cannot weaken production authentication."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import Credentials
from app.bootstrap_admin import provision_admin
from app.config import Settings
from app.main import app
from app.models import AdminUser, Base, OrganizationSettings
from app.security import verify_password

SECRET = "synthetic-local-auth-secret-longer-than-32-characters"
LOCAL_DB = "postgresql+psycopg://sas_dev:local-only@127.0.0.1:5432/sas_dev"


def test_local_demo_mode_must_use_loopback_postgres():
    valid = Settings(
        app_env="development",
        database_url=LOCAL_DB,
        local_demo_login_enabled=True,
        auth_secret=SECRET,
    )
    assert valid.local_demo_login_enabled
    for kwargs in [
        {"app_env": "production"},
        {"app_env": "staging"},
        {"database_url": LOCAL_DB.replace("127.0.0.1", "db.example.org")},
        {"database_url": LOCAL_DB.replace("/sas_dev", "/sas_live")},
        {"database_url": LOCAL_DB.replace(":5432/", ":5433/")},
        {"database_url": LOCAL_DB.replace("sas_dev:local", "dbowner:local")},
    ]:
        with pytest.raises(ValidationError):
            Settings(
                app_env=kwargs.get("app_env", "development"),
                database_url=kwargs.get("database_url", LOCAL_DB),
                local_demo_login_enabled=True,
                auth_secret=SECRET,
                upi_match_secret=SECRET,
            )


def test_ordinary_short_admin_password_still_rejected(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.bootstrap_admin.get_settings", lambda: SimpleNamespace(
        local_demo_login_enabled=False,
    ))
    with Session(engine) as db:
        with pytest.raises(ValueError, match="12 to 128"):
            provision_admin(
                db, email="test@example.org", password="shortpass",
                organization_name="Emlen Foundation",
            )
        with pytest.raises(ValueError, match="exception is disabled"):
            provision_admin(
                db, email="admin@local.sas.example", password="shortpass",
                organization_name="Emlen Foundation",
                local_demo_short_password=True,
            )
        assert db.scalars(select(AdminUser)).all() == []
    engine.dispose()


def test_username_admin_signs_in_only_in_opted_in_development(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.bootstrap_admin.get_settings", lambda: SimpleNamespace(
        local_demo_login_enabled=True,
    ))
    with Session(engine) as db:
        provision_admin(
            db, email="admin@local.sas.example", password="shortpass",
            organization_name="Emlen Foundation", local_demo_short_password=True,
        )
        user = db.scalars(select(AdminUser)).one()
        assert user.email == "admin@local.sas.example"
        assert user.password_hash.startswith("$argon2id$")
        assert verify_password(user.password_hash, "shortpass")
        assert db.get(OrganizationSettings, user.organization_id).automation_enabled is False

    monkeypatch.setattr("app.auth.get_engine", lambda: engine)
    monkeypatch.setattr("app.auth.get_settings", lambda: SimpleNamespace(
        app_env="development", local_demo_login_enabled=True, auth_secret=SECRET,
    ))
    with TestClient(app) as client:
        good = client.post("/v1/auth/login", json={
            "email": "Admin", "password": "shortpass",
        })
        assert good.status_code == 200, good.text
        assert client.get("/v1/auth/session").status_code == 200

    monkeypatch.setattr("app.auth.get_settings", lambda: SimpleNamespace(
        app_env="production", local_demo_login_enabled=False, auth_secret=SECRET,
    ))
    with pytest.raises(ValidationError):
        Credentials.model_validate({"email": "Admin", "password": "shortpass"})
    with TestClient(app) as client:
        blocked = client.post("/v1/auth/login", json={
            "email": "Admin", "password": "shortpass",
        })
        assert blocked.status_code == 422
    engine.dispose()
