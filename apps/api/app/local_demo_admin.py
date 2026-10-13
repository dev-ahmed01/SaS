"""Explicit one-time localhost-only demo Admin provisioning.

Run: python -m app.local_demo_admin
No secret or password is embedded here. Never use with real Foundation records.
"""

import getpass

from sqlalchemy.orm import Session

from app.bootstrap_admin import provision_admin
from app.config import get_settings
from app.db import get_engine


def main() -> None:
    settings = get_settings()
    # Settings validates that demo mode is confined to development + loopback sas_dev.
    if not settings.local_demo_login_enabled:
        raise SystemExit("Enable LOCAL_DEMO_LOGIN_ENABLED=true in the local API .env only")
    if not settings.auth_secret or len(settings.auth_secret) < 32:
        raise SystemExit("Configure a unique local AUTH_SECRET of at least 32 characters")

    print("Local development only: create username Admin for Emlen Foundation.")
    print("No real donor data or production credentials should exist in this database.")
    password = getpass.getpass("Local Admin password (8+ characters): ")
    confirmation = getpass.getpass("Confirm local Admin password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    with Session(get_engine()) as database:
        provision_admin(
            database,
            email="admin@localhost.invalid",
            password=password,
            organization_name="Emlen Foundation",
            local_demo_short_password=True,
        )
    print("Local Admin created. Sign in using username Admin on localhost:3000.")
    print("This is a development-only account and must never be deployed.")


if __name__ == "__main__":
    main()
