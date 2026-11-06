"""Synthetic role-access acceptance tests; never provision real users."""
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.bootstrap_admin import provision_admin
from app.main import app
from app.models import Base


@pytest.fixture
def system(monkeypatch):
    engine=create_engine("sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        provision_admin(
            db,email="owner@foundation.org",
            password="synthetic-owner-password-long",
            organization_name="Synthetic Foundation",amount_paise=50000,
        )
    monkeypatch.setattr("app.auth.get_engine",lambda:engine)
    monkeypatch.setattr("app.auth.get_settings",lambda:SimpleNamespace(
        auth_secret="synthetic-role-test-secret-at-least-32-characters",
        app_env="test",
    ))
    with TestClient(app) as client:
        yield client
    engine.dispose()


def login(client,email,password):
    assert client.post("/v1/auth/login",json={
        "email":email,"password":password,
    }).status_code==200
    return {"X-CSRF-Token":client.get("/v1/auth/session").json()["csrf_token"]}


def test_owner_provisions_staff_with_scoped_finance_and_campaign_permissions(system):
    client=system
    owner=login(client,"owner@foundation.org","synthetic-owner-password-long")
    assert client.get("/v1/auth/session").json()["role"]=="owner"
    credentials=[
        ("crm","crm@foundation.org"),("finance","finance@foundation.org"),
        ("messaging","messages@foundation.org"),("viewer","viewer@foundation.org"),
    ]
    for role,email in credentials:
        result=client.post("/v1/auth/users",headers=owner,json={
            "email":email,"password":"synthetic-staff-password-123",
            "role":role,
        })
        assert result.status_code==201,result.text
        assert result.json()["role"]==role
    assert len(client.get("/v1/auth/users").json())==5
    assert client.post("/v1/auth/users",headers=owner,json={
        "email":"crm@foundation.org",
        "password":"synthetic-staff-password-123","role":"crm",
    }).status_code==409

    for role,email in credentials:
        csrf=login(client,email,"synthetic-staff-password-123")
        assert client.get("/v1/auth/session").json()["role"]==role
        assert client.get("/v1/dashboard/overview").status_code==200
        assert client.get("/v1/prospects").status_code==200
        assert client.get("/v1/auth/users").status_code==403
        assert client.patch("/v1/settings",headers=csrf,json={}).status_code==403
        if role=="crm":
            assert client.post("/v1/payouts/quick",headers=csrf,json={}).status_code==403
            assert client.post("/v1/communication/campaigns",headers=csrf,json={}).status_code==403
        elif role=="finance":
            assert client.post("/v1/prospects",headers=csrf,json={}).status_code==403
            assert client.post("/v1/communication/campaigns",headers=csrf,json={}).status_code==403
        elif role=="messaging":
            assert client.post("/v1/collections",headers=csrf,json={}).status_code==403
            assert client.post("/v1/payouts/quick",headers=csrf,json={}).status_code==403
        elif role=="viewer":
            assert client.post("/v1/prospects",headers=csrf,json={}).status_code==403
            assert client.post("/v1/collections",headers=csrf,json={}).status_code==403

    owner=login(client,"owner@foundation.org","synthetic-owner-password-long")
    staff=next(row for row in client.get("/v1/auth/users").json()
               if row["email"]=="crm@foundation.org")
    assert client.patch("/v1/auth/users/"+staff["id"],headers=owner,json={
        "role":"viewer","is_active":False,
    }).status_code==200
    assert client.post("/v1/auth/login",json={
        "email":"crm@foundation.org","password":"synthetic-staff-password-123",
    }).status_code==401
    assert client.patch("/v1/auth/users/"+str(uuid.uuid4()),headers=owner,json={
        "role":"viewer","is_active":True,
    }).status_code==404
