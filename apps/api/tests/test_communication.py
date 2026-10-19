"""Communication contract: consent, tenant isolation, IST and no surprise sending."""
import uuid
from datetime import timedelta
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
    Base,
    CommunicationCampaign,
    CommunicationConsentEvent,
    CommunicationPreparation,
    CommunicationRecipientSnapshot,
    CommunicationRule,
    CommunicationTemplate,
    MessageDispatch,
    Organization,
    Prospect,
)
from app.security import hash_password, utc_now


@pytest.fixture
def system(monkeypatch):
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
    monkeypatch.setattr(
        "app.auth.get_settings",
        lambda: SimpleNamespace(
            auth_secret="synthetic-secure-auth-key-longer-than-thirty-two",
            app_env="test",
        ),
    )
    monkeypatch.setattr(
        "app.prospects.get_settings",
        lambda: SimpleNamespace(
            upi_match_secret="synthetic-unique-hmac-secret-for-communication-test"
        ),
    )
    with TestClient(app) as client:
        yield client, engine
    engine.dispose()


def login(client, email="office@foundation.org",
          password="synthetic-long-admin-password"):
    response = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": client.get("/v1/auth/session").json()["csrf_token"]}


def create_template(client, csrf, name="Foundation update", **overrides):
    payload = {
        "name": name, "channel": "whatsapp", "category": "update",
        "body": "Hello {{name}}, we have a Foundation update.",
    }
    payload.update(overrides)
    return client.post("/v1/communication/templates", headers=csrf, json=payload)


def create_campaign(client, csrf, **overrides):
    payload = {
        "request_id": str(uuid.uuid4()),
        "title": "Foundation announcement", "channel": "whatsapp",
        "audience": "prospects", "segment": "active", "category": "update",
        "body": "Hello {{name}}, this is an update.",
    }
    payload.update(overrides)
    return client.post("/v1/communication/campaigns", headers=csrf, json=payload)


def test_communication_requires_auth_and_csrf(system):
    client, _ = system
    assert client.get("/v1/communication/clock").status_code == 401
    assert client.get("/v1/communication/templates").status_code == 401
    assert client.get("/v1/communication/audience").status_code == 401
    assert client.post("/v1/communication/templates", json={}).status_code == 401
    csrf = login(client)
    assert create_template(client, {}).status_code == 403
    assert client.post("/v1/communication/campaigns", json={}).status_code == 403
    assert client.post("/v1/communication/rules", json={}).status_code == 403
    clock = client.get("/v1/communication/clock")
    assert clock.status_code == 200
    assert clock.headers["cache-control"] == "no-store"
    assert clock.json()["timezone"] == "Asia/Kolkata"
    assert clock.json()["now_ist"].endswith("+05:30")
    assert client.post("/v1/communication/send", headers=csrf, json={}).status_code == 404


def test_audience_preview_never_infers_consent_or_sent_status(system):
    client, engine = system
    csrf = login(client)
    def create(name, phone, consent):
        result = client.post("/v1/prospects", headers=csrf, json={
            "full_name": name, "mobile_number": phone,
            "whatsapp_opt_in": consent, "area_city": "Bengaluru",
            "monthly_contribution_paise": 25000,
            "email": "contact@example.org",
        })
        assert result.status_code == 201, result.text
        return result.json()
    consenting = create("Consenting Candidate", "+919877661101", True)
    create("No Consent Candidate", "+919877661102", False)
    count = client.get("/v1/communication/audience?audience=prospects&segment=all"
                       "&channel=whatsapp").json()
    assert count["candidate_count"] == 2
    assert count["eligible_count"] == 1
    assert count["suppressed_count"] == 1
    assert count["sample_names"] == ["Consenting Candidate"]
    assert count["channel_ready"] is False
    assert client.get("/v1/communication/audience?channel=email").json()[
        "eligible_count"
    ] == 0
    unpaid = client.get("/v1/communication/audience?segment=unpaid").json()
    assert unpaid["candidate_count"] == 2
    assert unpaid["eligible_count"] == 1
    with Session(engine) as db:
        sponsor = db.get(Prospect, uuid.UUID(consenting["id"]))
        assert sponsor.monthly_contribution_paise == 25000
        assert db.scalar(select(func.count(MessageDispatch.id))) == 0


