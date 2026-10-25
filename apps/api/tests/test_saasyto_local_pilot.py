"""Guarded localhost Saasyto pilot: offline tests never send real messages."""
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from test_communication import create_campaign, login
from test_saasyto_campaign_dispatch import RUNNER, _approved, _cfg, _consent, _person

from app.bootstrap_admin import provision_admin
from app.config import Settings
from app.main import app
from app.models import Base, SaasytoCampaignRun
from app.saasyto_client import Submission, send_text

LOCAL_DB = "postgresql+psycopg://sas_dev:local-test@127.0.0.1:5432/sas_dev"
LOCAL_PHONE = "+919899001001"
LONG_SECRET = "synthetic-local-config-secret-longer-than-thirty-two"


@pytest.fixture
def dispatch_system(monkeypatch):
    """Isolated database + authenticated API; imported tests remain independent."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        provision_admin(
            db, email="office@foundation.org",
            password="synthetic-long-admin-password",
            organization_name="Emlen Foundation",
        )
    monkeypatch.setattr("app.auth.get_engine", lambda: engine)
    monkeypatch.setattr("app.auth.get_settings", lambda: SimpleNamespace(
        auth_secret="synthetic-secure-auth-key-longer-than-thirty-two",
        app_env="test",
    ))
    monkeypatch.setattr("app.prospects.get_settings", lambda: SimpleNamespace(
        upi_match_secret="synthetic-unique-hmac-secret-for-communication-test",
    ))
    with TestClient(app) as client:
        yield client, engine
    engine.dispose()


def settings(**overrides):
    options = dict(
        app_env="development",
        database_url=LOCAL_DB,
        auth_secret=LONG_SECRET,
        local_demo_login_enabled=True,
        saasyto_local_test_enabled=True,
        saasyto_local_test_phone=LOCAL_PHONE,
    )
    options.update(overrides)
    return Settings(**options)


def test_local_mode_is_opt_in_and_requires_exact_loopback_demo_database():
    conf = settings()
    assert conf.saasyto_local_test_enabled
    assert conf.saasyto_delivery_enabled is False
    for overrides in (
        {"local_demo_login_enabled": False},
        {"app_env": "production"},
        {"app_env": "test"},
        {"app_env": "staging"},
        {"database_url": LOCAL_DB.replace("127.0.0.1", "db.example.com")},
        {"database_url": LOCAL_DB.replace("/sas_dev", "/foundation_live")},
        {"database_url": LOCAL_DB.replace(":5432/", ":5433/")},
        {"saasyto_local_test_phone": "not-a-number"},
        {"saasyto_local_test_phone": None},
    ):
        with pytest.raises(ValidationError):
            settings(**overrides)


def test_explicit_sender_approval_cutoff_secret_and_instance_are_required():
    valid = dict(
        saasyto_delivery_enabled=True,
        saasyto_sender_approved=True,
        saasyto_instance_id="test_instance_001",
        saasyto_access_token=SecretStr("synthetic-no-real-token"),
        saasyto_runner_secret=SecretStr(RUNNER),
        saasyto_enable_after=datetime.now(UTC)-timedelta(minutes=1),
    )
    assert settings(**valid).saasyto_delivery_enabled
    for key, value in (
        ("saasyto_local_test_enabled", False),
        ("saasyto_sender_approved", False),
        ("saasyto_runner_secret", SecretStr("short")),
        ("saasyto_instance_id", ""),
        ("saasyto_access_token", None),
        ("saasyto_enable_after", None),
    ):
        with pytest.raises(ValidationError):
            settings(**{**valid, key: value})
    # Critical: production cannot smuggle the localhost-only pilot flag.
    with pytest.raises(ValidationError):
        settings(**valid, app_env="production")


def _pilot(phone):
    cfg = _cfg()
    cfg.saasyto_local_test_enabled = True
    cfg.saasyto_local_test_phone = phone
    return cfg


def test_local_approval_refuses_mismatched_or_multiple_contacts(dispatch_system, monkeypatch):
    client, engine = dispatch_system
    csrf = login(client)
    first = _person(client, csrf, "1001")
    second = _person(client, csrf, "1002")
    _consent(client, csrf, first, "opted_in")
    _consent(client, csrf, second, "opted_in")
    monkeypatch.setattr("app.saasyto_campaigns.get_settings", lambda: _pilot(LOCAL_PHONE))
    row = create_campaign(client, csrf).json()
    base = "/v1/communication/campaigns/" + row["id"]
    ready = client.post(base + "/preparations", headers=csrf, json={
        "request_id": str(uuid.uuid4()), "simulation_only": True,
    }).json()
    assert ready["eligible_count"] == 2
    response = client.post(base + "/saasyto", headers=csrf, json={
        "preparation_id": ready["id"], "expected_eligible": 2,
        "confirm_send": True,
    })
    assert response.status_code == 409, response.text
    assert "allowlisted recipient" in response.json()["detail"]
    with Session(engine) as db:
        assert db.scalar(select(func.count(SaasytoCampaignRun.id))) == 0


def test_local_pilot_allows_one_consent_granted_recipient(dispatch_system, monkeypatch):
    client, _engine = dispatch_system
    csrf = login(client)
    person = _person(client, csrf, "1001")
    _consent(client, csrf, person, "opted_in")
    monkeypatch.setattr("app.saasyto_campaigns.get_settings", lambda: _pilot(LOCAL_PHONE))
    cid, approved = _approved(client, csrf, "Local one-contact send")
    assert approved["queued"] == 1
    sent = []
    def mock_provider(_cfg, *, phone, message):
        sent.append((phone, message))
        return Submission("accepted_unverified")
    monkeypatch.setattr("app.saasyto_campaigns.send_text", mock_provider)
    unauthorized = client.post("/internal/saasyto/dispatch", headers={
        "X-Saasyto-Runner-Token": "bad",
    })
    assert unauthorized.status_code == 401
    actual = client.post("/internal/saasyto/dispatch", headers={
        "X-Saasyto-Runner-Token": RUNNER,
    })
    assert actual.status_code == 200 and actual.json()["accepted_unverified"] == 1
    assert sent == [(LOCAL_PHONE, sent[0][1])]
    assert client.post("/internal/saasyto/dispatch", headers={
        "X-Saasyto-Runner-Token": RUNNER,
    }).json() == {}
    status = client.get("/v1/communication/campaigns/"+cid+"/saasyto").json()
    assert status["status"] == "completed"


def test_switching_local_phone_suppresses_existing_queue(dispatch_system, monkeypatch):
    client, _engine = dispatch_system
    csrf = login(client)
    person = _person(client, csrf, "1001")
    _consent(client, csrf, person, "opted_in")
    current = {"phone": LOCAL_PHONE}
    monkeypatch.setattr("app.saasyto_campaigns.get_settings",
                        lambda: _pilot(current["phone"]))
    cid, _approved_run = _approved(client, csrf, "Local send changed consent target")
    current["phone"] = "+919899009999"
    monkeypatch.setattr("app.saasyto_campaigns.send_text", lambda *_a, **_kw:
                        (_ for _ in ()).throw(AssertionError("No network send allowed")))
    outcome = client.post("/internal/saasyto/dispatch", headers={
        "X-Saasyto-Runner-Token": RUNNER,
    })
    assert outcome.status_code == 200
    assert outcome.json()["suppressed"] == 1
    assert client.get("/v1/communication/campaigns/"+cid+"/saasyto").json()[
        "suppressed_after_approval"
    ] == 1


def test_transport_rejects_non_allowlisted_phone_before_network(monkeypatch):
    cfg = SimpleNamespace(
        saasyto_delivery_enabled=True,
        saasyto_sender_approved=True,
        saasyto_instance_id="local_pilot_001",
        saasyto_access_token=SecretStr("synthetic-testing-token"),
        saasyto_local_test_enabled=True,
        saasyto_local_test_phone=LOCAL_PHONE,
    )
    monkeypatch.setattr("app.saasyto_client.httpx.Client", lambda **_:
                        (_ for _ in ()).throw(AssertionError("Network forbidden")))
    with pytest.raises(ValueError, match="not allowlisted"):
        send_text(cfg, phone="+919899001002", message="Example")


def test_local_worker_rejects_disabled_state_without_transport(monkeypatch, capsys):
    from app import saasyto_local_worker as worker
    cfg = SimpleNamespace(
        app_env="development", local_demo_login_enabled=True,
        saasyto_local_test_enabled=True, saasyto_delivery_enabled=False,
        saasyto_sender_approved=False, saasyto_runner_secret=SecretStr(RUNNER),
    )
    monkeypatch.setattr(worker, "get_settings", lambda: cfg)
    monkeypatch.setattr(worker, "build_opener", lambda *_:
                        (_ for _ in ()).throw(AssertionError("worker cannot call API")))
    assert worker.dispatch_once(port=8001) is False
    assert "disabled" in capsys.readouterr().out


def test_local_worker_uses_only_loopback_private_endpoint(monkeypatch, capsys):
    from app import saasyto_local_worker as worker
    cfg = SimpleNamespace(
        app_env="development", local_demo_login_enabled=True,
        saasyto_local_test_enabled=True, saasyto_delivery_enabled=True,
        saasyto_sender_approved=True, saasyto_runner_secret=SecretStr(RUNNER),
    )
    monkeypatch.setattr(worker, "get_settings", lambda: cfg)
    paths = []
    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self, _size):
            return b'{"accepted_unverified":1}'
    class FakeOpener:
        def open(self, request, *, timeout):
            paths.append((request.full_url, request.get_header("X-saasyto-runner-token"), timeout))
            return FakeResponse()
    monkeypatch.setattr(worker, "build_opener", lambda *_: FakeOpener())
    assert worker.dispatch_once(port=8001) is True
    assert paths == [
        ("http://127.0.0.1:8001/internal/saasyto/dispatch", RUNNER, 30),
    ]
    assert RUNNER not in capsys.readouterr().out
