"""One-time, explicit Admin provisioning. No default credentials or public registration.

Usage: python -m app.bootstrap_admin
Environment: BOOTSTRAP_ORGANIZATION, BOOTSTRAP_ADMIN_EMAIL.
Password is prompted interactively and is never passed through command arguments.
"""

import getpass
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import AdminUser, AuditEvent, Organization, OrganizationSettings
from app.security import hash_password


def provision_admin(
    database: Session, *, email: str, password: str, organization_name: str,
    amount_paise: int = 25000, sponsor_day: int = 5, promoter_day: int = 20,
    inactivity_months: int = 2,
) -> None:
    normalized = email.strip().lower()
    if not normalized or "@" not in normalized or len(normalized) > 320:
        raise ValueError("A valid Admin email is required")
    if not organization_name.strip() or len(organization_name.strip()) > 160:
        raise ValueError("A valid organization name is required")
    if database.scalars(select(AdminUser).limit(1)).first() is not None:
        raise ValueError("Admin already provisioned; use the controlled account recovery process")
    if amount_paise <= 0 or not 1 <= sponsor_day <= 28 or not 1 <= promoter_day <= 28:
        raise ValueError("Invalid initial sponsorship configuration")
    if not 1 <= inactivity_months <= 24:
        raise ValueError("Invalid initial inactivity threshold")
    org = Organization(name=organization_name.strip())
    database.add(org)
    database.flush()
    admin = AdminUser(
        organization_id=org.id, email=normalized,
        password_hash=hash_password(password), is_active=True,
    )
    database.add_all(
        [
            admin,
            OrganizationSettings(
                organization_id=org.id,
                currency_code="INR",
                timezone="Asia/Kolkata",
                default_contribution_paise=amount_paise,
                sponsor_reminder_day=sponsor_day,
                promoter_reminder_day=promoter_day,
                inactivity_months=inactivity_months,
                automation_enabled=False,
            ),
        ]
    )
    database.flush()
    database.add(
        AuditEvent(
            organization_id=org.id, actor_admin_id=admin.id,
            action="admin.provisioned", entity_type="admin_user", entity_id=str(admin.id),
            before_data=None, after_data={"email": normalized},
        )
    )
    database.commit()


def main() -> None:
    email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "")
    org = os.environ.get("BOOTSTRAP_ORGANIZATION", "")
    if not email or not org:
        raise SystemExit("Set BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ORGANIZATION")
    password = getpass.getpass("New Admin password (12+ characters): ")
    confirmation = getpass.getpass("Confirm Admin password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    with Session(get_engine()) as database:
        provision_admin(
            database, email=email, password=password, organization_name=org,
            amount_paise=int(os.environ.get("BOOTSTRAP_AMOUNT_PAISE", "25000")),
            sponsor_day=int(os.environ.get("BOOTSTRAP_SPONSOR_DAY", "5")),
            promoter_day=int(os.environ.get("BOOTSTRAP_PROMOTER_DAY", "20")),
            inactivity_months=int(os.environ.get("BOOTSTRAP_INACTIVITY_MONTHS", "2")),
        )
    print("Admin account provisioned. No password has been printed or stored in plaintext.")


if __name__ == "__main__":
    main()
