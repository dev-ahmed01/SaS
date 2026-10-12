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
