"""CRM redesign acceptance: activity is factual and promoter transfers are atomic."""
from app.accounting import ist_today

pytest_plugins = ("test_crm_review_2026_10",)


def test_individual_handover_is_atomic_and_retains_assignment_history(api):
    client, csrf, _ = api
    promoters = []
    for n in range(3):
        response = client.post("/v1/promoters", headers=csrf, json={
            "full_name": f"Demo Transfer Promoter {n}",
            "mobile_number": f"+91990000000{n}", "area_city": "Bengaluru",
        })
        assert response.status_code == 201, response.text
        promoters.append(response.json())
    candidates = []
    for n in range(2):
        response = client.post("/v1/prospects", headers=csrf, json={
            "full_name": f"Demo Transfer Prospect {n}",
            "mobile_number": f"+91980000000{n}", "area_city": "Bengaluru",
        })
        assert response.status_code == 201, response.text
        person = response.json()
        assigned = client.put(
            f"/v1/promoters/{promoters[0]['id']}/sponsors/{person['id']}",
            headers={**csrf, "If-Match": str(person["version"])},
        )
        assert assigned.status_code == 200, assigned.text
        candidates.append(person)
    source = client.get("/v1/promoters/" + promoters[0]["id"]).json()
    partial = client.patch("/v1/promoters/" + source["id"], headers=csrf, json={
        "version": source["version"], "is_active": False,
        "reassign_individually": {candidates[0]["id"]: promoters[1]["id"]},
    })
    assert partial.status_code == 409, partial.text
    assert client.get("/v1/promoters/" + source["id"]).json()["is_active"] is True
    assert client.get("/v1/promoters/" + source["id"] + "/sponsors").json()["total"] == 2
    moved = client.patch("/v1/promoters/" + source["id"], headers=csrf, json={
        "version": source["version"], "is_active": False,
        "reassign_individually": {
            candidates[0]["id"]: promoters[1]["id"],
            candidates[1]["id"]: promoters[2]["id"],
        },
    })
    assert moved.status_code == 200, moved.text
    assert moved.json()["is_active"] is False
    assert client.get("/v1/promoters/" + source["id"] + "/sponsors").json()["total"] == 0
    for target in promoters[1:]:
        assert client.get("/v1/promoters/" + target["id"] + "/sponsors").json()["total"] == 1
    timeline = client.get("/v1/promoters/" + source["id"] + "/activity")
    assert timeline.status_code == 200, timeline.text
    assert any(row["title"] == "Promoter deactivated" for row in timeline.json())
    for candidate in candidates:
        events = client.get("/v1/prospects/" + candidate["id"] + "/activity")
        assert events.status_code == 200, events.text
        assert any(row["title"] == "Promoter assigned" for row in events.json())


def test_prospect_timeline_records_real_followup_and_no_unmade_payments(api):
    client, csrf, _ = api
    response = client.post("/v1/prospects", headers=csrf, json={
        "full_name": "Timeline Prospect",
        "mobile_number": "+918212340001", "area_city": "Bengaluru",
    })
    assert response.status_code == 201, response.text
    sponsor = response.json()
    events = client.get("/v1/prospects/" + sponsor["id"] + "/activity")
    assert events.status_code == 200
    assert [row["title"] for row in events.json()] == ["Prospect created"]
    followup = client.post("/v1/prospects/" + sponsor["id"] + "/followups", headers=csrf, json={
        "version": sponsor["version"], "occurred_on": ist_today().isoformat(),
        "outcome": "contacted", "notes": "Sponsor requested a follow-up",
    })
    assert followup.status_code == 201, followup.text
    events = client.get("/v1/prospects/" + sponsor["id"] + "/activity")
    assert events.status_code == 200
    assert any(item["title"] == "Follow-up: contacted" for item in events.json())
    assert not any(item["kind"] == "payment" for item in events.json())