def test_template_crud_and_rule_dependencies_are_protected(system):
    client, engine = system
    csrf = login(client)
    created = create_template(client, csrf)
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["name"] == "Foundation update"
    assert create_template(client, csrf, name="FOUNDATION UPDATE").status_code == 409
    assert create_template(client, csrf, name="Other", channel="email").status_code == 422
    changed = client.patch("/v1/communication/templates/"+row["id"], headers=csrf, json={
        "version": 1, "name": "Sponsor update", "channel": "whatsapp",
        "category": "update", "subject": None, "body": "Welcome, {{name}}!",
        "provider_template_id": "whatsapp-approved-copy-001",
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == 2
    assert client.patch("/v1/communication/templates/"+row["id"], headers=csrf,
        json={"version": 1, "name": "Conflict", "channel": "whatsapp",
              "category": "other", "body": "Invalid stale edit"}).status_code == 409
    invalid = client.post("/v1/communication/rules", headers=csrf, json={
        "name": "Unpaid sponsor follow-up", "template_id": row["id"],
        "trigger_kind": "monthly_sponsor",
        "audience": "both", "segment": "unpaid",
    })
    assert invalid.status_code == 422
    rule = client.post("/v1/communication/rules", headers=csrf, json={
        "name": "Unpaid sponsor follow-up", "template_id": row["id"],
        "trigger_kind": "monthly_sponsor", "audience": "prospects",
        "segment": "unpaid",
    })
    assert rule.status_code == 201, rule.text
    assert rule.json()["active"] is False
    assert client.delete("/v1/communication/templates/"+row["id"]+"?version=2",
        headers=csrf).status_code == 409
    assert client.delete("/v1/communication/rules/"+rule.json()["id"],
        headers=csrf).status_code == 204
    assert client.delete("/v1/communication/templates/"+row["id"]+"?version=2",
        headers=csrf).status_code == 204
    assert client.get("/v1/communication/templates").json() == []
    with Session(engine) as db:
        assert db.scalar(select(func.count(CommunicationTemplate.id))) == 1
        assert db.scalar(select(func.count(CommunicationRule.id))) == 0


def test_campaign_saves_draft_or_ist_plan_without_dispatch(system):
    client, engine = system
    csrf = login(client)
    draft = create_campaign(client, csrf)
    assert draft.status_code == 201, draft.text
    row = draft.json()
    assert row["status"] == "draft"
    assert row["eligible_snapshot"] == 0
    assert row["planned_for"] is None
    when = (utc_now()+timedelta(days=3)).isoformat()
    planned = create_campaign(client, csrf, planned_for=when)
    assert planned.status_code == 201, planned.text
    assert planned.json()["status"] == "scheduled"
    assert planned.json()["planned_for"] is not None
    assert create_campaign(client, csrf, segment="inactive", category="reminder").status_code == 422
    assert create_campaign(client, csrf, planned_for="2026-10-30T12:00:00").status_code == 422
    original_id = str(uuid.uuid4())
    assert create_campaign(client, csrf, request_id=original_id).status_code == 201
    assert create_campaign(client, csrf, request_id=original_id).status_code == 200
    assert create_campaign(client, csrf, request_id=original_id,
                           title="Different").status_code == 409
    assert client.post(
        "/v1/communication/campaigns/"+planned.json()["id"]+"/cancel",
        headers=csrf, json={},
    ).json()["status"] == "cancelled"
    with Session(engine) as db:
        assert db.scalar(select(func.count(MessageDispatch.id))) == 0
        assert db.scalar(select(func.count(CommunicationCampaign.id))) == 3


def test_cross_tenant_campaign_and_template_are_not_visible(system):
    client, engine = system
    csrf = login(client)
    saved = create_template(client, csrf).json()
    created = create_campaign(client, csrf).json()
    with Session(engine) as db:
        other = Organization(name="Other foundation")
        db.add(other)
        db.flush()
        db.add(AdminUser(
            organization_id=other.id, email="other@foundation.org",
            password_hash=hash_password("synthetic-other-password"),
            is_active=True,
        ))
        db.commit()
    second = login(client, "other@foundation.org", "synthetic-other-password")
    assert client.get("/v1/communication/templates").json() == []
    assert client.get("/v1/communication/campaigns").json() == []
    assert client.patch("/v1/communication/templates/"+saved["id"], headers=second,
        json={"version": 1,"name": "Copied", "channel": "whatsapp",
              "category": "update","body":"Changed body"}).status_code == 404
    assert client.post("/v1/communication/rules", headers=second, json={
        "name": "Not authorized", "template_id": saved["id"],
        "trigger_kind": "manual", "audience": "both", "segment": "all",
    }).status_code == 404
    assert client.post(
        "/v1/communication/campaigns/"+created["id"]+"/cancel",
        headers=second, json={},
    ).status_code == 404


def test_preflight_requires_explicit_consent_and_never_dispatches(system):
    client, engine = system
    csrf = login(client)
    person = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Test Recipient",
        "mobile_number": "+919876540111",
        "email": "consented@example.org",
        "area_city": "Bengaluru",
        "whatsapp_opt_in": True,
        "monthly_contribution_paise": 25000,
    })
    assert person.status_code == 201, person.text
    identifier = person.json()["id"]
    campaign = create_campaign(client, csrf)
    assert campaign.status_code == 201, campaign.text
    campaign_id = campaign.json()["id"]
    url = "/v1/communication/campaigns/" + campaign_id + "/preparations"
    assert client.post(url, json={}).status_code == 403
    assert client.post(url, headers=csrf, json={
        "request_id": str(uuid.uuid4()), "simulation_only": False,
    }).status_code == 422

    identifier1 = str(uuid.uuid4())
    request = {"request_id": identifier1, "simulation_only": True}
    first = client.post(url, headers=csrf, json=request)
    assert first.status_code == 201, first.text
    assert first.json()["eligible_count"] == 0
    assert first.json()["suppressed_count"] == 1
    assert first.json()["delivery_activated"] is False
    assert client.post(url, headers=csrf, json=request).status_code == 200

    consent = "/v1/communication/consent-events"
    assert client.post(consent, json={}).status_code == 403
    assert client.post(consent, headers=csrf, json={
        "recipient_kind": "prospect", "recipient_id": identifier,
        "channel": "whatsapp", "decision": "opted_in",
        "source": "signed paper form",
    }).status_code == 422
    attested = client.post(consent, headers=csrf, json={
        "recipient_kind": "prospect", "recipient_id": identifier,
        "channel": "whatsapp", "decision": "opted_in",
        "source": "signed paper form", "evidence_reference": "archive-123",
    })
    assert attested.status_code == 201, attested.text
    assert "evidence_reference" not in attested.json()
    preview = client.get(
        "/v1/communication/audience?audience=prospects&segment=active"
        "&channel=whatsapp&category=update"
    )
    assert preview.json()["eligible_count"] == 1
    second = client.post(url, headers=csrf, json={
        "request_id": str(uuid.uuid4()), "simulation_only": True,
    })
    assert second.status_code == 201, second.text
    assert second.json()["eligible_count"] == 1

    opted_out = client.post(consent, headers=csrf, json={
        "recipient_kind": "prospect", "recipient_id": identifier,
        "channel": "whatsapp", "decision": "opted_out",
        "source": "recipient requested stop",
    })
    assert opted_out.status_code == 201, opted_out.text
    third = client.post(url, headers=csrf, json={
        "request_id": str(uuid.uuid4()), "simulation_only": True,
    })
    assert third.status_code == 201, third.text
    assert third.json()["eligible_count"] == 0
    assert third.json()["suppressed_count"] == 1
    with Session(engine) as db:
        assert db.scalar(select(func.count(CommunicationConsentEvent.id))) == 2
        assert db.scalar(select(func.count(CommunicationPreparation.id))) == 3
        assert db.scalar(select(func.count(CommunicationRecipientSnapshot.id))) == 3
        assert db.scalar(select(func.count(MessageDispatch.id))) == 0
        assert db.scalars(select(CommunicationRecipientSnapshot).order_by(
            CommunicationRecipientSnapshot.id
        )).all()
    assert client.get(url).status_code == 200
    assert len(client.get(url).json()) == 3


