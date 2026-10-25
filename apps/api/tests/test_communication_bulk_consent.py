"""Admin-only existing-consent confirmation never sends WhatsApp."""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_communication import (
    activate_for_communication,
    create_campaign,
    login,
    system as system,
)

from app.models import CommunicationConsentEvent, Prospect

def test_bulk_attestation_requires_evidence_skips_optouts_and_does_not_send(system):
    client, engine = system
    url = "/v1/communication/active-consent-review"
    assert client.get(url).status_code == 401
    assert client.post(url, json={}).status_code == 401
    csrf = login(client)
    ids = []
    for i in range(3):
        response = client.post("/v1/prospects", headers=csrf, json={
            "full_name": "Consent register sponsor "+str(i),
            "mobile_number": "+9198112200"+str(10+i),
            "area_city": "Bengaluru",
            "whatsapp_opt_in": False,
        })
        assert response.status_code == 201, response.text
        person = activate_for_communication(client, csrf, response.json())
        ids.append(person["id"])

    permissions = "/v1/communication/consent-events"
    opted_in = client.post(permissions, headers=csrf, json={
        "recipient_kind": "prospect", "recipient_id": ids[0],
        "channel": "whatsapp", "decision": "opted_in",
        "source": "signed consent list", "evidence_reference": "register-01",
    })
    assert opted_in.status_code == 201, opted_in.text
    opted_out = client.post(permissions, headers=csrf, json={
        "recipient_kind": "prospect", "recipient_id": ids[1],
        "channel": "whatsapp", "decision": "opted_out",
        "source": "recipient asked to stop",
    })
    assert opted_out.status_code == 201, opted_out.text

    preview = client.get(url)
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "no-store"
    assert preview.json() == {
        "active":3, "already_documented":1, "needs_confirmation":1,
        "opted_out":1, "no_number":0,
    }

    data = {
        "confirm":"I_HAVE_VERIFIED_EXISTING_CONSENT",
        "expected_needs_confirmation":1,
        "source":"Verified organizational opt-in register",
        "evidence_reference":"signed-register-2026-oct",
    }
    assert client.post(url, json=data).status_code == 403
    assert client.post(url, headers=csrf, json={
        **data, "confirm":"yes",
    }).status_code == 422
    assert client.post(url, headers=csrf, json={
        **data, "evidence_reference":" ",
    }).status_code == 422
    changed = client.post(url, headers=csrf, json=data)
    assert changed.status_code == 200, changed.text
    assert changed.json() == {
        "active":3, "already_documented":2, "needs_confirmation":0,
        "opted_out":1, "no_number":0,
    }

    with Session(engine) as db:
        confirmed = db.scalars(select(CommunicationConsentEvent).where(
            CommunicationConsentEvent.recipient_id == uuid.UUID(ids[2]),
        )).all()
        assert len(confirmed) == 1
        assert confirmed[0].evidence_reference == "signed-register-2026-oct"
        assert confirmed[0].source == "Verified organizational opt-in register"
        assert db.get(Prospect, uuid.UUID(ids[2])).whatsapp_opt_in is True
        assert db.get(Prospect, uuid.UUID(ids[1])).whatsapp_opt_in is False

    assert client.post(url, headers=csrf, json=data).status_code == 409
    campaign = create_campaign(client, csrf, title="Verified permissions").json()
    prepared = client.post(
        "/v1/communication/campaigns/"+campaign["id"]+"/preparations",
        headers=csrf,
        json={"request_id":str(uuid.uuid4()),"simulation_only":True},
    )
    assert prepared.status_code == 201, prepared.text
    assert prepared.json()["eligible_count"] == 2
    assert prepared.json()["exclusion_reasons"] == {"opted_out":1}


def test_existing_permission_review_is_read_only(system):
    client, engine = system
    csrf = login(client)
    person = client.post("/v1/prospects", headers=csrf, json={
        "full_name":"No prior consent", "mobile_number":"+919822331122",
        "area_city":"Bengaluru", "whatsapp_opt_in":False,
    })
    assert person.status_code == 201
    activate_for_communication(client, csrf, person.json())
    for _ in range(2):
        preview = client.get("/v1/communication/active-consent-review")
        assert preview.status_code == 200
        assert preview.json()["needs_confirmation"] == 1
    with Session(engine) as db:
        assert db.scalars(select(CommunicationConsentEvent)).all() == []
