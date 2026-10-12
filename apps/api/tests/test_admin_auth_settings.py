"""Phase 03 Admin authorization, CSRF, audited settings and session lifecycle tests."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.bootstrap_admin import provision_admin
from app.main import app
from app.models import AdminSession, AdminUser, AuditEvent, Base, Organization, OrganizationSettings
from app.security import COOKIE_NAME, token_digest, utc_now, verify_password

SECRET = "temporary-test-only-session-secret-long-enough-0123456789"


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        provision_admin(
            database, organization_name="Emlen Foundation",
            email="admin@foundation.test", password="test-only-very-long-password",
        )
    monkeypatch.setattr("app.auth.get_engine", lambda: engine)
    monkeypatch.setattr(
        "app.auth.get_settings",
        lambda: SimpleNamespace(auth_secret=SECRET, app_env="test"),
    )
    with TestClient(app) as client:
        yield client, engine
    engine.dispose()


def sign_in(client: TestClient, email: str = "admin@foundation.test") -> str:
    response = client.post(
        "/v1/auth/login", json={"email": email, "password": "test-only-very-long-password"}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "authenticated"}
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=lax" in response.headers["set-cookie"].lower()
    details = client.get("/v1/auth/session")
    assert details.status_code == 200
    return details.json()["csrf_token"]


def test_bootstrap_never_seeds_default_password_and_denies_duplicate(environment) -> None:
    _client, engine = environment
    with Session(engine) as database:
        admin = database.scalars(select(AdminUser)).one()
        assert admin.email == "admin@foundation.test"
        assert admin.password_hash.startswith("$argon2id$")
        assert verify_password(admin.password_hash, "test-only-very-long-password")
        assert "very-long-password" not in admin.password_hash
        assert database.scalars(select(AuditEvent)).one().action == "admin.provisioned"
        with pytest.raises(ValueError, match="already provisioned"):
            provision_admin(
                database, organization_name="Unsafe",
                email="second@example.invalid", password="test-only-very-long-password",
            )


def test_signed_out_session_denies_settings_and_user_details(environment) -> None:
    client, _engine = environment
    assert client.get("/v1/settings").status_code == 401
    assert client.get("/v1/auth/session").status_code == 401
    assert (
        client.patch("/v1/settings", json={"default_contribution_paise": 30000}).status_code
        == 401
    )


def test_login_uses_generic_failures_and_tracks_throttle(environment) -> None:
    client, _engine = environment
    for email in ["nobody@example.invalid", "admin@foundation.test"]:
        response = client.post("/v1/auth/login", json={"email": email, "password": "wrong-pass"})
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"
    sign_in(client)


def test_login_rate_limit_is_enforced_across_multiple_requests(environment) -> None:
    client, _engine = environment
    for _ in range(8):
        assert client.post(
            "/v1/auth/login",
            json={"email": "admin@foundation.test", "password": "wrong-pass"},
        ).status_code == 401
    assert client.post(
        "/v1/auth/login",
        json={"email": "admin@foundation.test", "password": "test-only-very-long-password"},
    ).status_code == 429


def test_cookie_hash_is_persisted_never_raw_token(environment) -> None:
    client, engine = environment
    sign_in(client)
    value = client.cookies.get(COOKIE_NAME)
    assert value and len(value) >= 30
    with Session(engine) as database:
        row = database.scalars(select(AdminSession)).one()
        assert row.token_hash == token_digest(value)
        assert row.token_hash != value
        assert row.expires_at > row.created_at


def test_settings_changes_are_audited_and_other_keys_cannot_be_set(environment) -> None:
    client, engine = environment
    csrf = sign_in(client)
    original = client.get("/v1/settings").json()
    assert original == {
        "currency_code": "INR",
        "timezone": "Asia/Kolkata",
        "default_contribution_paise": 25000,
        "sponsor_reminder_day": 5,
        "promoter_reminder_day": 20,
        "inactivity_months": 2,
        "automation_enabled": False,
    }
    assert client.patch(
        "/v1/settings", json={"default_contribution_paise": 30000}
    ).status_code == 403
    response = client.patch(
        "/v1/settings",
        headers={"X-CSRF-Token": csrf},
        json={"default_contribution_paise": 30000, "sponsor_reminder_day": 6},
    )
    assert response.status_code == 200, response.text
    assert response.json()["default_contribution_paise"] == 30000
    assert response.json()["sponsor_reminder_day"] == 6
    assert response.json()["automation_enabled"] is False
    with Session(engine) as database:
        events = database.scalars(
            select(AuditEvent).where(AuditEvent.action == "settings.updated")
        ).all()
        assert len(events) == 1
        assert events[0].before_data == {
            "default_contribution_paise": 25000, "sponsor_reminder_day": 5
        }
        assert events[0].after_data == {
            "default_contribution_paise": 30000, "sponsor_reminder_day": 6
        }
        assert events[0].actor_admin_id is not None
    for invalid in [
        {"currency_code": "USD"},
        {"automation_enabled": True},
        {"sponsor_reminder_day": 35},
        {"inactivity_months": 0},
        {"default_contribution_paise": -1},
        {"default_contribution_paise": None},
        {},
    ]:
        response = client.patch("/v1/settings", headers={"X-CSRF-Token": csrf}, json=invalid)
        assert response.status_code == 422, (invalid, response.text)


def test_logout_revokes_session_and_csrf_is_required(environment) -> None:
    client, engine = environment
    csrf = sign_in(client)
    assert client.post("/v1/auth/logout").status_code == 403
    response = client.post("/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert client.get("/v1/auth/session").status_code == 401
    with Session(engine) as database:
        record = database.scalars(select(AdminSession)).one()
        assert record.revoked_at is not None


def test_expired_and_disabled_sessions_cannot_access_admin_data(environment) -> None:
    client, engine = environment
    sign_in(client)
    with Session(engine) as database:
        record = database.scalars(select(AdminSession)).one()
        record.expires_at = utc_now() - timedelta(minutes=1)
        database.commit()
    assert client.get("/v1/settings").status_code == 401
    client.cookies.clear()
    sign_in(client)
    with Session(engine) as database:
        admin = database.scalars(select(AdminUser)).one()
        admin.is_active = False
        database.commit()
    assert client.get("/v1/settings").status_code == 401


def test_session_scoped_to_admin_organization(environment) -> None:
    client, engine = environment
    sign_in(client)
    with Session(engine) as database:
        other = Organization(name="Second organization")
        database.add(other)
        database.flush()
        database.add(
            OrganizationSettings(
                organization_id=other.id, currency_code="INR", timezone="Asia/Kolkata",
                default_contribution_paise=99900, sponsor_reminder_day=10,
                promoter_reminder_day=22, inactivity_months=4, automation_enabled=False,
            )
        )
        database.commit()
    assert client.get("/v1/settings").json()["default_contribution_paise"] == 25000


def test_csrf_is_session_bound(environment) -> None:
    client, _engine = environment
    csrf = sign_in(client)
    assert client.patch(
        "/v1/settings",
        headers={"X-CSRF-Token": "0" * 64},
        json={"inactivity_months": 3},
    ).status_code == 403
    client.cookies.clear()
    other_csrf = sign_in(client)
    assert csrf != other_csrf
    assert client.patch(
        "/v1/settings",
        headers={"X-CSRF-Token": csrf},
        json={"inactivity_months": 3},
    ).status_code == 403
    assert client.patch(
        "/v1/settings",
        headers={"X-CSRF-Token": other_csrf},
        json={"inactivity_months": 3},
    ).status_code == 200


def test_no_password_or_tokens_in_settings_response(environment) -> None:
    client, _engine = environment
    sign_in(client)
    result = client.get("/v1/settings")
    assert result.status_code == 200
    assert "password" not in result.text.lower()
    assert "csrf" not in result.text.lower()
