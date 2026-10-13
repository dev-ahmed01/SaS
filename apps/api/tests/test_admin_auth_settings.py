"""Phase 03 Admin authorization, CSRF, audited settings and session lifecycle tests."""

import hashlib
import hmac
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
            email="admin@foundation.org", password="test-only-very-long-password",
            amount_paise=50000,
        )
    monkeypatch.setattr("app.auth.get_engine", lambda: engine)
    monkeypatch.setattr(
        "app.auth.get_settings",
        lambda: SimpleNamespace(auth_secret=SECRET, app_env="test"),
    )
    with TestClient(app) as client:
        yield client, engine
    engine.dispose()


def sign_in(client: TestClient, email: str = "admin@foundation.org") -> str:
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
        assert admin.email == "admin@foundation.org"
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
        client.patch("/v1/settings", json={"default_contribution_paise": 75000}).status_code
        == 401
    )


def test_login_uses_generic_failures_and_tracks_throttle(environment) -> None:
    client, _engine = environment
    for email in ["nobody@samplemail.org", "admin@foundation.org"]:
        response = client.post("/v1/auth/login", json={"email": email, "password": "wrong-pass"})
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"
    sign_in(client)


def test_login_rate_limit_is_enforced_across_multiple_requests(environment) -> None:
    client, _engine = environment
    for _ in range(8):
        assert client.post(
            "/v1/auth/login",
            json={"email": "admin@foundation.org", "password": "wrong-pass"},
        ).status_code == 401
    assert client.post(
        "/v1/auth/login",
        json={"email": "admin@foundation.org", "password": "test-only-very-long-password"},
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
        "default_contribution_paise": 50000,
        "sponsor_reminder_day": 5,
        "promoter_reminder_day": 20,
        "inactivity_months": 2,
        "automation_enabled": False,
    }
    assert client.patch(
        "/v1/settings", json={"default_contribution_paise": 75000}
    ).status_code == 403
    response = client.patch(
        "/v1/settings",
        headers={"X-CSRF-Token": csrf},
        json={"default_contribution_paise": 75000, "sponsor_reminder_day": 6},
    )
    assert response.status_code == 200, response.text
    assert response.json()["default_contribution_paise"] == 75000
    assert response.json()["sponsor_reminder_day"] == 6
    assert response.json()["automation_enabled"] is False
    with Session(engine) as database:
        events = database.scalars(
            select(AuditEvent).where(AuditEvent.action == "settings.updated")
        ).all()
        assert len(events) == 1
        assert events[0].before_data == {
            "default_contribution_paise": 50000, "sponsor_reminder_day": 5
        }
        assert events[0].after_data == {
            "default_contribution_paise": 75000, "sponsor_reminder_day": 6
        }
        assert events[0].actor_admin_id is not None
    for invalid in [
        {"currency_code": "USD"},
        {"automation_enabled": True},
        {"sponsor_reminder_day": 35},
        {"inactivity_months": 0},
        {"inactivity_months": 3},
        {"default_contribution_paise": 37500},
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
                promoter_reminder_day=22, inactivity_months=2, automation_enabled=False,
            )
        )
        database.commit()
    assert client.get("/v1/settings").json()["default_contribution_paise"] == 50000


def test_csrf_is_session_bound(environment) -> None:
    client, _engine = environment
    csrf = sign_in(client)
    assert client.patch(
        "/v1/settings",
        headers={"X-CSRF-Token": "0" * 64},
        json={"sponsor_reminder_day": 7},
    ).status_code == 403
    client.cookies.clear()
    other_csrf = sign_in(client)
    assert csrf != other_csrf
    assert client.patch(
        "/v1/settings",
        headers={"X-CSRF-Token": csrf},
        json={"sponsor_reminder_day": 7},
    ).status_code == 403
    assert client.patch(
        "/v1/settings",
        headers={"X-CSRF-Token": other_csrf},
        json={"sponsor_reminder_day": 7},
    ).status_code == 200


