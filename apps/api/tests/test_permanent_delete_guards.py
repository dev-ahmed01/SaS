"""Deletion must refuse historical assignments and permit only unused people."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Promoter, Prospect, SponsorshipRate

pytest_plugins = ("test_prospects",)


def session_token(client):
    r = client.post("/v1/auth/login", json={
        "email": "office@foundation.org",
        "password": "synthetic-long-admin-password",
    })
    assert r.status_code == 200
    return {"X-CSRF-Token": client.get("/v1/auth/session").json()["csrf_token"]}


def test_unused_prospect_delete_and_confirmation(system):
    client, engine = system
    csrf = session_token(client)
    r = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Test Unused", "mobile_number": "+919899999991",
    })
    assert r.status_code == 201
    record = r.json()
    url = "/v1/prospects/" + record["id"] + "/permanent-delete"
    body = {"version": record["version"], "confirmation": "DELETE"}
    assert client.post(url, headers=csrf, json={
        **body, "confirmation": "YES",
    }).status_code == 422
    assert client.post(url, headers=csrf, json=body).status_code == 204
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Prospect)) == 0


def test_assigned_promoter_cannot_be_deleted(system):
    client, engine = system
    csrf = session_token(client)
    promoter = client.post("/v1/promoters", headers=csrf, json={
        "full_name": "Active Promoter", "mobile_number": "+919899999992",
    }).json()
    person = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Assigned Person", "mobile_number": "+919899999993",
    }).json()
    assigned = client.put(
        "/v1/promoters/" + promoter["id"] + "/sponsors/" + person["id"],
        headers={**csrf, "If-Match": str(person["version"])},
    )
    assert assigned.status_code == 200, assigned.text
    r = client.post(
        "/v1/promoters/" + promoter["id"] + "/permanent-delete",
        headers=csrf,
        json={"version": assigned.json()["version"], "confirmation": "DELETE"},
    )
    assert r.status_code == 409, r.text
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Promoter)) == 1


def test_nontrivial_sponsorship_history_blocks_prospect_deletion(system):
    client, engine = system
    csrf = session_token(client)
    created = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "History Contact", "mobile_number": "+919899999994",
    })
    assert created.status_code == 201
    person = created.json()
    with Session(engine) as db:
        rate = db.scalars(select(SponsorshipRate)).one()
        db.add(SponsorshipRate(
            organization_id=rate.organization_id,
            prospect_id=rate.prospect_id,
            effective_month=rate.effective_month.replace(year=rate.effective_month.year + 1),
            amount_paise=rate.amount_paise,
        ))
        db.commit()
    result = client.post(
        "/v1/prospects/" + person["id"] + "/permanent-delete",
        headers=csrf,
        json={"version": person["version"], "confirmation": "DELETE"},
    )
    assert result.status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Prospect)) == 1
        assert db.scalar(select(func.count()).select_from(SponsorshipRate)) == 2


def test_unused_promoter_may_be_permanently_deleted(system):
    client, engine = system
    csrf = session_token(client)
    created = client.post("/v1/promoters", headers=csrf, json={
        "full_name": "Unused Promoter", "mobile_number": "+919899999995",
    })
    assert created.status_code == 201
    record = created.json()
    result = client.post(
        "/v1/promoters/" + record["id"] + "/permanent-delete",
        headers=csrf,
        json={"version": record["version"], "confirmation": "DELETE"},
    )
    assert result.status_code == 204
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Promoter)) == 0
