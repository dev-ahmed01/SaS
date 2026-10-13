"""Restore-audit scope must prevent accidental production-data access."""
import pytest

from app.restored_staging_audit import audit_database, validate_restored_target

VALID = (
    "postgresql+psycopg://sas_audit:synthetic-ci-not-a-secret@"
    "staging.db.invalid:5432/sas_recovery_20261013?sslmode=verify-full"
)


def test_explicit_separate_tls_verified_staging_target_is_valid():
    url = validate_restored_target(
        VALID, app_env="staging", approved_name="sas_recovery_20261013"
    )
    assert url.database == "sas_recovery_20261013"


@pytest.mark.parametrize("url,env,approved", [
    (VALID, "production", "sas_recovery_20261013"),
    (VALID, "test", "sas_recovery_20261013"),
    (VALID, "staging", ""),
    (VALID, "staging", "sas_recovery_different"),
    (VALID.replace("sas_recovery_20261013", "sas_live"), "staging", "sas_live"),
    (VALID.replace("verify-full", "disable"), "staging", "sas_recovery_20261013"),
    (VALID.replace("verify-full", "require"), "staging", "sas_recovery_20261013"),
    ("", "staging", "sas_recovery_20261013"),
    ("sqlite:///:memory:", "staging", "sas_recovery_20261013"),
])
def test_bad_restoration_scopes_are_rejected(url, env, approved):
    with pytest.raises(ValueError):
        validate_restored_target(url, app_env=env, approved_name=approved)


def test_non_postgres_engine_does_not_get_a_false_audit_pass():
    class FakeDialect:
        name = "sqlite"

    class FakeEngine:
        dialect = FakeDialect()

    with pytest.raises(ValueError, match="PostgreSQL"):
        audit_database(FakeEngine())
