"""End-to-end tenant boundaries across CRM, finance, promoters and planning.

Two independently authenticated browsers and two synthetic organizations.
Never uses real donor information or activates message transports.
"""
import uuid

from activation_helper import activate_with_test_otp
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounting import ist_today, month_start
from app.main import app
from app.models import (
    AdminUser,
    CommunicationConsentEvent,
    ManualCollection,
    ManualCollectionReversal,
    Organization,
    OrganizationSettings,
    PromoterAssignment,
    Prospect,
)
from app.security import hash_password

pytest_plugins = ("test_crm_review_2026_10",)


def _register(client, csrf, *, phone: str):
    response = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Same Name Across Tenants",
        "mobile_number": phone,
        "area_city": "Bengaluru",
        "monthly_contribution_paise": 50000,
    })
    assert response.status_code == 201, response.text
    return response.json()


def _promoter(client, csrf, *, phone: str):
    response = client.post("/v1/promoters", headers=csrf, json={
        "full_name": "Same Promoter Name Across Tenants",
        "mobile_number": phone, "area_city": "Bengaluru",
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_two_admins_cannot_read_or_mutate_each_others_records(api):
    first, first_csrf, engine = api
    shared_sponsor_mobile = "+918888800701"
    shared_promoter_mobile = "+918888800702"
    sponsor_a = _register(first, first_csrf, phone=shared_sponsor_mobile)
    promoter_a = _promoter(first, first_csrf, phone=shared_promoter_mobile)
    assignment = first.put(
        f"/v1/promoters/{promoter_a['id']}/sponsors/{sponsor_a['id']}",
        headers={**first_csrf, "If-Match": str(sponsor_a["version"])},
    )
    assert assignment.status_code == 200, assignment.text
    details_a = first.get("/v1/prospects/" + sponsor_a["id"]).json()
    activation = activate_with_test_otp(first, first_csrf, details_a)
    assert activation.status_code == 200, activation.text
    today = ist_today()
    receipt_a = first.post("/v1/collections", headers=first_csrf, json={
        "request_id": str(uuid.uuid4()),
        "prospect_id": sponsor_a["id"],
        "period_month": month_start(today).isoformat(),
        "received_on": today.isoformat(),
        "amount_paise": 25000,
        "payment_method": "upi",
        "receipt_reference": "TENANT-BOUNDARY-RECEIPT-701",
        "funds_confirmed": True,
    })
    assert receipt_a.status_code == 201, receipt_a.text
    template_a = first.post("/v1/communication/templates", headers=first_csrf, json={
        "name": "Private foundation update",
        "channel": "whatsapp", "category": "update",
        "body": "Synthetic private foundation planning message",
    })
    assert template_a.status_code == 201, template_a.text
    campaign_a = first.post("/v1/communication/campaigns", headers=first_csrf, json={
        "request_id": str(uuid.uuid4()),
        "title": "Private foundation planning",
        "channel": "whatsapp", "audience": "prospects",
        "segment": "all", "category": "update",
        "body": "Synthetic campaign for the original foundation",
    })
    assert campaign_a.status_code == 201, campaign_a.text

    with Session(engine) as db:
        second_org = Organization(name="Independent synthetic QA foundation")
        db.add(second_org)
        db.flush()
        db.add(AdminUser(
            organization_id=second_org.id,
            email="tenant-isolation@foundation.org",
            password_hash=hash_password("synthetic-second-tenant-password"),
            is_active=True,
        ))
        db.add(OrganizationSettings(
            organization_id=second_org.id,
            currency_code="INR", timezone="Asia/Kolkata",
            default_contribution_paise=50000,
            sponsor_reminder_day=5, promoter_reminder_day=20,
            inactivity_months=2, automation_enabled=False,
        ))
        original = db.get(Prospect, uuid.UUID(sponsor_a["id"]))
        original_org_id = original.organization_id
        db.commit()

    with TestClient(app) as second:
        signed_in = second.post("/v1/auth/login", json={
            "email": "tenant-isolation@foundation.org",
            "password": "synthetic-second-tenant-password",
        })
        assert signed_in.status_code == 200, signed_in.text
        second_csrf = {
            "X-CSRF-Token": second.get("/v1/auth/session").json()["csrf_token"],
        }

        # No public or private leakage of the first tenant's records.
        for endpoint in (
            "/v1/prospects/" + sponsor_a["id"],
            "/v1/prospects/" + sponsor_a["id"] + "/followups",
            "/v1/prospects/" + sponsor_a["id"] + "/activity",
            "/v1/promoters/" + promoter_a["id"],
            "/v1/promoters/" + promoter_a["id"] + "/sponsors",
            "/v1/promoters/" + promoter_a["id"] + "/activity",
        ):
            response = second.get(endpoint)
            assert response.status_code == 404, (endpoint, response.text)
        assert second.get("/v1/prospects").json()["total"] == 0
        assert second.get("/v1/promoters").json()["total"] == 0
        assert second.get("/v1/collections").json()["total"] == 0
        assert second.get("/v1/communication/templates").json() == []
        assert second.get("/v1/communication/campaigns").json() == []

        # An attacker cannot use their own valid CSRF to mutate other tenants.
        blocked = [
            second.patch(
                "/v1/prospects/" + sponsor_a["id"],
                headers=second_csrf,
                json={"version": activation.json()["version"],
                      "area_city": "Unauthorized"},
            ),
            second.post(
                "/v1/prospects/" + sponsor_a["id"] + "/stage",
                headers=second_csrf,
                json={"version": activation.json()["version"],
                      "stage": "inactive", "reason": "other",
                      "note": "Unauthorized transfer"},
            ),
            second.patch(
                "/v1/promoters/" + promoter_a["id"],
                headers=second_csrf,
                json={"version": assignment.json()["version"], "is_active": False},
            ),
            second.post(
                "/v1/collections/" + receipt_a.json()["id"] + "/reverse",
                headers=second_csrf,
                json={"request_id": str(uuid.uuid4()),
                      "reason_code": "wrong_amount", "confirmation": "REVERSE"},
            ),
            second.post("/v1/collections", headers=second_csrf, json={
                "request_id": str(uuid.uuid4()), "prospect_id": sponsor_a["id"],
                "period_month": month_start(today).isoformat(),
                "received_on": today.isoformat(),
                "amount_paise": 25000, "payment_method": "upi",
                "receipt_reference": "CROSS-TENANT-DENIED-001",
                "funds_confirmed": True,
            }),
            second.patch(
                "/v1/communication/templates/" + template_a.json()["id"],
                headers=second_csrf,
                json={"version": template_a.json()["version"],
                      "name": "Unauthorized edited template",
                      "channel": "whatsapp", "category": "update",
                      "body": "Unauthorized replacement"},
            ),
            second.post(
                "/v1/communication/campaigns/" + campaign_a.json()["id"] + "/cancel",
                headers=second_csrf, json={},
            ),
            second.post("/v1/communication/consent-events", headers=second_csrf, json={
                "recipient_kind": "prospect", "recipient_id": sponsor_a["id"],
                "channel": "whatsapp", "decision": "opted_out",
                "source": "unauthorized test",
            }),
        ]
        assert [item.status_code for item in blocked] == [404] * len(blocked), [
            (item.status_code, item.text) for item in blocked
        ]

        # Same names and numbers may exist in independent organizations.
        sponsor_b = _register(second, second_csrf, phone=shared_sponsor_mobile)
        promoter_b = _promoter(second, second_csrf, phone=shared_promoter_mobile)
        assert second.put(
            f"/v1/promoters/{promoter_b['id']}/sponsors/{sponsor_a['id']}",
            headers={**second_csrf, "If-Match": "1"},
        ).status_code == 404
        assert second.put(
            f"/v1/promoters/{promoter_a['id']}/sponsors/{sponsor_b['id']}",
            headers={**second_csrf, "If-Match": "1"},
        ).status_code == 404
        own_assignment = second.put(
            f"/v1/promoters/{promoter_b['id']}/sponsors/{sponsor_b['id']}",
            headers={**second_csrf, "If-Match": str(sponsor_b["version"])},
        )
        assert own_assignment.status_code == 200, own_assignment.text
        assert second.get("/v1/prospects").json()["total"] == 1
        assert second.get("/v1/promoters").json()["total"] == 1
        assert second.get("/v1/collections").json()["total"] == 0
        # CSRF tokens are bound to the Admin session, not reusable across tenants.
        assert second.patch(
            "/v1/prospects/" + sponsor_b["id"],
            headers=first_csrf,
            json={"version": sponsor_b["version"], "notes": "cross-session"},
        ).status_code == 403

    # No rejected request altered the original tenant's financial evidence.
    assert first.get("/v1/prospects/" + sponsor_a["id"]).json()[
        "area_city"
    ] == "Bengaluru"
    assert first.get("/v1/promoters/" + promoter_a["id"]).json()["is_active"] is True
    assert first.get("/v1/collections").json()["total"] == 1
    assert first.get("/v1/communication/campaigns").json()[0]["status"] == "draft"
    with Session(engine) as db:
        assert db.scalar(select(func.count(ManualCollectionReversal.id))) == 0
        assert db.scalar(select(func.count(ManualCollection.id)).where(
            ManualCollection.organization_id == original_org_id,
        )) == 1
        assert db.scalar(select(func.count(PromoterAssignment.id)).where(
            PromoterAssignment.organization_id == original_org_id,
            PromoterAssignment.ended_at.is_(None),
        )) == 1
        assert db.scalar(select(func.count(CommunicationConsentEvent.id)).where(
            CommunicationConsentEvent.organization_id == original_org_id,
        )) == 0