def test_email_requires_documented_consent_and_preflight_is_tenant_scoped(system):
    client, engine = system
    csrf = login(client)
    person = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Email Recipient",
        "mobile_number": "+919876540112",
        "email": "email@example.org",
        "area_city": "Bengaluru",
        "monthly_contribution_paise": 25000,
    })
    assert person.status_code == 201, person.text
    identifier = person.json()["id"]
    campaign = create_campaign(client, csrf, channel="email", subject="Foundation notice")
    assert campaign.status_code == 201, campaign.text
    campaign_id = campaign.json()["id"]
    url = "/v1/communication/campaigns/" + campaign_id + "/preparations"
    assert client.get("/v1/communication/audience?channel=email").json()[
        "eligible_count"
    ] == 0
    response = client.post("/v1/communication/consent-events", headers=csrf, json={
        "recipient_kind": "prospect", "recipient_id": identifier, "channel": "email",
        "decision": "opted_in", "source": "documented affirmative request",
        "evidence_reference": "email-consent-log-1",
    })
    assert response.status_code == 201, response.text
    result = client.post(url, headers=csrf, json={
        "request_id": str(uuid.uuid4()), "simulation_only": True,
    })
    assert result.status_code == 201, result.text
    assert result.json()["eligible_count"] == 1
    with Session(engine) as db:
        other = Organization(name="Isolated tenant")
        db.add(other)
        db.flush()
        db.add(AdminUser(
            organization_id=other.id, email="other-contact@example.org",
            password_hash=hash_password("different-password"), is_active=True,
        ))
        db.commit()
    another = login(client, "other-contact@example.org", "different-password")
    assert client.get(url).status_code == 404
    assert client.post(url, headers=another, json={
        "request_id": str(uuid.uuid4()), "simulation_only": True,
    }).status_code == 404
    assert client.post("/v1/communication/consent-events", headers=another, json={
        "recipient_kind": "prospect", "recipient_id": identifier, "channel": "email",
        "decision": "opted_out", "source": "administrative opt-out",
    }).status_code == 404



