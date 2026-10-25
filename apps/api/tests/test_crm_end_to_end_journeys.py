"""Cross-module CRM journeys with synthetic data; never touch the live local database.

The positive, negative, boundary and idempotency cases simulate real admin
workflows with FastAPI TestClient, CSRF cookies and fresh per-test databases.
"""
import uuid

import pytest
from activation_helper import activate_with_test_otp
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounting import effective_credits, ist_today, month_start
from app.models import (
    AuditEvent,
    CommunicationConsentEvent,
    ManualCollection,
    ManualCollectionReversal,
    MessageOutbox,
    PayoutPayment,
    PromoterAssignment,
    Prospect,
    ProspectStageDefinition,
)

pytest_plugins = ("test_crm_review_2026_10",)


def _create(client, csrf, *, name="Same Person", phone="+918701001111", **changes):
    return client.post("/v1/prospects", headers=csrf, json={
        "full_name": name, "mobile_number": phone, "area_city": "Bengaluru", **changes,
    })


def _activate(client, csrf, person):
    result = activate_with_test_otp(client, csrf, person)
    assert result.status_code == 200, result.text
    return result.json()


def test_same_name_different_numbers_allowed_duplicate_number_denied(api):
    client, csrf, engine = api
    first = _create(client, csrf, phone="+918701001111")
    second = _create(client, csrf, phone="+918701001112")
    assert first.status_code == second.status_code == 201
    a, b = first.json(), second.json()
    assert a["id"] != b["id"] and a["full_name"] == b["full_name"]
    assert a["pipeline_stage_name"] == b["pipeline_stage_name"] == "New Inquiry"
    assert a["crm_stage"] == b["crm_stage"] == "inactive"
    assert a["lifecycle_status"] == b["lifecycle_status"] == "new"
    duplicate = _create(client, csrf, name="Different Name", phone="+91 87010-01111")
    assert duplicate.status_code == 409 and "Mobile number" in duplicate.text
    assert a["id"] not in duplicate.text
    update = client.patch("/v1/prospects/"+b["id"], headers=csrf, json={
        "version": b["version"], "mobile_number": a["mobile_number"],
    })
    assert update.status_code == 409 and "Mobile number" in update.text
    assert client.get("/v1/prospects/"+b["id"]).json()["mobile_number"] == b["mobile_number"]
    assert client.get("/v1/prospects").json()["total"] == 2
    with Session(engine) as db:
        assert db.scalar(select(func.count(Prospect.id))) == 2


def test_same_mobile_remains_reserved_after_archive_and_restore(api):
    client, csrf, _ = api
    original = _create(client, csrf, phone="+918701001113").json()
    uri = "/v1/prospects/"+original["id"]
    archived = client.delete(uri, headers={**csrf, "If-Match": str(original["version"])})
    assert archived.status_code == 204
    assert _create(client, csrf, phone="+918701001113").status_code == 409
    assert client.get("/v1/prospects?include_archived=true").json()["total"] == 1
    restored = client.post(uri+"/restore", headers={
        **csrf, "If-Match": str(original["version"]+1),
    })
    assert restored.status_code == 200 and restored.json()["archived_at"] is None
    assert _create(client, csrf, phone="+918701001113").status_code == 409


def test_registration_replay_and_update_version_protect_same_mobile(api):
    client, csrf, engine = api
    key = str(uuid.uuid4())
    original = _create(client, csrf, phone="+918701001114", request_id=key)
    assert original.status_code == 201
    again = _create(client, csrf, phone="+918701001114", request_id=key)
    assert again.status_code == 200 and again.json()["id"] == original.json()["id"]
    reused = _create(client, csrf, phone="+918701001115", request_id=key)
    assert reused.status_code == 409
    modified = client.patch(
        "/v1/prospects/"+original.json()["id"], headers=csrf,
        json={"version":1,"mobile_number":"+91 87010-01116"},
    )
    assert modified.status_code == 200
    assert modified.json()["mobile_number"] == "+918701001116"
    stale = client.patch(
        "/v1/prospects/"+original.json()["id"], headers=csrf,
        json={"version":1,"mobile_number":"+918701001117"},
    )
    assert stale.status_code == 409
    assert _create(client, csrf, phone="+918701001116").status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count(Prospect.id))) == 1


@pytest.mark.parametrize("phone", [
    "9876543210", "+910", "+9199999999999999", "+91abc98765",
    "+91\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669\u0660",
    "+91 9876 54@210",
])
def test_invalid_or_non_ascii_mobile_rejected(api, phone):
    client, csrf, _ = api
    result = _create(client, csrf, phone=phone)
    assert result.status_code == 422, result.text


@pytest.mark.parametrize("amount", [0, 10000, 24999, 25001, 37500, 40001])
def test_sponsorship_amounts_outside_250_tiers_rejected(api, amount):
    client, csrf, _ = api
    result = _create(client, csrf, monthly_contribution_paise=amount)
    assert result.status_code == 422, result.text


