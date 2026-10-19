"""Opt-in synthetic CRM dataset for loopback local development only.

From apps/api, run:
  python -m app.seed_local_crm              # report only
  python -m app.seed_local_crm --apply --confirm-synthetic-only

Never use real phones, donor identities, external message delivery, or money receipts.
The command is idempotent: existing demo rows are not duplicated.
"""

import argparse
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounting import month_start
from app.config import get_settings
from app.db import get_engine
from app.models import (
    AdminUser,
    AuditEvent,
    PayoutPlan,
    PayoutPlanTerm,
    Promoter,
    PromoterAssignment,
    Prospect,
    ProspectStageDefinition,
    ProspectStageTransition,
    SponsorshipRate,
)

TOTAL_PROSPECTS = 100
TOTAL_PROMOTERS = 10
FIRST_NAMES = (
    "Aisha", "Omar", "Sara", "Zoya", "Bilal", "Nadia", "Yusuf", "Hana", "Ibrahim",
    "Amira", "Zain", "Mariam", "Farhan", "Sana", "Hamza", "Riya", "Arman", "Alina",
    "Faizan", "Inaya",
)
LAST_NAMES = ("Khan", "Ali", "Rahman", "Noor", "Hassan", "Sheikh", "Ansari", "Ahmed")
CITIES = ("Bengaluru", "Mysuru", "Mangaluru", "Hyderabad", "Chennai", "Pune", "Delhi")
OCCUPATIONS = ("Teacher", "Engineer", "Designer", "Accountant", "Entrepreneur")
INACTIVE_REASONS = ("budget", "timing", "not_interested", "unreachable", "other")
# These labels belong to an opt-in DEMO dataset, never to default application config.
SAMPLE_STAGES = (
    ("Demo — New enquiry", "#64748b"),
    ("Demo — Contacted", "#2563eb"),
    ("Demo — Interested", "#16a34a"),
    ("Demo — Follow-up", "#ea580c"),
)


def _fixed_uuid(organization_id: uuid.UUID, kind: str, number: int) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"emlen-synthetic-v1:{organization_id}:{kind}:{number}")


