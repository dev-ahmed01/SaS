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
        assert valid.messaging_delivery_enabled is False
    with pytest.raises(ValidationError, match="PostgreSQL TLS"):
        Settings(**{
            **base,
            "database_url": base["database_url"] + "?sslmode=require&sslmode=disable",
        })
