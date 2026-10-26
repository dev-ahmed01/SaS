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
    })
    assert created.status_code == 201, created.text
    person = created.json()
    assert person["pipeline_stage_name"] == "New Inquiry"
    moved = client.patch("/v1/prospects/"+person["id"], headers=csrf, json={
        "version": person["version"], "pipeline_stage_id": stage["id"],
    })
    assert moved.status_code == 200, moved.text
    person = moved.json()
    assert person["pipeline_stage_name"] == "Ready for call"
    assert person["pipeline_stage_color"] == "#7c3aed"
    assert person["lifecycle_status"] == "new"
    assert person["crm_stage"] == "inactive"
    assert next(
        row["prospect_count"] for row in client.get("/v1/prospect-stages").json()
        if row["id"] == stage["id"]
    ) == 1
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


def test_registration_stage_keeps_same_uuid_after_name_change_and_bulk_import(system):
    client, engine = system
    csrf = login(client)
    first = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Initial Registration",
        "mobile_number": "+919711110101",
    })
    assert first.status_code == 201, first.text
    initial = first.json()
    default_id = initial["pipeline_stage_id"]
    stages = client.get("/v1/prospect-stages").json()
    selected = next(stage for stage in stages if stage["id"] == default_id)
    assert selected["is_registration_default"] is True
    renamed = client.patch("/v1/prospect-stages/" + default_id, headers=csrf, json={
        "version": selected["version"], "name": "New Donor Enquiry",
    })
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["is_registration_default"] is True
    second = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "After Renaming",
        "mobile_number": "+919711110102",
    })
    assert second.status_code == 201, second.text
    assert second.json()["pipeline_stage_id"] == default_id
    assert second.json()["pipeline_stage_name"] == "New Donor Enquiry"

    import_id = str(uuid.uuid4())
    source = {
        "batch_id": import_id,
        "rows": [{"full_name": "Bulk After Rename",
                  "mobile_number": "+919711110103"}],
    }
    preview = client.post("/v1/prospects/bulk", headers=csrf, json=source)
    assert preview.status_code == 200, preview.text
    preview_data = preview.json()
    committed = client.post("/v1/prospects/bulk", headers=csrf, json={
        **source, "commit": True,
        "expected_month": preview_data["default_start_month"],
        "expected_default_amount_paise": preview_data["default_amount_paise"],
    })
    assert committed.status_code == 200, committed.text
    bulk_id = committed.json()["rows"][0]["prospect_id"]
    bulk = client.get("/v1/prospects/" + bulk_id).json()
    assert bulk["pipeline_stage_id"] == default_id
    assert bulk["crm_stage"] == "inactive"
    assert len(client.get("/v1/prospect-stages").json()) == 1

    # Protect the registration identity even when the stage has no assignments.
    alternative = client.post("/v1/prospect-stages", headers=csrf, json={
        "name": "Follow-up", "color": "#155e75",
    }).json()
    for person_id in (initial["id"], second.json()["id"], bulk_id):
        current = client.get("/v1/prospects/" + person_id).json()
        moved = client.patch("/v1/prospects/" + person_id, headers=csrf, json={
            "version": current["version"], "pipeline_stage_id": alternative["id"],
        })
        assert moved.status_code == 200, moved.text
    cannot_delete = client.delete(
        "/v1/prospect-stages/" + default_id,
        headers={**csrf, "If-Match": str(renamed.json()["version"])},
    )
    assert cannot_delete.status_code == 409
    with Session(engine) as db:
        default = db.get(ProspectStageDefinition, uuid.UUID(default_id))
        assert default.system_key == "registration_new_inquiry"


def test_legacy_renamed_default_with_original_description_is_reused(system):
    client, engine = system
    csrf = login(client)
    candidate = client.post("/v1/prospect-stages", headers=csrf, json={
        "name": "Renamed First Contact",
        "description": "Awaiting first documented follow-up",
    })
    assert candidate.status_code == 201, candidate.text
    original_id = candidate.json()["id"]
    created = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Legacy Default Test", "mobile_number": "+919711110105",
    })
    assert created.status_code == 201, created.text
    assert created.json()["pipeline_stage_id"] == original_id
    with Session(engine) as db:
        stage = db.get(ProspectStageDefinition, uuid.UUID(original_id))
        assert stage.system_key == "registration_new_inquiry"
