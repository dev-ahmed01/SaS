"""Fail-closed, OFFLINE documentary checks for the Foundation release dossier.

A successful result means only that the evidence form is syntactically complete.
It is not independent verification of the claims, approval to deploy, or permission
to send WhatsApp messages. This module never connects to external services.
"""

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REQUIRED_GATES = (
    "source_review",
    "protected_main",
    "tenant_auth",
    "financial_governance",
    "payout_governance",
    "consent_retention",
    "staging_verification",
    "backup_restoration",
    "whatsapp_authorization",
    "incident_monitoring",
    "ui_approval",
    "foundation_final_approval",
)

SHA = re.compile(r"^[a-f0-9]{40}$")
EVIDENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:/._-]{11,159}$")
PLACEHOLDERS = ("pending", "todo", "tbd", "example", "placeholder", "synthetic")


def _nonplaceholder(value: Any, *, minimum: int = 2) -> bool:
    return (
        isinstance(value, str)
        and minimum <= len(value.strip()) <= 160
        and not any(marker in value.lower() for marker in PLACEHOLDERS)
    )


def evaluate_release_record(
    record: Any, expected_sha: str, now: datetime | None = None,
) -> dict[str, Any]:
    """Check complete signed-off *metadata* only; never trust it as provider proof."""
    if now is None:
        now = datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("The evaluation clock must include a timezone")
    now = now.astimezone(UTC)
    errors: list[str] = []
    if not isinstance(record, dict):
        return {
            "documentary_complete": False,
            "missing_or_invalid": ["record"],
            "requires_external_verification": True,
            "authorizes_deployment_or_messaging": False,
        }
    if record.get("schema_version") != 1:
        errors.append("schema_version")
    if not SHA.fullmatch(expected_sha) or record.get("release_sha") != expected_sha:
        errors.append("release_sha")
    gates = record.get("gates")
    if not isinstance(gates, dict):
        gates = {}
    for name in REQUIRED_GATES:
        entry = gates.get(name)
        if not isinstance(entry, dict) or entry.get("approved") is not True:
            errors.append(name)
            continue
        reviewer = entry.get("reviewer")
        evidence = entry.get("evidence_id")
        stamped = entry.get("approved_at")
        if not _nonplaceholder(reviewer):
            errors.append(name)
            continue
        if (
            not _nonplaceholder(evidence, minimum=12)
            or not EVIDENCE_ID.fullmatch(evidence)
        ):
            errors.append(name)
            continue
        if not isinstance(stamped, str):
            errors.append(name)
            continue
        try:
            signed = datetime.fromisoformat(stamped.replace("Z", "+00:00"))
        except ValueError:
            errors.append(name)
            continue
        if signed.tzinfo is None or signed.astimezone(UTC) > now:
            errors.append(name)
    return {
        "documentary_complete": not errors,
        "missing_or_invalid": errors,
        "requires_external_verification": True,
        "authorizes_deployment_or_messaging": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate release evidence metadata; never deploys or sends messages."
    )
    parser.add_argument("evidence_file", type=Path)
    parser.add_argument("--sha", required=True, help="40-character intended release SHA")
    args = parser.parse_args()
    try:
        record = json.loads(args.evidence_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = None
    result = evaluate_release_record(record, args.sha)
    # No reviewer identities, donor records, or evidence IDs are ever printed.
    print(json.dumps(result, sort_keys=True))
    return 0 if result["documentary_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
