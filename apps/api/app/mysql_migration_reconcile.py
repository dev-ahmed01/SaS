"""Offline, read-only-proof comparison for a future PostgreSQL to MySQL move.

This utility has no database connection, SQL execution or export capability.
Only compare aggregate manifests from separately reviewed extractors. A passing
comparison NEVER authorizes production cutover or outbound messaging.
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any

from app.models import Base

FORMAT = "sas-migration-manifest-v1"
FIELDS = frozenset({
    "format", "role", "engine", "snapshot_id", "schema_revision",
    "table_counts", "table_hmac_sha256", "financial_totals_paise", "invariants",
})
TABLES = frozenset(Base.metadata.tables)
FINANCIAL = frozenset({
    "manual_collections_gross", "verified_credits_gross",
    "manual_collections_net", "verified_credits_net",
    "payout_payments_gross",
})
INVARIANTS = frozenset({
    "referential_integrity", "one_active_promoter_per_prospect",
    "net_manual_ledger_balanced", "tenant_boundary_integrity",
})
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9_-]{12,90}\Z")


def _nonnegative_int(value: Any) -> bool:
    return type(value) is int and 0 <= value <= 2**63 - 1


def validate_manifest(manifest: Any, role: str) -> dict:
    """Validate an aggregate-only manifest without leaking its contents."""
    if not isinstance(manifest, dict) or set(manifest) != FIELDS:
        raise ValueError("Unexpected or missing manifest fields")
    if manifest["format"] != FORMAT or manifest["role"] != role:
        raise ValueError("Incorrect manifest role or version")
    if manifest["engine"] != ("postgresql" if role == "source" else "mysql"):
        raise ValueError("Incorrect database engine for role")
    if not isinstance(manifest["snapshot_id"], str) or not _ID.fullmatch(
        manifest["snapshot_id"]
    ):
        raise ValueError("Invalid snapshot identifier")
    if not isinstance(manifest["schema_revision"], str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{6,100}", manifest["schema_revision"]
    ):
        raise ValueError("Invalid schema revision")
    for key, expected in (
        ("table_counts", TABLES),
        ("table_hmac_sha256", TABLES),
        ("financial_totals_paise", FINANCIAL),
        ("invariants", INVARIANTS),
    ):
        section = manifest[key]
        if not isinstance(section, dict) or set(section) != expected:
            raise ValueError("Incomplete manifest section: " + key)
    if not all(_nonnegative_int(v) for v in manifest["table_counts"].values()):
        raise ValueError("Invalid row counts")
    if not all(isinstance(v, str) and _HEX.fullmatch(v)
               for v in manifest["table_hmac_sha256"].values()):
        raise ValueError("Invalid HMAC digest format")
    if not all(_nonnegative_int(v) for v in manifest["financial_totals_paise"].values()):
        raise ValueError("Invalid financial totals")
    if not all(v is True for v in manifest["invariants"].values()):
        raise ValueError("Required integrity check did not pass")
    if manifest["financial_totals_paise"]["manual_collections_net"] != (
        manifest["financial_totals_paise"]["verified_credits_net"]
    ):
        raise ValueError("Manual collection accounting does not reconcile")
    return manifest


def compare_manifests(source: Any, target: Any) -> dict:
    """Fail closed on any discrepancy. Matching data is not proof of safe hosting."""
    source = validate_manifest(source, "source")
    target = validate_manifest(target, "target")
    if source["snapshot_id"] != target["snapshot_id"]:
        raise ValueError("Source snapshots do not match")
    for section in ("table_counts", "table_hmac_sha256", "financial_totals_paise"):
        mismatches = sorted(
            key for key in source[section]
            if source[section][key] != target[section][key]
        )
        if mismatches:
            raise ValueError("Reconciliation mismatch in " + section + ": " +
                             ", ".join(mismatches))
    return {
        "comparison": "passed",
        "snapshot_id": source["snapshot_id"],
        "tables_compared": len(TABLES),
        "cutover_authorized": False,
        "note": "Manifest-only check. Independently verify source backups, restore, "
                "application runtime, and final frozen-source cutover.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline SaS data-copy comparison")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        source = json.loads(args.source.read_text(encoding="utf-8"))
        target = json.loads(args.target.read_text(encoding="utf-8"))
        result = compare_manifests(source, target)
    except (OSError, ValueError, TypeError):
        # Never echo source files, credentials, contacts, or receipts.
        print("Migration comparison failed; inspect private manifests")
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
