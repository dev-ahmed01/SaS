"""Admin-only authentication API: persistent sessions, CSRF, and throttled sign-in."""

import hashlib
import hmac
import ipaddress
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.models import AdminLoginAttempt, AdminSession, AdminUser, AuditEvent, Organization
from app.security import (
    COOKIE_NAME,
    SESSION_HOURS,
    as_utc,
    compare_csrf,
    csrf_for_token,
    new_session_token,
    throttle_key,
    token_digest,
    utc_now,
    verify_password,
)

router = APIRouter(prefix="/v1/auth", tags=["Admin authentication"])


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email", mode="before")
    @classmethod
    def local_admin_alias(cls, value: object) -> object:
        # Explicitly enabled, localhost-only development mode; EmailStr
        # validation remains mandatory for production and ordinary accounts.
        if (
            isinstance(value, str)
            and value.strip().lower() == "admin"
            and getattr(get_settings(), "local_demo_login_enabled", False)
        ):
            return "admin@local.sas.example"
        return value


def db_session():
    with Session(get_engine()) as database:
        yield database


def auth_secret() -> str:
    value = get_settings().auth_secret
    if not value or len(value) < 32:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    return value


def get_admin(
    request: Request, database: Annotated[Session, Depends(db_session)]
) -> tuple[AdminUser, AdminSession, str]:
    raw_token = request.cookies.get(COOKIE_NAME)
    if not raw_token or len(raw_token) > 120:
        raise HTTPException(status_code=401, detail="Sign in required")
    record = database.scalars(
        select(AdminSession).where(AdminSession.token_hash == token_digest(raw_token))
    ).one_or_none()
    if record is None or record.revoked_at is not None or as_utc(record.expires_at) <= utc_now():
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    admin = database.get(AdminUser, record.admin_user_id)
    if admin is None or not admin.is_active or admin.organization_id != record.organization_id:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    return admin, record, raw_token


def require_csrf(
    request: Request,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
) -> tuple[AdminUser, AdminSession, str]:
    if not compare_csrf(request.headers.get("x-csrf-token"), context[2], auth_secret()):
        raise HTTPException(status_code=403, detail="CSRF verification failed")
    return context


def _trusted_login_network(request: Request, secret: str) -> str | None:
    """Only a gateway-signed client IP may authorize a shared network throttle."""
    raw = request.headers.get("x-sas-login-client-ip")
    signature = request.headers.get("x-sas-login-client-signature")
    if not raw or not signature or len(raw) > 64 or len(signature) != 64:
        return None
    try:
        normalized = str(ipaddress.ip_address(raw))
    except ValueError:
        return None
    expected = hmac.new(
        secret.encode("utf-8"),
        ("sas:bff-login-client:v1:" + normalized).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return normalized if hmac.compare_digest(expected, signature) else None


def _audit(database: Session, admin: AdminUser, action: str) -> None:
    database.add(
        AuditEvent(
            organization_id=admin.organization_id,
            actor_admin_id=admin.id,
            action=action,
            entity_type="admin_user",
            entity_id=str(admin.id),
        )
    )


@router.post("/login", status_code=200)
def login(
    payload: Credentials, request: Request, response: Response,
    database: Annotated[Session, Depends(db_session)],
) -> dict[str, str]:
    secret = auth_secret()
    email = payload.email.strip().lower()
    now = utc_now()
    # BFF source IPs can be shared across visitors. Only use a network-wide
    # throttle if the original client identity is authenticated by the BFF.
    network = _trusted_login_network(request, secret)
    raw_peer = request.client.host if request.client else "unknown"
    email_key = throttle_key("email:" + email, secret)
    ip_key = throttle_key(
        "network:" + network if network else "untrusted-peer:" + raw_peer,
        secret,
    )
    recent = now - timedelta(minutes=15)
    condition = AdminLoginAttempt.email_hash == email_key
    if network is not None:
        condition = condition | (AdminLoginAttempt.network_hash == ip_key)
    failures = database.scalar(
        select(func.count()).select_from(AdminLoginAttempt).where(
            AdminLoginAttempt.occurred_at >= recent, condition,
        )
    ) or 0
    if failures >= 8:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    admin = database.scalars(select(AdminUser).where(AdminUser.email == email)).one_or_none()
    verified = verify_password(admin.password_hash if admin else None, payload.password)
    if not admin or not admin.is_active or not verified:
        database.add(
            AdminLoginAttempt(
                email_hash=email_key, network_hash=ip_key, occurred_at=now
            )
        )
        database.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Rehash safely when the Argon2 parameters are strengthened in later releases.
    from app.security import PASSWORD_HASHER
    if PASSWORD_HASHER.check_needs_rehash(admin.password_hash):
        from app.security import hash_password
        admin.password_hash = hash_password(payload.password)

    raw_token = new_session_token()
    database.add(
        AdminSession(
            admin_user_id=admin.id,
            organization_id=admin.organization_id,
            token_hash=token_digest(raw_token),
            created_at=now,
            expires_at=now + timedelta(hours=SESSION_HOURS),
        )
    )
    _audit(database, admin, "admin.login")
    database.commit()
    response.set_cookie(
        COOKIE_NAME, raw_token, max_age=SESSION_HOURS * 3600, path="/",
        httponly=True, secure=get_settings().app_env in ("staging", "production"),
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"status": "authenticated"}


@router.get("/session")
def current_session(
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
) -> dict[str, str]:
    admin, _record, token = context
    organization = database.get(Organization, admin.organization_id)
    response.headers["Cache-Control"] = "no-store"
    return {
        "email": admin.email,
        "organization_name": organization.name if organization else "",
        "csrf_token": csrf_for_token(token, auth_secret()),
    }


@router.post("/logout")
def logout(
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
) -> dict[str, str]:
    admin, record, _token = context
    record.revoked_at = utc_now()
    _audit(database, admin, "admin.logout")
    database.commit()
    response.delete_cookie(
        COOKIE_NAME, path="/",
        httponly=True, secure=get_settings().app_env in ("staging", "production"),
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"status": "signed_out"}
