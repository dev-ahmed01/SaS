"""Bulk import acceptance tests: no side effects on preview or rejected batches."""
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Prospect, SponsorshipRate
from test_prospects import login

pytest_plugins = ("test_prospects",)


def payload(*, batch=None, rows=None, commit=False, **other):
    return {
        "batch_id": str(batch or uuid.uuid4()),
        "commit": commit,
        "rows": rows or [
            {"full_name": "Shared Name", "mobile_number": "+919876540001",
             "area_city": "Bengaluru"},
            {"full_name": "Shared Name", "mobile_number": "+919876540002",
             "monthly_contribution_paise": 75000},
        ],
        **other,
    }


def test_preview_does_not_write_and_commit_is_atomic_and_idempotent(system):
    client, engine = system
    source = payload()
    assert client.post("/v1/prospects/bulk", json=source).status_code == 401
    csrf = login(client)
    assert client.post("/v1/prospects/bulk", json=source).status_code == 403
    path = "/v1/prospects/bulk"
    preview = client.post(path, headers=csrf, json=source)
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data["preview_only"] and data["ready"] == 2 and data["blocked"] == 0
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Prospect)) == 0
        assert db.scalar(select(func.count()).select_from(SponsorshipRate)) == 0

    approved = {
        **source, "commit": True,
        "expected_month": data["default_start_month"],
        "expected_default_amount_paise": data["default_amount_paise"],
    }
    response = client.post(path, headers=csrf, json=approved)
    assert response.status_code == 200, response.text
    assert response.json()["added"] == 2
    assert all(x["status"] == "added" for x in response.json()["rows"])
    with Session(engine) as db:
        people = db.scalars(select(Prospect)).all()
        assert len(people) == 2
        assert len({p.mobile_number for p in people}) == 2
        assert all(p.full_name == "Shared Name" for p in people)
        assert all(p.crm_stage == "inactive" for p in people)
        assert all(p.lifecycle_status == "new" for p in people)
        assert all(p.whatsapp_opt_in is False for p in people)
        assert db.scalar(select(func.count()).select_from(SponsorshipRate)) == 2
        assert db.scalar(select(func.count(AuditEvent.id)).where(
            AuditEvent.action == "prospect.bulk_created",
        )) == 2
    repeated = client.post(path, headers=csrf, json=approved)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["added"] == 0
    assert repeated.json()["already_imported"] == 2
    assert client.get("/v1/prospects").json()["total"] == 2


def test_duplicate_numbers_block_entire_batch_without_partial_writes(system):
    client, engine = system
    csrf = login(client)
    path = "/v1/prospects/bulk"
    source = payload(rows=[
        {"full_name": "First person", "mobile_number": "+919876540010"},
        {"full_name": "Same phone", "mobile_number": "+919876540010"},
    ])
    preview = client.post(path, headers=csrf, json=source).json()
    assert preview["ready"] == 1 and preview["blocked"] == 1
    refused = client.post(path, headers=csrf, json={
        **source, "commit": True,
        "expected_month": preview["default_start_month"],
        "expected_default_amount_paise": preview["default_amount_paise"],
    })
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["rows"][1]["status"] == "blocked"
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Prospect)) == 0

    clean = payload(rows=[
        {"full_name": "Registered person", "mobile_number": "+919876540012"},
    ])
    first = client.post(path, headers=csrf, json=clean).json()
    success = client.post(path, headers=csrf, json={
        **clean, "commit": True, "expected_month": first["default_start_month"],
        "expected_default_amount_paise": first["default_amount_paise"],
    })
    assert success.status_code == 200, success.text
    conflict = payload(rows=[
        {"full_name": "New name", "mobile_number": "+919876540013"},
        {"full_name": "Existing phone", "mobile_number": "+919876540012"},
    ])
    pre = client.post(path, headers=csrf, json=conflict).json()
    assert pre["blocked"] == 1
    rejected = client.post(path, headers=csrf, json={
        **conflict, "commit": True, "expected_month": pre["default_start_month"],
        "expected_default_amount_paise": pre["default_amount_paise"],
    })
    assert rejected.status_code == 409
    assert client.get("/v1/prospects").json()["total"] == 1


def test_import_rejects_unsafe_fields_invalid_sponsorship_and_stale_confirmation(system):
    client, engine = system
    csrf = login(client)
    path = "/v1/prospects/bulk"
    for row in [
        {"full_name": "Forged person", "mobile_number": "+919876540030",
         "crm_stage": "active"},
        {"full_name": "Broken amount", "mobile_number": "+919876540031",
         "monthly_contribution_paise": 12500},
        {"full_name": "Invalid phone", "mobile_number": "9876540032"},
    ]:
        assert client.post(path, headers=csrf, json=payload(rows=[row])).status_code == 422
    assert client.post(path, headers=csrf, json=payload(rows=[
        {"full_name": "Batch Candidate", "mobile_number": f"+91987654{i:04d}"}
        for i in range(101)
    ])).status_code == 422
    source = payload(rows=[
        {"full_name": "Boundary person", "mobile_number": "+919876540038"},
    ])
    preview = client.post(path, headers=csrf, json=source).json()
    stale = client.post(path, headers=csrf, json={
        **source, "commit": True, "expected_month": preview["default_start_month"],
        "expected_default_amount_paise": preview["default_amount_paise"] + 25000,
    })
    assert stale.status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Prospect)) == 0


def test_import_request_id_cannot_be_reused_with_different_details(system):
    client, _ = system
    csrf = login(client)
    path = "/v1/prospects/bulk"
    source = payload(rows=[
        {"full_name": "Original owner", "mobile_number": "+919876540041"},
    ])
    pre = client.post(path, headers=csrf, json=source).json()
    good = client.post(path, headers=csrf, json={
        **source, "commit": True, "expected_month": pre["default_start_month"],
        "expected_default_amount_paise": pre["default_amount_paise"],
    })
    assert good.status_code == 200, good.text
    changed = payload(batch=uuid.UUID(source["batch_id"]), rows=[
        {"full_name": "Other identity", "mobile_number": "+919876540042"},
    ])
    assert client.post(path, headers=csrf, json=changed).json()["blocked"] == 1
    assert client.get("/v1/prospects").json()["total"] == 1
