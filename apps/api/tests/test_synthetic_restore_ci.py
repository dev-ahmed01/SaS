"""Destructive recovery tooling must categorically reject non-CI scope."""
import pytest

from app.synthetic_restore_ci import postgres_client, validate_ci_scope

LOCAL = (
    "postgresql+psycopg://sas_ci:synthetic-only-password@"
    "127.0.0.1:5432/sas_ci"
)


def test_explicit_ephemeral_local_ci_can_pass_scope_check():
    parsed = validate_ci_scope(LOCAL, "test", "1")
    assert parsed.database == "sas_ci"
    assert parsed.host == "127.0.0.1"


@pytest.mark.parametrize("db_url,environment,opt_in", [
    (LOCAL, "production", "1"),
    (LOCAL, "staging", "1"),
    (LOCAL, "test", ""),
    (LOCAL, "test", "yes"),
    (LOCAL.replace("sas_ci", "foundation_live"), "test", "1"),
    (LOCAL.replace("127.0.0.1", "db.example.net"), "test", "1"),
    (LOCAL.replace(":5432/", ":5433/"), "test", "1"),
    (LOCAL.replace("sas_ci:synthetic", "live_admin:synthetic"), "test", "1"),
    (LOCAL + "?sslmode=disable", "test", "1"),
    ("postgresql://sas_ci:pass@localhost:5432/sas_ci", "test", "1"),
    ("sqlite:///:memory:", "test", "1"),
    ("", "test", "1"),
])
def test_any_non_ephemeral_database_target_is_blocked(
    db_url, environment, opt_in
):
    with pytest.raises(ValueError):
        validate_ci_scope(db_url, environment, opt_in)


def test_no_unsupported_client_command_can_run():
    with pytest.raises(ValueError):
        postgres_client("dropdb", None, "sas_ci", None)
