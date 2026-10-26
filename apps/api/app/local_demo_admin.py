"""Explicit localhost-only Admin setup and recovery.

Run: python -m app.local_demo_admin [--reset]
The selected password is entered at a hidden terminal prompt, never stored in
source or shell history. Never use with live Foundation records.
"""

import argparse
import getpass

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.bootstrap_admin import provision_admin
from app.config import get_settings
from app.db import get_engine
from app.models import AdminLoginAttempt, AdminSession, AdminUser, AuditEvent
from app.security import PASSWORD_HASHER, utc_now


LOCAL_ADMIN_EMAIL = "admin@local.sas.example"


def recover_local_demo_admin(database: Session, password: str) -> str:
    """Re-establish the Admin alias in a protected localhost demo DB only.

    An existing sole Admin is updated in place so prospects, audit history and
    organization-scoped records are retained. Existing sessions are revoked.
    Reject multi-Admin databases; never reset a guessed production account.
    """
    settings = get_settings()
    if settings.app_env != "development" or not settings.local_demo_login_enabled:
        raise ValueError("Admin recovery is restricted to guarded local demo mode")
    if not settings.auth_secret or len(settings.auth_secret) < 32:
        raise ValueError("Local demo AUTH_SECRET must be at least 32 characters")
    if not 8 <= len(password) <= 128:
        raise ValueError("Local demo password must be 8 to 128 characters")

    admins = database.scalars(select(AdminUser).limit(2)).all()
    if len(admins) > 1:
        raise ValueError("Local demo recovery refuses databases with multiple Admin accounts")
    if not admins:
        provision_admin(
            database,
            email=LOCAL_ADMIN_EMAIL,
            password=password,
            organization_name="Emlen Foundation",
            local_demo_short_password=True,
        )
        return "created"

    admin = admins[0]
    admin.email = LOCAL_ADMIN_EMAIL
    admin.password_hash = PASSWORD_HASHER.hash(password)
    admin.is_active = True
    now = utc_now()
    database.execute(
        update(AdminSession).where(
            AdminSession.admin_user_id == admin.id,
            AdminSession.revoked_at.is_(None),
        ).values(revoked_at=now)
    )
    # This is only the localhost demo database; clear prior failed sign-in
    # throttles so newly recovered credentials can be tested immediately.
    database.execute(delete(AdminLoginAttempt))
    database.add(AuditEvent(
        organization_id=admin.organization_id,
        actor_admin_id=admin.id,
        action="admin.local_demo_credentials_recovered",
        entity_type="admin_user",
        entity_id=str(admin.id),
        after_data={"username": "Admin", "sessions_revoked": True},
    ))
    database.commit()
    return "reset"


def main() -> None:
    parser = argparse.ArgumentParser(description="Local demo Admin bootstrap/recovery")
    parser.add_argument(
        "--reset", action="store_true",
        help="Create or recover username Admin on the protected localhost demo DB",
    )
    args = parser.parse_args()

    settings = get_settings()
    # Settings enforces development + protected loopback sas_dev when this
    # flag is enabled. No aliases or short passwords exist in production.
    if not settings.local_demo_login_enabled:
        raise SystemExit("Enable LOCAL_DEMO_LOGIN_ENABLED=true in the local API .env only")
    if not settings.auth_secret or len(settings.auth_secret) < 32:
        raise SystemExit("Configure a unique local AUTH_SECRET of at least 32 characters")

    print("Local development only: username Admin for Emlen Foundation.")
    print("Only run against your private demo database, never live Foundation records.")
    password = getpass.getpass("Local Admin password (8+ characters): ")
    confirmation = getpass.getpass("Confirm local Admin password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")

    with Session(get_engine()) as database:
        if args.reset:
            try:
                outcome = recover_local_demo_admin(database, password)
            except ValueError as exc:
                raise SystemExit(str(exc)) from None
        else:
            provision_admin(
                database,
                email=LOCAL_ADMIN_EMAIL,
                password=password,
                organization_name="Emlen Foundation",
                local_demo_short_password=True,
            )
            outcome = "created"
    print(
        "Local Admin " + outcome + ". Sign in using username Admin on localhost. "
        "Any prior local Admin sessions were invalidated on reset."
    )


if __name__ == "__main__":
    main()