def seed_synthetic_crm(
    database: Session, organization_id: uuid.UUID, admin_id: uuid.UUID,
) -> dict[str, int]:
    """Create missing deterministic demo records in a single caller-managed transaction."""
    now = datetime.now(UTC)
    month = month_start(now.astimezone(ZoneInfo("Asia/Kolkata")).date())
    created = {
        "prospects": 0, "promoters": 0, "stage_definitions": 0,
        "assignments": 0, "stage_events": 0, "payout_plans": 0,
    }
    stage_defs = list(database.scalars(
        select(ProspectStageDefinition).where(
            ProspectStageDefinition.organization_id == organization_id,
        ).order_by(
            ProspectStageDefinition.sort_order, ProspectStageDefinition.name_key,
        )
    ).all())
    if not stage_defs:
        for index, (name, color) in enumerate(SAMPLE_STAGES):
            stage = ProspectStageDefinition(
                organization_id=organization_id,
                name=name, name_key=name.casefold(), color=color,
                description="Synthetic test stage; configurable and removable",
                sort_order=index, version=1,
            )
            database.add(stage)
            stage_defs.append(stage)
            created["stage_definitions"] += 1
        database.flush()

    promoters = []
    for index in range(1, TOTAL_PROMOTERS + 1):
        mobile = f"+9160001{index:05d}"
        existing = database.scalar(select(Promoter).where(
            Promoter.organization_id == organization_id,
            Promoter.mobile_number == mobile,
        ))
        if existing:
            if not existing.full_name.startswith("Demo "):
                raise ValueError("Synthetic promoter phone collides with an existing record")
            promoters.append(existing)
            continue
        first = FIRST_NAMES[(index * 3) % len(FIRST_NAMES)]
        last = LAST_NAMES[index % len(LAST_NAMES)]
        person = Promoter(
            organization_id=organization_id,
            full_name=f"Demo {first} {last}",
            first_name=f"Demo {first}", last_name=last,
            mobile_number=mobile, whatsapp_number=None,
            email=f"demo.promoter{index:02d}@example.test",
            area_city=CITIES[index % len(CITIES)],
            occupation=OCCUPATIONS[index % len(OCCUPATIONS)],
            notes="SYNTHETIC DEMO DATA — DO NOT CONTACT",
            whatsapp_opt_in=False, is_active=True, version=1,
            created_at=now - timedelta(days=index * 5),
        )
        database.add(person)
        promoters.append(person)
        created["promoters"] += 1
    database.flush()

    for index in range(1, TOTAL_PROSPECTS + 1):
        request_id = _fixed_uuid(organization_id, "prospect", index)
        if database.scalar(select(Prospect.id).where(
            Prospect.organization_id == organization_id,
            Prospect.registration_request_id == request_id,
        )):
            continue
        mobile = f"+9160010{index:05d}"
        if database.scalar(select(Prospect.id).where(
            Prospect.organization_id == organization_id,
            Prospect.mobile_number == mobile,
        )):
            raise ValueError("Synthetic prospect phone collides with an existing record")
        first = FIRST_NAMES[index % len(FIRST_NAMES)]
        last = LAST_NAMES[(index // len(FIRST_NAMES)) % len(LAST_NAMES)]
        amount_paise = (1 + index % 8) * 25000
        is_inactive = index % 4 == 0
        changed_at = now - timedelta(days=5 + (index * 7) % 85) if is_inactive else None
        created_at = now - timedelta(days=100 + index)
        reason = INACTIVE_REASONS[index % len(INACTIVE_REASONS)] if is_inactive else None
        prospect = Prospect(
            organization_id=organization_id,
            full_name=f"Demo {first} {last}",
            first_name=f"Demo {first}", last_name=last,
            mobile_number=mobile, whatsapp_number=None,
            email=f"demo.prospect{index:03d}@example.test",
            area_city=CITIES[index % len(CITIES)],
            occupation=OCCUPATIONS[index % len(OCCUPATIONS)],
            monthly_contribution_paise=amount_paise,
            start_month=month, pipeline_stage_id=stage_defs[index % len(stage_defs)].id,
            lifecycle_status="new", status_updated_at=now,
            crm_stage="inactive" if is_inactive else "active",
            crm_stage_changed_at=changed_at,
            crm_inactive_reason=reason,
            crm_inactive_note="Synthetic CRM status example" if is_inactive else None,
            registration_request_id=request_id,
            notes="SYNTHETIC DEMO DATA — NO REAL CONTRIBUTIONS OR CONTACT CONSENT",
            whatsapp_opt_in=False, version=1,
            created_at=created_at, updated_at=now,
        )
        database.add(prospect)
        database.flush()
        database.add(SponsorshipRate(
            organization_id=organization_id, prospect_id=prospect.id,
            effective_month=month, amount_paise=amount_paise,
        ))
        if is_inactive:
            database.add(ProspectStageTransition(
                organization_id=organization_id, prospect_id=prospect.id,
                from_stage="active", to_stage="inactive", reason=reason,
                note="Synthetic inactivity example", changed_at=changed_at,
                actor_admin_id=admin_id,
            ))
            created["stage_events"] += 1
        if index % 5 != 0:
            database.add(PromoterAssignment(
                organization_id=organization_id,
                prospect_id=prospect.id,
                promoter_id=promoters[index % len(promoters)].id,
                assigned_at=created_at, assigned_by_admin_id=admin_id,
            ))
            created["assignments"] += 1
        created["prospects"] += 1

    # Forecast-only commitments. No outgoing disbursements are fabricated.
    for index in range(1, 21):
        request_id = _fixed_uuid(organization_id, "payout", index)
        existing = database.scalar(select(PayoutPlan.id).where(
            PayoutPlan.organization_id == organization_id,
            PayoutPlan.create_request_id == request_id,
        ))
        if existing:
            continue
        kind = "recurring" if index <= 12 else "one_time"
        day = date(month.year, month.month, min(25, 4 + index))
        plan = PayoutPlan(
            organization_id=organization_id, create_request_id=request_id,
            create_hash="0" * 64,
            payee_name=f"Demo Payee {index:02d}",
            purpose=("Synthetic monthly facility support" if kind == "recurring"
                     else "Synthetic one-time equipment support"),
            notes="SYNTHETIC DEMO — proposed obligation, NOT money sent",
            cadence=kind, start_month=month,
            scheduled_on=day if kind == "one_time" else None,
            amount_paise=(index % 8 + 1) * 50000,
            created_by_admin_id=admin_id,
        )
        database.add(plan)
        database.flush()
        database.add(PayoutPlanTerm(
            organization_id=organization_id, plan_id=plan.id,
            effective_month=month, status="active",
            recorded_by_admin_id=admin_id,
        ))
        created["payout_plans"] += 1

    if any(created.values()):
        database.add(AuditEvent(
            organization_id=organization_id, actor_admin_id=admin_id,
            action="local_demo.crm_seeded", entity_type="organization",
            entity_id=str(organization_id), before_data=None,
            after_data={"synthetic": True, "created": created},
        ))
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic prospects for local demo only")
    parser.add_argument("--apply", action="store_true", help="Insert synthetic records")
    parser.add_argument(
        "--confirm-synthetic-only", action="store_true",
        help="Confirm this local database contains no real donor records",
    )
    args = parser.parse_args()
    settings = get_settings()
    if (
        settings.app_env != "development"
        or not settings.local_demo_login_enabled
        or settings.messaging_delivery_enabled
    ):
        raise SystemExit("Refusing: demo-only database and disabled messaging required")
    with Session(get_engine()) as database:
        admins = list(database.scalars(select(AdminUser)).all())
        if (
            len(admins) != 1
            or admins[0].email != "admin@local.sas.example"
            or not admins[0].is_active
        ):
            raise SystemExit("Refusing: expected only the local-demo Admin account")
        admin = admins[0]
        count = database.scalar(select(func.count(Prospect.id)).where(
            Prospect.organization_id == admin.organization_id,
        )) or 0
        print(f"Current prospect rows: {count}; target new demo rows: {TOTAL_PROSPECTS}")
        if not args.apply:
            print("Dry run. No records created. Use --apply --confirm-synthetic-only.")
            return
        if not args.confirm_synthetic_only:
            raise SystemExit("Refusing without --confirm-synthetic-only")
        created = seed_synthetic_crm(
            database, admin.organization_id, admin.id,
        )
        database.commit()
        print("Created synthetic demo records:", created)
        print(
            "No collection receipts, verified credits, payout disbursements, "
            "or WhatsApp consent created."
        )
        print("Rerunning this command will not duplicate demo prospects.")


if __name__ == "__main__":
    main()
