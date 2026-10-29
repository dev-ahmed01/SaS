"""Secret configuration hard-fails in production rather than silently becoming insecure."""

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.security import hash_password


def test_staging_rejects_missing_session_secret() -> None:
    with pytest.raises(ValidationError, match="AUTH_SECRET"):
        Settings(
            app_env="staging",
            database_url="postgresql+psycopg://example.invalid/db",
            auth_secret=None,
        )


def test_dev_hash_requires_nontrivial_password() -> None:
    with pytest.raises(ValueError, match="12"):
        hash_password("short")


@pytest.mark.parametrize("env", ["staging", "production"])
def test_hosted_database_requires_tls_and_independent_secrets(env: str) -> None:
    base = {
        "app_env": env,
        "database_url": "postgresql+psycopg://app:secret@db.example.org/sas",
        "auth_secret": "a" * 48,
        "upi_match_secret": "b" * 48,
    }
    with pytest.raises(ValidationError, match="PostgreSQL TLS"):
        Settings(**base)
    for insecure in ("disable", "prefer", "allow", ""):
        with pytest.raises(ValidationError, match="PostgreSQL TLS"):
            Settings(**{**base, "database_url": base["database_url"] + "?sslmode=" + insecure})
    for mode in ("require", "verify-ca", "verify-full"):
        valid = Settings(**{
            **base,
            "database_url": base["database_url"] + "?sslmode=" + mode,
        })
        assert valid.app_env == env
        assert valid.saasyto_delivery_enabled is False
    with pytest.raises(ValidationError, match="PostgreSQL TLS"):
        Settings(**{
            **base,
            "database_url": base["database_url"] + "?sslmode=require&sslmode=disable",
        })



def test_mysql_staging_trial_is_explicit_local_and_send_disabled():
    base = {
        "_env_file": None,
        "app_env": "staging",
        "mysql_staging_trial_enabled": True,
        "database_url": (
            "mysql+pymysql://trial_user:test_password@127.0.0.1:3306/"
            "sas_mysql_trial_ci_001"
        ),
        "auth_secret": "a" * 48,
        "upi_match_secret": "b" * 48,
    }
    trial = Settings(**base)
    assert trial.mysql_staging_trial_enabled
    assert not trial.saasyto_delivery_enabled
    assert not trial.saasyto_auto_reminders_enabled

    for invalid in (
        {**base, "app_env": "production"},
        {**base, "mysql_staging_trial_enabled": False},
        {**base, "database_url": base["database_url"].replace(
            "127.0.0.1", "localhost",
        )},
        {**base, "database_url": base["database_url"].replace(
            "sas_mysql_trial_ci_001", "sas_production",
        )},
        {**base, "database_url": base["database_url"] + "?ssl_disabled=true"},
        {**base, "saasyto_delivery_enabled": True},
        {**base, "saasyto_auto_reminders_enabled": True},
        {**base, "otp_delivery_enabled": True},
    ):
        with pytest.raises(ValidationError):
            Settings(**invalid)


def test_mysql_staging_flag_cannot_authorize_production_without_migrated_schema():
    with pytest.raises(ValidationError, match="MySQL staging trial"):
        Settings(
            _env_file=None,
            app_env="production",
            mysql_staging_trial_enabled=True,
            database_url="mysql+pymysql://u:p@127.0.0.1:3306/sas_mysql_trial_ci_001",
            auth_secret="a" * 48,
            upi_match_secret="b" * 48,
        )



def test_saasyto_auto_reminders_need_standing_production_worker():
    with pytest.raises(ValidationError, match="Scheduled Saasyto reminders"):
        Settings(
            _env_file=None,
            app_env="production",
            database_url="postgresql+psycopg://u:p@db.example.org/sas?sslmode=require",
            auth_secret="a" * 48,
            upi_match_secret="b" * 48,
            saasyto_auto_reminders_enabled=True,
        )
