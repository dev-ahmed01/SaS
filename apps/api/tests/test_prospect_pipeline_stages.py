"""Configurable Prospect pipeline stages: tenant boundaries and financial isolation."""
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.bootstrap_admin import provision_admin
from app.main import app
from app.models import (
    AdminUser,
    Base,
    Organization,
    OrganizationSettings,
    Prospect,
    ProspectStageDefinition,
)
from app.security import hash_password


@pytest.fixture
def system(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        provision_admin(
            db, email="foundation@example.org", password="synthetic-secure-login",
            organization_name="Synthetic Foundation", amount_paise=25000,
        )
    monkeypatch.setattr("app.auth.get_engine", lambda: engine)
    monkeypatch.setattr(
        "app.auth.get_settings",
        lambda: SimpleNamespace(
            auth_secret="synthetic-test-secret-longer-than-32-characters",
            app_env="test",
        ),
    )
    monkeypatch.setattr(
        "app.prospects.get_settings",
        lambda: SimpleNamespace(
            upi_match_secret="synthetic-upi-match-secret-longer-than-32-characters"
        ),
    )
    with TestClient(app) as client:
        yield client, engine
    engine.dispose()


def login(client, email="foundation@example.org", password="synthetic-secure-login"):
    assert client.post("/v1/auth/login", json={
        "email": email, "password": password,
    }).status_code == 200
    return {"X-CSRF-Token": client.get("/v1/auth/session").json()["csrf_token"]}


def test_stages_are_configurable_and_do_not_exist_until_created(system):
    client, engine = system
    assert client.get("/v1/prospect-stages").status_code == 401
    csrf = login(client)
    assert client.get("/v1/prospect-stages").json() == []
    assert client.post("/v1/prospect-stages", json={"name": "New"}).status_code == 403
    created = client.post("/v1/prospect-stages", headers=csrf, json={
        "name": " Contacted ", "description": " First outreach ",
        "color": "#0F766E", "sort_order": 3,
    })
    assert created.status_code == 201, created.text
    stage = created.json()
    assert stage["name"] == "Contacted"
    assert stage["description"] == "First outreach"
    assert stage["color"] == "#0f766e"
    assert stage["prospect_count"] == 0
    duplicate = client.post("/v1/prospect-stages", headers=csrf, json={
        "name": "contacted",
    })
    assert duplicate.status_code == 409
    invalid_color = client.post("/v1/prospect-stages", headers=csrf, json={
        "name": "Broken", "color": "not-a-color",
    })
    assert invalid_color.status_code == 422
    updated = client.patch("/v1/prospect-stages/"+stage["id"], headers=csrf, json={
        "version": stage["version"], "name": "Interested",
        "color": "#2563eb", "sort_order": 1,
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert updated.json()["name"] == "Interested"
    assert client.patch("/v1/prospect-stages/"+stage["id"], headers=csrf, json={
        "version": 1, "name": "Stale",
    }).status_code == 409
    assert client.delete(
        "/v1/prospect-stages/"+stage["id"],
        headers={**csrf, "If-Match": "1"},
    ).status_code == 409
    assert client.delete(
        "/v1/prospect-stages/"+stage["id"], headers=csrf,
    ).status_code == 428
    assert client.delete(
        "/v1/prospect-stages/"+stage["id"],
        headers={**csrf, "If-Match": "2"},
    ).status_code == 204
    assert client.get("/v1/prospect-stages").json() == []
    with Session(engine) as db:
        assert not db.scalars(select(ProspectStageDefinition)).all()


def test_assigned_stages_survive_edits_and_cannot_be_deleted_until_unassigned(system):
    client, engine = system
    csrf = login(client)
    stage = client.post("/v1/prospect-stages", headers=csrf, json={
        "name": "Ready for call", "color": "#7c3aed",
    }).json()
    created = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Stage Tested", "mobile_number": "+919766543210",
        "pipeline_stage_id": stage["id"],
    })
    assert created.status_code == 201, created.text
    person = created.json()
    assert person["pipeline_stage_name"] == "Ready for call"
    assert person["pipeline_stage_color"] == "#7c3aed"
    assert person["lifecycle_status"] == "new"
    assert person["crm_stage"] == "active"
    assert client.get("/v1/prospect-stages").json()[0]["prospect_count"] == 1
    assert client.delete(
        "/v1/prospect-stages/"+stage["id"],
        headers={**csrf, "If-Match": str(stage["version"])},
    ).status_code == 409
    change = client.patch("/v1/prospect-stages/"+stage["id"], headers=csrf, json={
        "version": 1, "name": "Follow-up", "color": "#ea580c",
    })
    assert change.status_code == 200, change.text
    loaded = client.get("/v1/prospects/"+person["id"]).json()
    assert loaded["pipeline_stage_name"] == "Follow-up"
    assert loaded["pipeline_stage_color"] == "#ea580c"
    cleared = client.patch("/v1/prospects/"+person["id"], headers=csrf, json={
        "version": loaded["version"], "pipeline_stage_id": None,
    })
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["pipeline_stage_name"] is None
    assert cleared.json()["lifecycle_status"] == "new"
    assert client.delete(
        "/v1/prospect-stages/"+stage["id"],
        headers={**csrf, "If-Match": str(change.json()["version"])},
    ).status_code == 204
    with Session(engine) as db:
        item = db.get(Prospect, uuid.UUID(person["id"]))
        assert item.monthly_contribution_paise == 25000


def test_stage_assignment_never_crosses_tenant_boundary(system):
    client, engine = system
    csrf = login(client)
    stage = client.post("/v1/prospect-stages", headers=csrf, json={
        "name": "Foundation A stage",
    }).json()
    with Session(engine) as db:
        org = Organization(name="Other foundation")
        db.add(org)
        db.flush()
        db.add(AdminUser(
            organization_id=org.id, email="other@example.org",
            password_hash=hash_password("synthetic-other-password"), is_active=True,
        ))
        db.add(OrganizationSettings(
            organization_id=org.id, currency_code="INR",
            timezone="Asia/Kolkata", default_contribution_paise=25000,
            sponsor_reminder_day=5, promoter_reminder_day=20,
            inactivity_months=2, automation_enabled=False,
        ))
        db.commit()
    other = login(client, "other@example.org", "synthetic-other-password")
    assert client.get("/v1/prospect-stages").json() == []
    assert client.patch("/v1/prospect-stages/"+stage["id"], headers=other, json={
        "version": 1, "name": "Hijacked",
    }).status_code == 404
    assert client.delete(
        "/v1/prospect-stages/"+stage["id"],
        headers={**other, "If-Match": "1"},
    ).status_code == 404
    cross = client.post("/v1/prospects", headers=other, json={
        "full_name": "Cross Tenant", "mobile_number": "+919755553333",
        "pipeline_stage_id": stage["id"],
    })
    assert cross.status_code == 422