def test_no_password_or_tokens_in_settings_response(environment) -> None:
    client, _engine = environment
    sign_in(client)
    result = client.get("/v1/settings")
    assert result.status_code == 200
    assert "password" not in result.text.lower()
    assert "csrf" not in result.text.lower()


def test_shared_gateway_cannot_lock_unrelated_emails_via_unsigned_network(environment):
    client, _engine = environment
    for n in range(8):
        r = client.post("/v1/auth/login", json={
            "email": f"unknown{n}@example.org", "password": "wrong-pass",
        }, headers={
            "X-SaS-Login-Client-IP": "198.51.100.17",
            "X-SaS-Login-Client-Signature": "0" * 64,
        })
        assert r.status_code == 401, r.text
    sign_in(client)


def test_valid_signed_client_ip_enforces_network_anti_spray(environment):
    client, _engine = environment

    def signed(ip):
        return {
            "X-SaS-Login-Client-IP": ip,
            "X-SaS-Login-Client-Signature": hmac.new(
                SECRET.encode("utf-8"),
                ("sas:bff-login-client:v1:" + ip).encode("ascii"),
                hashlib.sha256,
            ).hexdigest(),
        }

    for n in range(8):
        r = client.post("/v1/auth/login", json={
            "email": f"spray{n}@example.org", "password": "wrong-pass",
        }, headers=signed("203.0.113.19"))
        assert r.status_code == 401, r.text
    blocked = client.post("/v1/auth/login", json={
        "email": "admin@foundation.org",
        "password": "test-only-very-long-password",
    }, headers=signed("203.0.113.19"))
    assert blocked.status_code == 429
    other = client.post("/v1/auth/login", json={
        "email": "admin@foundation.org",
        "password": "test-only-very-long-password",
    }, headers=signed("203.0.113.20"))
    assert other.status_code == 200, other.text


def test_automation_enable_is_separate_audited_fail_closed_admin_action(
    environment, monkeypatch,
) -> None:
    from types import SimpleNamespace

    client, engine = environment
    csrf = sign_in(client)
    monkeypatch.setattr("app.admin_settings.get_settings", lambda: SimpleNamespace(
        app_env="test",
        messaging_delivery_enabled=False,
        messaging_sender_approved=False,
        messaging_enable_after=None,
    ))
    url = "/v1/settings/automation"
    enable = {"enabled": True, "confirmation": "ENABLE WHATSAPP"}
    assert client.post(url, json=enable).status_code == 403
    assert client.post(url, headers={"X-CSRF-Token": csrf}, json={
        **enable, "confirmation": "ENABLE",
    }).status_code == 422
    # A development environment never enables real delivery.
    assert client.post(url, headers={"X-CSRF-Token": csrf},
                       json=enable).status_code == 409
    assert client.get("/v1/settings").json()["automation_enabled"] is False

    monkeypatch.setattr("app.admin_settings.get_settings", lambda: SimpleNamespace(
        app_env="production",
        messaging_delivery_enabled=True,
        messaging_sender_approved=True,
        messaging_enable_after=utc_now() + timedelta(days=1),
    ))
    accepted = client.post(url, headers={"X-CSRF-Token": csrf}, json=enable)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["automation_enabled"] is True
    assert client.post(url, headers={"X-CSRF-Token": csrf},
                       json=enable).status_code == 200
    stopped = client.post(url, headers={"X-CSRF-Token": csrf}, json={
        "enabled": False, "confirmation": "DISABLE WHATSAPP",
    })
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["automation_enabled"] is False
    with Session(engine) as db:
        events = db.scalars(select(AuditEvent).where(
            AuditEvent.action == "settings.automation_changed",
        )).all()
        assert len(events) == 2
        assert events[0].before_data == {"automation_enabled": False}
        assert events[0].after_data == {"automation_enabled": True}
        assert events[1].before_data == {"automation_enabled": True}
        assert events[1].after_data == {"automation_enabled": False}