def test_contact_consent_read_is_minimal_latest_and_tenant_scoped(system):
    client, engine = system
    assert client.get(
        "/v1/communication/consent-events",
        params={"recipient_kind": "prospect", "recipient_id": str(uuid.uuid4())},
    ).status_code == 401
    csrf = login(client)
    created = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Consent View Sponsor",
        "mobile_number": "+919876543299",
        "email": "private@example.org",
        "area_city": "Bengaluru",
        "monthly_contribution_paise": 25000,
        "whatsapp_opt_in": True,
    })
    assert created.status_code == 201, created.text
    identifier = created.json()["id"]
    route = "/v1/communication/consent-events"
    params = {"recipient_kind": "prospect", "recipient_id": identifier}
    empty = client.get(route, params=params)
    assert empty.status_code == 200
    assert empty.headers["cache-control"] == "no-store"
    assert empty.json() == []
    opt_in = {
        **params, "channel": "email", "decision": "opted_in",
        "source": "signed form", "evidence_reference": "private-proof-301",
    }
    assert client.post(route, headers=csrf, json=opt_in).status_code == 201
    assert client.post(route, headers=csrf, json={
        **params, "channel": "email", "decision": "opted_out",
        "source": "user stop request",
    }).status_code == 201
    assert client.post(route, headers=csrf, json={
        **params, "channel": "whatsapp", "decision": "opted_in",
        "source": "consent request", "evidence_reference": "record-340",
    }).status_code == 201
    last = client.get(route, params=params)
    assert last.status_code == 200
    assert len(last.json()) == 2
    events = {item["channel"]: item for item in last.json()}
    assert events["email"]["decision"] == "opted_out"
    assert events["whatsapp"]["decision"] == "opted_in"
    assert "private-proof-301" not in last.text
    assert "private@example.org" not in last.text
    assert "+919876543299" not in last.text
    assert client.get(route, params={
        "recipient_kind": "promoter", "recipient_id": identifier,
    }).status_code == 404
    with Session(engine) as db:
        org = Organization(name="Unrelated tenant")
        db.add(org)
        db.flush()
        db.add(AdminUser(
            organization_id=org.id, email="isolation@example.org",
            password_hash=hash_password("another-secure-password"),
            is_active=True,
        ))
        db.commit()
    other_csrf = login(client, "isolation@example.org", "another-secure-password")
    assert client.get(route, params=params).status_code == 404
    assert client.post(route, headers=other_csrf, json={
        **params, "channel": "email", "decision": "opted_out",
        "source": "untrusted user",
    }).status_code == 404
    assert client.get(route, params={
        "recipient_kind": "bad", "recipient_id": identifier,
    }).status_code == 422


def test_archived_prospect_cannot_be_granted_consent_but_may_opt_out(system):
    client, _ = system
    csrf = login(client)
    created = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Archived Consent Contact",
        "mobile_number": "+919876543298",
        "area_city": "Bengaluru",
        "monthly_contribution_paise": 25000,
    })
    assert created.status_code == 201, created.text
    identifier = created.json()["id"]
    assert client.delete(
        "/v1/prospects/" + identifier, headers={**csrf, "If-Match": "1"},
    ).status_code == 204
    route = "/v1/communication/consent-events"
    fields = {
        "recipient_kind": "prospect", "recipient_id": identifier,
        "channel": "whatsapp", "source": "recipient called",
    }
    grant = client.post(route, headers=csrf, json={
        **fields, "decision": "opted_in", "evidence_reference": "record-123",
    })
    assert grant.status_code == 409
    revoke = client.post(route, headers=csrf, json={
        **fields, "decision": "opted_out",
    })
    assert revoke.status_code == 201
    assert client.get(route, params={
        "recipient_kind": "prospect", "recipient_id": identifier,
    }).json()[0]["decision"] == "opted_out"
