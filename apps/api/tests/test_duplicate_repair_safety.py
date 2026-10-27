"""Regression checks for local duplicate repair and schema readiness.

These tests use synthetic in-memory data. The guarded repair never touches
a real PostgreSQL database during CI.
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from app import main as api_main
from app.repair_local_duplicate import validate_links, validate_records
from test_prospects import login, system

pytest_plugins = ("test_prospects",)


def _candidate(*, full_name: str, record_id=None, **overrides) -> dict:
    result = {
        "id": record_id or uuid4(), "organization_id": "test-organization",
        "full_name": full_name, "mobile_number": "+919800000001",
        "crm_stage": "inactive", "archived_at": None,
        "whatsapp_opt_in": False, "whatsapp_verified_at": None, "version": 1,
    }
    result.update(overrides)
    return result


def test_repair_selects_only_seeded_test_record_and_retains_other_identity():
    removed = _candidate(full_name="First Prospect")
    kept = _candidate(full_name="Retained Contact")
    assert validate_records([kept, removed]) == (removed, kept)
    validate_links({
        "sponsorship_rates.prospect_id": 1,
        "prospect_stage_transitions.prospect_id": 1,
    }, keeper_assignments=1)


@pytest.mark.parametrize("change", [
    {"whatsapp_verified_at": "2026-01-01"},
    {"whatsapp_opt_in": True},
    {"crm_stage": "active"},
    {"archived_at": "2026-01-01"},
    {"full_name": "Actual Sponsor"},
])
def test_repair_fails_closed_if_disposable_identity_changed(change):
    removed = _candidate(full_name="First Prospect", **change)
    kept = _candidate(full_name="Retained Contact")
    with pytest.raises(RuntimeError, match="STOP"):
        validate_records([removed, kept])


@pytest.mark.parametrize("links,assignments", [
    ({}, 1),
    ({"sponsorship_rates.prospect_id": 1}, 1),
    ({"sponsorship_rates.prospect_id": 2,
      "prospect_stage_transitions.prospect_id": 1}, 1),
    ({"sponsorship_rates.prospect_id": 1,
      "prospect_stage_transitions.prospect_id": 1,
      "manual_collections.prospect_id": 1}, 1),
    ({"sponsorship_rates.prospect_id": 1,
      "prospect_stage_transitions.prospect_id": 1}, 0),
])
def test_repair_refuses_any_unexpected_links(links, assignments):
    with pytest.raises(RuntimeError, match="STOP"):
        validate_links(links, assignments)


def test_db_unique_constraint_and_api_block_duplicate_and_archived_phones(system):
    client, _ = system
    csrf = login(client)
    first = client.post("/v1/prospects", json={
        "full_name": "Seed Sponsor", "mobile_number": "+919000000001",
    }, headers=csrf)
    assert first.status_code == 201, first.text
    duplicate = client.post("/v1/prospects", json={
        "full_name": "Completely Different Name",
        "mobile_number": "+91 9000000001",
    }, headers=csrf)
    assert duplicate.status_code == 409, duplicate.text
    archived = client.delete(
        "/v1/prospects/" + first.json()["id"],
        headers={**csrf, "If-Match": "1"},
    )
    assert archived.status_code == 204, archived.text
    repeat = client.post("/v1/prospects", json={
        "full_name": "Another Name", "mobile_number": "+919000000001",
    }, headers=csrf)
    assert repeat.status_code == 409, repeat.text


def test_development_readiness_rejects_old_schema(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
            conn.execute(text(
                "INSERT INTO alembic_version (version_num) VALUES ('0020_saasyto_campaigns')"
            ))
        monkeypatch.setattr(api_main, "get_engine", lambda: engine)
        monkeypatch.setattr(
            api_main, "get_settings",
            lambda: SimpleNamespace(app_env="development"),
        )
        monkeypatch.setattr(
            api_main, "_expected_migration_heads",
            lambda: {"0023_stage_system_identity"},
        )
        response = api_main.readiness()
        assert response.status_code == 503
        assert b"postgresql" not in response.body.lower()
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE alembic_version "
                "SET version_num = '0023_stage_system_identity'"
            ))
        assert api_main.readiness().status_code == 200
    finally:
        engine.dispose()


def test_development_readiness_rejects_missing_migration_table(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        monkeypatch.setattr(api_main, "get_engine", lambda: engine)
        monkeypatch.setattr(
            api_main, "get_settings",
            lambda: SimpleNamespace(app_env="development"),
        )
        assert api_main.readiness().status_code == 503
    finally:
        engine.dispose()