def test_new_contact_number_revokes_whatsapp_permission_for_both_roles(api):
    client, csrf, engine = api
    prospect = _create(
        client, csrf, phone="+918701001123", whatsapp_number="+918701001123",
        whatsapp_opt_in=True,
    ).json()
    promoter_response = client.post("/v1/promoters", headers=csrf, json={
        "full_name":"Consent Owner", "mobile_number":"+918701002123",
        "whatsapp_number":"+918701002123", "whatsapp_opt_in":True,
    })
    assert promoter_response.status_code == 201, promoter_response.text
    promoter = promoter_response.json()
    for kind, person in (("prospect",prospect),("promoter",promoter)):
        opt_in = client.post("/v1/communication/consent-events", headers=csrf, json={
            "recipient_kind":kind, "recipient_id":person["id"],
            "channel":"whatsapp", "decision":"opted_in",
            "source":"synthetic evidence recorded", "evidence_reference":"consent-test-01",
        })
        assert opt_in.status_code == 201, opt_in.text
        url = "/v1/"+("prospects" if kind=="prospect" else "promoters")+"/"+person["id"]
        updated = client.patch(url, headers=csrf, json={
            "version":person["version"],
            "mobile_number":"+9187010091"+("23" if kind=="prospect" else "24"),
            "whatsapp_number":"+9187010091"+("23" if kind=="prospect" else "24"),
            "whatsapp_opt_in":True,
        })
        assert updated.status_code == 200, updated.text
        assert updated.json()["whatsapp_opt_in"] is False
        history = client.get("/v1/communication/consent-events", params={
            "recipient_kind":kind, "recipient_id":person["id"],
        })
        assert history.status_code == 200, history.text
        with Session(engine) as db:
            revoked = db.scalars(select(CommunicationConsentEvent).where(
                CommunicationConsentEvent.recipient_kind==kind,
                CommunicationConsentEvent.recipient_id==uuid.UUID(person["id"]),
                CommunicationConsentEvent.channel=="whatsapp",
                CommunicationConsentEvent.decision=="opted_out",
                CommunicationConsentEvent.source=="contact_address_changed",
            )).all()
            assert len(revoked)==1
    with Session(engine) as db:
        assert db.scalar(select(func.count(CommunicationConsentEvent.id))) == 4


def test_registration_stage_is_always_new_inquiry_then_editable(api):
    client, csrf, engine = api
    other = client.post("/v1/prospect-stages", headers=csrf, json={
        "name":"Awaiting Approval", "color":"#437b5d",
    })
    assert other.status_code == 201
    forged = _create(client, csrf, pipeline_stage_id=other.json()["id"])
    assert forged.status_code == 422
    created = _create(client, csrf, phone="+918701001118")
    assert created.status_code == 201
    person = created.json()
    assert person["pipeline_stage_name"] == "New Inquiry"
    changed = client.patch("/v1/prospects/"+person["id"], headers=csrf, json={
        "version":person["version"], "pipeline_stage_id":other.json()["id"],
    })
    assert changed.status_code == 200
    assert changed.json()["pipeline_stage_name"] == "Awaiting Approval"
    assert changed.json()["lifecycle_status"] == "new"
    assert changed.json()["crm_stage"] == "inactive"
    with Session(engine) as db:
        assert db.scalar(select(func.count(Prospect.id))) == 1
        assert db.scalar(select(func.count(ProspectStageDefinition.id))) == 2


def test_collection_positive_negative_replay_reversal_and_no_delivery(api):
    client, csrf, engine = api
    person = _create(client, csrf, phone="+918701001119").json()
    today = ist_today().isoformat()
    month = month_start(ist_today()).isoformat()
    payload = {
        "request_id":str(uuid.uuid4()), "prospect_id":person["id"],
        "period_month":month, "received_on":today,
        "amount_paise":25000, "payment_method":"upi",
        "receipt_reference":"SAS-E2E-RECEIPT-001",
        "funds_confirmed":True,
    }
    assert client.post("/v1/collections", headers=csrf, json=payload).status_code == 422
    active = _activate(client, csrf, person)
    assert active["lifecycle_status"] == "new"
    for amount in (24999, 25001):
        assert client.post("/v1/collections", headers=csrf, json={
            **payload, "request_id":str(uuid.uuid4()), "amount_paise":amount,
        }).status_code == 422
    bad_future = client.post("/v1/collections", headers=csrf, json={
        **payload, "request_id":str(uuid.uuid4()), "period_month":"2099-01-01",
    })
    assert bad_future.status_code == 422
    first = client.post("/v1/collections", headers=csrf, json=payload)
    assert first.status_code == 201, first.text
    assert client.post("/v1/collections", headers=csrf, json=payload).status_code == 200
    duplicate_reference = client.post("/v1/collections", headers=csrf, json={
        **payload, "request_id":str(uuid.uuid4()),
    })
    assert duplicate_reference.status_code == 409
    changed_same_id = client.post("/v1/collections", headers=csrf, json={
        **payload, "amount_paise":50000,
    })
    assert changed_same_id.status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count(ManualCollection.id))) == 1
        outbox = db.scalars(select(MessageOutbox)).one()
        assert outbox.status == "suppressed"
        tenant_id = db.get(Prospect, uuid.UUID(person["id"])).organization_id
        assert sum(c.amount_paise for c in effective_credits(
            db, tenant_id, sponsor_id=uuid.UUID(person["id"]),
        )) == 25000
    reversal = {
        "request_id":str(uuid.uuid4()),"reason_code":"wrong_amount",
        "confirmation":"REVERSE",
    }
    reverse_url = "/v1/collections/"+first.json()["id"]+"/reverse"
    reversed_once = client.post(reverse_url, headers=csrf, json=reversal)
    assert reversed_once.status_code == 201, reversed_once.text
    assert client.post(reverse_url, headers=csrf, json=reversal).status_code == 200
    assert client.post(reverse_url, headers=csrf, json={
        **reversal, "request_id":str(uuid.uuid4()),
    }).status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count(ManualCollectionReversal.id))) == 1
        assert not effective_credits(
            db, db.get(Prospect, uuid.UUID(person["id"])).organization_id,
            sponsor_id=uuid.UUID(person["id"]),
        )


