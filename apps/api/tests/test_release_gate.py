"""Release dossier controls do not invent approval or trigger external effects."""

import json
from datetime import UTC, datetime, timedelta

from app.release_gate import REQUIRED_GATES, evaluate_release_record, main

SHA = "a" * 40
NOW = datetime(2026, 10, 13, 15, tzinfo=UTC)


def evidence():
    return {
        "schema_version": 1,
        "release_sha": SHA,
        "gates": {
            name: {
                "approved": True,
                "reviewer": "Foundation Reviewer",
                "evidence_id": "SECURE-RECORD-" + name,
                "approved_at": "2026-10-13T14:00:00+00:00",
            }
            for name in REQUIRED_GATES
        },
    }


def test_empty_unapproved_dossier_is_always_blocked():
    result = evaluate_release_record({}, SHA, NOW)
    assert result["documentary_complete"] is False
    assert "whatsapp_authorization" in result["missing_or_invalid"]
    assert "foundation_final_approval" in result["missing_or_invalid"]
    assert result["authorizes_deployment_or_messaging"] is False


def test_complete_metadata_does_not_authorize_sends_or_deployment():
    result = evaluate_release_record(evidence(), SHA, NOW)
    assert result["documentary_complete"] is True
    assert result["requires_external_verification"] is True
    assert result["authorizes_deployment_or_messaging"] is False


def test_wrong_commit_or_missing_review_gate_fails_closed():
    payload = evidence()
    assert not evaluate_release_record(payload, "b" * 40, NOW)["documentary_complete"]
    del payload["gates"]["backup_restoration"]
    invalid = evaluate_release_record(payload, SHA, NOW)
    assert not invalid["documentary_complete"]
    assert "backup_restoration" in invalid["missing_or_invalid"]


def test_placeholder_and_unverified_or_future_approval_rejected():
    payload = evidence()
    payload["gates"]["financial_governance"]["evidence_id"] = "todo-ticket"
    payload["gates"]["tenant_auth"]["approved_at"] = (
        NOW + timedelta(minutes=1)
    ).isoformat()
    payload["gates"]["ui_approval"]["approved_at"] = "2026-10-13"
    payload["gates"]["protected_main"]["approved"] = 1
    errors = evaluate_release_record(payload, SHA, NOW)["missing_or_invalid"]
    assert set(errors) == {
        "financial_governance", "tenant_auth", "ui_approval", "protected_main"
    }


def test_no_secrets_or_personal_identifiers_leak_from_cli(tmp_path, monkeypatch, capsys):
    payload = evidence()
    payload["gates"]["payout_governance"]["reviewer"] = "Private Finance Owner"
    payload["gates"]["payout_governance"]["evidence_id"] = "PRIVATE-CASE-123456"
    file = tmp_path / "release-evidence.json"
    file.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv", ["release-gate", str(file), "--sha", SHA],
    )
    assert main() == 0
    output = capsys.readouterr().out
    assert "Private Finance Owner" not in output
    assert "PRIVATE-CASE-123456" not in output
    assert "authorizes_deployment_or_messaging" in output
