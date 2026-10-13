"""Phase 05 Promoters: Admin authorization, cross-tenant safety and assignment history."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.bootstrap_admin import provision_admin
from app.main import app
from app.models import (
    AdminUser,
    AuditEvent,
    Base,
    Organization,
    OrganizationSettings,
    Promoter,
    PromoterAssignment,
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
            db, email="office@foundation.org", password="synthetic-long-admin-password",
            organization_name="Emlen Foundation",
            amount_paise=50000,
        )
    monkeypatch.setattr("app.auth.get_engine", lambda: engine)
    monkeypatch.setattr(
        "app.auth.get_settings",
        lambda: SimpleNamespace(
            auth_secret="synthetic-auth-secret-more-than-thirty-two-characters",
            app_env="test",
        ),
    )
    monkeypatch.setattr(
        "app.prospects.get_settings",
        lambda: SimpleNamespace(upi_match_secret="synthetic-independent-upi-hmac-key-for-tests"),
    )
    with TestClient(app) as client:
        yield client, engine
    engine.dispose()


def login(client):
    response = client.post(
        "/v1/auth/login",
        json={"email": "office@foundation.org", "password": "synthetic-long-admin-password"},
    )
    assert response.status_code == 200
    return {"X-CSRF-Token": client.get("/v1/auth/session").json()["csrf_token"]}


def add_prospect(client, csrf):
    return client.post(
        "/v1/prospects", headers=csrf,
        json={
            "full_name": "Synthetic Sponsor",
            "mobile_number": "+919876543210",
            "area_city": "Bengaluru",
        },
    )


PROMOTER={
    "full_name":"Bilal Ahmed",
    "mobile_number":"+919111122233",
    "area_city":"Bengaluru",
    "whatsapp_opt_in":False,
}


def add(client,csrf,**changes):
    return client.post("/v1/promoters",headers=csrf,json={**PROMOTER,**changes})


def test_login_csrf_validation_duplicate_and_initial_state(system):
    client, db_engine=system
    assert client.get("/v1/promoters").status_code==401
    assert client.post("/v1/promoters",json=PROMOTER).status_code==401
    csrf=login(client)
    assert client.post("/v1/promoters",json=PROMOTER).status_code==403
    response=add(client,csrf)
    assert response.status_code==201,response.text
    promoter=response.json()
    assert promoter["is_active"] is True
    assert promoter["sponsor_count"]==0
    assert promoter["whatsapp_opt_in"] is False
    assert promoter["version"]==1
    assert add(client,csrf).status_code==409
    assert add(client,csrf,mobile_number="broken").status_code==422
    assert add(client,csrf,unknown_field="bad").status_code==422
    assert client.patch(
        "/v1/promoters/"+promoter["id"],headers=csrf,
        json={"version":1,"sponsor_count":200},
    ).status_code==422
    with Session(db_engine) as db:
        events=db.scalars(select(AuditEvent).where(
            AuditEvent.action=="promoter.created"
        )).all()
        assert len(events)==1
        assert "Bilal" not in str(events[0].after_data)


def test_search_active_deactivate_reactivate_and_version(system):
    client,_=system
    csrf=login(client)
    first=add(client,csrf).json()
    add(client,csrf,full_name="Hamza Siddiqui",mobile_number="+919222233344")
    assert client.get("/v1/promoters?active=true").json()["total"]==2
    assert client.get("/v1/promoters?q=hamza").json()["total"]==1
    assert client.get("/v1/promoters?q=%25").json()["total"]==0
    assert client.get("/v1/promoters?limit=200").status_code==422
    url="/v1/promoters/"+first["id"]
    changed=client.patch(url,headers=csrf,json={
        "version":1,"is_active":False,
    })
    assert changed.status_code==200,changed.text
    assert changed.json()["version"]==2
    assert client.get("/v1/promoters?active=true").json()["total"]==1
    assert client.patch(url,headers=csrf,json={
        "version":1,"full_name":"Stale name",
    }).status_code==409
    updated=client.patch(url,headers=csrf,json={
        "version":2,"full_name":"Bilal A. Ahmed","is_active":True,
    })
    assert updated.status_code==200
    assert updated.json()["is_active"] is True
    assert updated.json()["full_name"]=="Bilal A. Ahmed"


def test_assign_reassign_history_stale_protection_and_deactivation_gate(system):
    client,engine=system
    csrf=login(client)
    p1=add(client,csrf).json()
    p2=add(client,csrf,full_name="Zaid Khan",mobile_number="+919444455566").json()
    prospect=add_prospect(client,csrf).json()
    a="/v1/promoters/"+p1["id"]+"/sponsors/"+prospect["id"]
    b="/v1/promoters/"+p2["id"]+"/sponsors/"+prospect["id"]
    assert client.put(a,headers=csrf).status_code==428
    assigned=client.put(a,headers={**csrf,"If-Match":"1"})
    assert assigned.status_code==200,assigned.text
    assert assigned.json()["sponsor_count"]==1
    links=client.get("/v1/promoters/"+p1["id"]+"/sponsors")
    assert links.status_code==200
    assert links.json()["items"][0]["prospect_id"]==prospect["id"]
    assert links.json()["items"][0]["prospect_version"]==2
    assert client.patch(
        "/v1/promoters/"+p1["id"],headers=csrf,
        json={"version":2,"is_active":False},
    ).status_code==409
    assert client.put(b,headers={**csrf,"If-Match":"1"}).status_code==409
    switched=client.put(b,headers={**csrf,"If-Match":"2"})
    assert switched.status_code==200,switched.text
    assert client.get("/v1/promoters/"+p1["id"]+"/sponsors").json()["total"]==0
    assert client.get("/v1/promoters/"+p2["id"]+"/sponsors").json()["total"]==1
    assert client.delete(b,headers={**csrf,"If-Match":"3"}).status_code==204
    assert client.get("/v1/promoters/"+p2["id"]+"/sponsors").json()["total"]==0
    with Session(engine) as db:
        history=db.scalars(select(PromoterAssignment).order_by(
            PromoterAssignment.assigned_at,PromoterAssignment.id,
        )).all()
        assert len(history)==2
        assert all(x.ended_at is not None for x in history)
        assert db.scalar(select(func.count()).select_from(Promoter))==2


def test_rejects_cross_org_promoter_and_prospect_access(system):
    client,engine=system
    csrf=login(client)
    main=add(client,csrf).json()
    sponsor=add_prospect(client,csrf).json()
    with Session(engine) as db:
        org=Organization(name="Other Charity")
        db.add(org)
        db.flush()
        db.add(AdminUser(
            organization_id=org.id,email="otherpromoter@foundation.org",
            password_hash=hash_password("synthetic-secondary-password"),is_active=True,
        ))
        db.add(OrganizationSettings(
            organization_id=org.id,currency_code="INR",timezone="Asia/Kolkata",
            default_contribution_paise=50000,sponsor_reminder_day=5,
            promoter_reminder_day=20,inactivity_months=2,automation_enabled=False,
        ))
        db.commit()
    assert client.post("/v1/auth/login",json={
        "email":"otherpromoter@foundation.org","password":"synthetic-secondary-password",
    }).status_code==200
    csrf2={"X-CSRF-Token":client.get("/v1/auth/session").json()["csrf_token"]}
    assert client.get("/v1/promoters").json()["total"]==0
    assert client.get("/v1/promoters/"+main["id"]).status_code==404
    assert client.put(
        "/v1/promoters/"+main["id"]+"/sponsors/"+sponsor["id"],
        headers={**csrf2,"If-Match":"1"},
    ).status_code==404
    other=add(client,csrf2,full_name="Other Coordinator",
              mobile_number="+919333344455").json()
    assert client.put(
        "/v1/promoters/"+other["id"]+"/sponsors/"+sponsor["id"],
        headers={**csrf2,"If-Match":"1"},
    ).status_code==404
    assert client.get("/v1/promoters/"+other["id"]).status_code==200


def test_archived_sponsors_cannot_be_assigned(system):
    client,_=system
    csrf=login(client)
    promoter=add(client,csrf).json()
    prospect=add_prospect(client,csrf).json()
    assert client.delete("/v1/prospects/"+prospect["id"],
                         headers={**csrf,"If-Match":"1"}).status_code==204
    assert client.put(
        "/v1/promoters/"+promoter["id"]+"/sponsors/"+prospect["id"],
        headers={**csrf,"If-Match":"2"},
    ).status_code==404


def test_location_is_optional_for_new_promoter(system):
    client, _ = system
    csrf = login(client)
    response = client.post("/v1/promoters", headers=csrf, json={
        "full_name": "No Location Promoter",
        "mobile_number": "+919111122234",
    })
    assert response.status_code == 201, response.text
    assert response.json()["area_city"] == ""