def test_promoter_assignment_transfer_and_inactive_receiver_rejected(api):
    client, csrf, engine = api
    first_person = _create(client, csrf, phone="+918701001120").json()
    sponsors = [first_person, _create(client, csrf, phone="+918701001121").json()]
    promoters = []
    for i in range(3):
        created = client.post("/v1/promoters", headers=csrf, json={
            "full_name":"Same Promoter" if i != 2 else "Third Promoter",
            "mobile_number":f"+91870100212{i}","area_city":"Bengaluru",
        })
        assert created.status_code == 201, created.text
        promoters.append(created.json())
    assert client.post("/v1/promoters", headers=csrf, json={
        "full_name":"Another Name", "mobile_number":promoters[1]["mobile_number"],
    }).status_code == 409
    for person in sponsors:
        response = client.put(
            "/v1/promoters/"+promoters[0]["id"]+"/sponsors/"+person["id"],
            headers={**csrf,"If-Match":str(person["version"])},
        )
        assert response.status_code == 200, response.text
    origin = client.get("/v1/promoters/"+promoters[0]["id"]).json()
    blocked = client.patch("/v1/promoters/"+origin["id"], headers=csrf, json={
        "version":origin["version"],"is_active":False,
    })
    assert blocked.status_code == 422
    inactive = client.patch("/v1/promoters/"+promoters[2]["id"], headers=csrf, json={
        "version":promoters[2]["version"],"is_active":False,
    })
    assert inactive.status_code == 200
    wrong = client.patch("/v1/promoters/"+origin["id"], headers=csrf, json={
        "version":origin["version"],"is_active":False,
        "reassign_to_promoter_id":promoters[2]["id"],
    })
    assert wrong.status_code == 409
    transferred = client.patch("/v1/promoters/"+origin["id"], headers=csrf, json={
        "version":origin["version"],"is_active":False,
        "reassign_to_promoter_id":promoters[1]["id"],
    })
    assert transferred.status_code == 200, transferred.text
    assert client.get("/v1/promoters/"+origin["id"]+"/sponsors").json()["total"] == 0
    assert client.get("/v1/promoters/"+promoters[1]["id"]+"/sponsors").json()["total"] == 2
    with Session(engine) as db:
        assert db.scalar(select(func.count(PromoterAssignment.id))) == 4
        assert db.scalar(select(func.count(AuditEvent.id)).where(
            AuditEvent.action=="promoter.updated",
        )) >= 2


def test_quick_payout_attestation_idempotency_and_utr_uniqueness(api):
    client, csrf, engine = api
    payload = {
        "request_id":str(uuid.uuid4()), "first_name":"Building",
        "last_name":"Services","purpose":"Foundation maintenance",
        "amount_paise":37500,"paid_on":ist_today().isoformat(),
        "payment_method":"upi","payment_reference":"E2EUTR-TEST-0001",
        "funds_disbursed":True,
    }
    assert client.post("/v1/payouts/quick", headers=csrf, json={
        **payload,"funds_disbursed":False,
    }).status_code == 422
    payment = client.post("/v1/payouts/quick", headers=csrf, json=payload)
    assert payment.status_code == 201, payment.text
    replay = client.post("/v1/payouts/quick", headers=csrf, json=payload)
    assert replay.status_code == 200 and replay.json()["id"] == payment.json()["id"]
    new_id = client.post("/v1/payouts/quick", headers=csrf, json={
        **payload, "request_id":str(uuid.uuid4()),
    })
    assert new_id.status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count(PayoutPayment.id))) == 1
