"""Reconciliation contract tests; no database/network and no donor records."""
import pytest

from app.config import Settings
from app.mysql_migration_reconcile import (
    FINANCIAL,
    FORMAT,
    INVARIANTS,
    TABLES,
    compare_manifests,
    main,
    validate_manifest,
)


def manifest(role="source"):
    return {
        "format": FORMAT,
        "role": role,
        "engine": "postgresql" if role == "source" else "mysql",
        "snapshot_id": "rehearsal_test_0001",
        "schema_revision": "0024_saasyto_claim_window_index"
        if role == "source" else "mysql_schema_trial_0001",
        "table_counts": {name: 0 for name in TABLES},
        "table_hmac_sha256": {name: "a" * 64 for name in TABLES},
        "financial_totals_paise": {name: 0 for name in FINANCIAL},
        "invariants": {name: True for name in INVARIANTS},
    }


def test_matching_manifests_are_not_cutover_authorization():
    report = compare_manifests(manifest(), manifest("target"))
    assert report["comparison"] == "passed"
    assert report["cutover_authorized"] is False
    assert report["tables_compared"] == len(TABLES)


@pytest.mark.parametrize("section,key,replacement", [
    ("table_counts", "prospects", 1),
    ("table_hmac_sha256", "prospects", "b" * 64),
    ("financial_totals_paise", "manual_collections_gross", 25000),
])
def test_mismatches_rejected(section, key, replacement):
    destination = manifest("target")
    destination[section][key] = replacement
    with pytest.raises(ValueError, match="Reconciliation mismatch"):
        compare_manifests(manifest(), destination)


def test_refuses_snapshot_confusion():
    destination = manifest("target")
    destination["snapshot_id"] = "rehearsal_test_0002"
    with pytest.raises(ValueError, match="Source snapshots"):
        compare_manifests(manifest(), destination)


def test_refuses_missing_table_and_extra_personal_data():
    source = manifest()
    del source["table_counts"]["prospects"]
    with pytest.raises(ValueError, match="Incomplete manifest section"):
        validate_manifest(source, "source")
    source = manifest()
    source["mobile_number"] = "+911234567890"
    with pytest.raises(ValueError, match="Unexpected or missing"):
        validate_manifest(source, "source")


@pytest.mark.parametrize("section,key,value", [
    ("table_counts", "prospects", True),
    ("table_counts", "prospects", -1),
    ("table_hmac_sha256", "prospects", "not-a-sha"),
    ("invariants", "referential_integrity", False),
])
def test_bad_data_or_integrity_fails_closed(section, key, value):
    source = manifest()
    source[section][key] = value
    with pytest.raises(ValueError):
        validate_manifest(source, "source")


def test_financial_balance_is_mandatory():
    source = manifest()
    source["financial_totals_paise"]["manual_collections_net"] = 25000
    with pytest.raises(ValueError, match="accounting"):
        validate_manifest(source, "source")



def test_independent_bank_verified_credit_does_not_break_manual_balance():
    """Bank reconciliations may legitimately exceed manual-attested receipts."""
    source = manifest()
    target = manifest("target")
    for record in (source, target):
        record["financial_totals_paise"]["verified_credits_gross"] = 50000
        record["financial_totals_paise"]["verified_credits_net"] = 50000
        # No manual receipts or manually attested credits were recorded.
        assert record["financial_totals_paise"]["manual_attested_credits_net"] == 0
    assert compare_manifests(source, target)["comparison"] == "passed"


def test_manual_attestation_mismatch_fails_even_if_verified_totals_match():
    source = manifest()
    source["financial_totals_paise"]["manual_attested_credits_net"] = 25000
    with pytest.raises(ValueError, match="manual-attested"):
        validate_manifest(source, "source")

def test_wrong_engine_and_swapped_role_rejected():
    destination = manifest("target")
    destination["engine"] = "postgresql"
    with pytest.raises(ValueError, match="database engine"):
        compare_manifests(manifest(), destination)
    with pytest.raises(ValueError, match="role or version"):
        validate_manifest(manifest(), "target")


def test_cli_rejects_invalid_private_manifest_without_echoing_it(tmp_path, capsys):
    source = tmp_path / "source.json"
    target = tmp_path / "target.json"
    source.write_text('{"mobile_number":"+911234567890"}', encoding="utf-8")
    target.write_text("{}", encoding="utf-8")
    assert main(["--source", str(source), "--target", str(target)]) == 1
    output = capsys.readouterr().out
    assert "failed" in output
    assert "+911234567890" not in output


def test_mysql_cannot_be_turned_on_in_production_before_compatibility_work():
    with pytest.raises(ValueError, match="require PostgreSQL"):
        Settings(
            _env_file=None,
            app_env="production",
            database_url="mysql+pymysql://user:password@localhost/sas_trial",
            auth_secret="a" * 40,
            upi_match_secret="b" * 40,
        )
