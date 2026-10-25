"""CI-only synthetic CRM activation fixture. Never import into app routes.

This is a *test data seeder*, not an authentication or OTP bypass endpoint.
It refuses to run outside the exact disposable GitHub Actions test database.
"""
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import AdminUser, AuditEvent, Prospect, ProspectStageTransition
from app.security import utc_now


def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    parsed = urlsplit(database_url)
    if not (
        os.environ.get("CI", "").lower() == "true"
        and os.environ.get("APP_ENV") == "test"
        and parsed.scheme == "postgresql+psycopg"
        and parsed.hostname in ("localhost", "127.0.0.1")
        and parsed.username == "sas_ci"
        and parsed.path == "/sas_ci"
        and len(sys.argv) == 3
        and sys.argv[2] in ("initial", "return")
    ):
        raise SystemExit("CI-only synthetic activation refused")
    try:
        prospect_id = uuid.UUID(sys.argv[1])
    except ValueError as exc:
        raise SystemExit("Invalid synthetic prospect ID") from exc
    with Session(get_engine()) as db:
        admin = db.scalars(select(AdminUser).where(
            AdminUser.email == "admin@foundation.org",
        )).one()
        person = db.scalars(select(Prospect).where(
            Prospect.id == prospect_id,
            Prospect.organization_id == admin.organization_id,
            Prospect.archived_at.is_(None),
        ).with_for_update()).one()
        if (person.crm_stage != "inactive" or not person.full_name.startswith((
                "Stage Candidate ", "Collection Candidate ", "Seeded History Sponsor ",
                "Browser Sponsor ", "Fresh Sponsor ", "Prospect Test ",
        ))):
            raise SystemExit("Not a permitted synthetic fixture")
        was_active = db.scalar(select(ProspectStageTransition.id).where(
            ProspectStageTransition.prospect_id == person.id,
            ProspectStageTransition.organization_id == admin.organization_id,
            ProspectStageTransition.to_stage == "active",
        ).limit(1)) is not None
        if was_active != (sys.argv[2] == "return"):
            raise SystemExit("Incorrect synthetic transition type")
        now = utc_now()
        person.crm_stage = "active"
        person.crm_stage_changed_at = now
        person.crm_inactive_reason = None
        person.crm_inactive_note = None
        person.version += 1
        person.updated_at = now
        db.add(ProspectStageTransition(
            organization_id=admin.organization_id, prospect_id=person.id,
            from_stage="inactive", to_stage="active",
            reason=None, note="CI synthetic reactivation" if was_active else None,
            actor_admin_id=admin.id, changed_at=now,
        ))
        db.add(AuditEvent(
            organization_id=admin.organization_id, actor_admin_id=admin.id,
            entity_type="prospect", entity_id=str(person.id),
            action="ci.fixture.synthetic_activation",
            after_data={"stage":"active","ci_only": True},
        ))
        db.commit()
    print("synthetic activation fixture applied")


if __name__ == "__main__":
    main()
