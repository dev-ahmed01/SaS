"""Password hashing and opaque database-backed Admin sessions.

There are no JWTs in browser storage, no default passwords, and no ambient Admin bypass.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

COOKIE_NAME = "sas_session"
SESSION_HOURS = 8
PASSWORD_HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=2)
# Timing-safe verification when an Admin email does not exist.
_UNKNOWN_ADMIN_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(28))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 128:
        raise ValueError("Admin password must be 12 to 128 characters")
    return PASSWORD_HASHER.hash(password)


def verify_password(stored: str | None, password: str) -> bool:
    try:
        return bool(PASSWORD_HASHER.verify(stored or _UNKNOWN_ADMIN_HASH, password))
    except (InvalidHashError, VerificationError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def csrf_for_token(token: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), ("csrf:" + token).encode(), hashlib.sha256).hexdigest()


def compare_csrf(provided: str | None, token: str, secret: str) -> bool:
    return bool(provided) and hmac.compare_digest(
        provided or "", csrf_for_token(token, secret)
    )


def throttle_key(value: str, secret: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()
