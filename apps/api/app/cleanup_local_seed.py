"""Preview or remove only the guarded, generated *local* SaS CRM demonstration.

Keep the first generated prospect (index 1), the manually entered Danny Danyal,
and any promoters linked to either protected prospect. All other non-generated
prospects and their relationships are kept unchanged.

From apps/api:
  python -m app.cleanup_local_seed
  python -m app.cleanup_local_seed --apply --confirm-synthetic-only

Before applying, back up the loopback sas_dev database. No hosted or live donor
database is accepted by the CLI. No messages are sent by this utility.
"""
import argparse
import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.models import (
    AdminUser,
    Base,
    CommunicationCampaign,
    CommunicationConsentEvent,
    CommunicationPreparation,
    CommunicationRecipientSnapshot,
    CommunicationRule,
    CommunicationTemplate,
    PayoutPayment,
    PayoutPlan,
    PayoutPlanTerm,
    Promoter,
    PromoterAssignment,
    Prospect,
    ProspectStageDefinition,
    ProspectStageTransition,
    SaasytoCampaignRecipient,
    SaasytoCampaignRun,
    SponsorshipRate,
)
from app.seed_local_crm import (
    SAMPLE_STAGES,
    TOTAL_PROMOTERS,
    TOTAL_PROSPECTS,
    _fixed_uuid,
)

# This is the exact marker written by the opt-in local demo generator.
PROSPECT_MARKER = "SYNTHETIC DEMO DATA — NO REAL CONTRIBUTIONS OR CONTACT CONSENT"
PROMOTER_MARKER = "SYNTHETIC DEMO DATA — DO NOT CONTACT"
DANNY = "danny danyal"
DEMO_RULES = {
    "Demo — Monthly sponsor follow-up",
    "Demo — Promoter notification",
}
DEMO_TEMPLATES = {
    "Demo — Community update",
    "Demo — Sponsorship follow-up",
    "Demo — Promoter update",
    "Demo — Thank you",
}


def _dependents(db: Session, row, *, safe_tables: set[str]) -> list[str]:
    """Detect every FK-backed dependent, including tables added by later phases.

    Only specifically removable seed children are exempt from the check.
    No generic cascades or mass deletes are used.
    """
    failures = []
    table_name = row.__table__.name
    for table in Base.metadata.tables.values():
        if table.name in safe_tables:
            continue
        for key in table.foreign_key_constraints:
            if key.referred_table.name != table_name:
                continue
            conditions = []
            for element in key.elements:
                attr = element.column.name
                if not hasattr(row, attr):
                    raise ValueError(f"Unsupported dependent key: {table.name}.{attr}")
                conditions.append(element.parent == getattr(row, attr))
            if db.scalar(select(func.count()).select_from(table).where(*conditions)):
                failures.append(table.name)
    return sorted(set(failures))


def _external_recipient_evidence(db: Session, organization_id, kind: str, person_id) -> bool:
    """Recipient IDs in these planning tables intentionally have no person FK."""
    for model in (
        CommunicationConsentEvent, CommunicationRecipientSnapshot,
        SaasytoCampaignRecipient,
    ):
        if db.scalar(select(model.id).where(
            model.organization_id == organization_id,
            model.recipient_kind == kind,
            model.recipient_id == person_id,
        ).limit(1)) is not None:
            return True
    return False


def cleanup_synthetic_crm(
    db: Session, organization_id: uuid.UUID, *, apply: bool = False,
) -> dict:
    """Preflight all proposed removals before making any changes.

    The caller controls the transaction; dry run is strictly read-only.
    This does not identify arbitrary externally imported fake-looking rows.
    """
    prospects = list(db.scalars(select(Prospect).where(
        Prospect.organization_id == organization_id,
    )).all())
    dannys = [p for p in prospects if p.full_name.strip().casefold() == DANNY]
    if len(dannys) != 1:
        raise ValueError("Expected exactly one Danny Danyal; refusing ambiguous cleanup")
    danny = dannys[0]

    synthetic = {}
    for index in range(1, TOTAL_PROSPECTS + 1):
        request = _fixed_uuid(organization_id, "prospect", index)
        match = next((p for p in prospects
                      if p.registration_request_id == request), None)
        if match is None:
            continue
        if not (
            match.mobile_number == f"+9160010{index:05d}"
            and match.notes == PROSPECT_MARKER
            and match.full_name.startswith("Demo ")
            and not match.whatsapp_opt_in
        ):
            raise ValueError(f"Seed prospect {index} was modified; refusing removal")
        synthetic[index] = match

    if 1 not in synthetic:
        raise ValueError("First generated prospect is missing; verify the database")
    keep_ids = {synthetic[1].id, danny.id}
    remove_prospects = [p for index, p in synthetic.items()
                        if p.id not in keep_ids]

    assignments = list(db.scalars(select(PromoterAssignment).where(
        PromoterAssignment.organization_id == organization_id,
    )).all())
    remove_ids = {p.id for p in remove_prospects}
    # Preserve all promoters ever connected to retained people, including
    # manual prospects and historical links.
    keep_promoter_ids = {
        a.promoter_id for a in assignments if a.prospect_id not in remove_ids
    }
    synthetic_promoters = []
    for index in range(1, TOTAL_PROMOTERS + 1):
        mobile = f"+9160001{index:05d}"
        row = db.scalar(select(Promoter).where(
            Promoter.organization_id == organization_id,
            Promoter.mobile_number == mobile,
        ))
        if row is None:
            continue
        if not (
            row.full_name.startswith("Demo ")
            and row.email == f"demo.promoter{index:02d}@example.test"
            and row.notes == PROMOTER_MARKER
        ):
            raise ValueError(f"Seed promoter {index} was modified; refusing removal")
        if row.id not in keep_promoter_ids:
            synthetic_promoters.append(row)

    plans = list(db.scalars(select(PayoutPlan).where(
        PayoutPlan.organization_id == organization_id,
    )).all())
    synthetic_plans = [
        p for p in plans
        if p.create_request_id in {
            _fixed_uuid(organization_id, "payout", i) for i in range(1, 21)
        } and p.payee_name.startswith("Demo Payee ")
        and p.notes == "SYNTHETIC DEMO — proposed obligation, NOT money sent"
    ]
    campaigns = list(db.scalars(select(CommunicationCampaign).where(
        CommunicationCampaign.organization_id == organization_id,
    )).all())
    synthetic_campaigns = [
        c for c in campaigns
        if c.request_id in {
            _fixed_uuid(organization_id, "campaign", i) for i in range(1, 4)
        } and c.title.startswith("Demo — Communication plan ")
    ]
    synthetic_rules = list(db.scalars(select(CommunicationRule).where(
        CommunicationRule.organization_id == organization_id,
        CommunicationRule.name.in_(DEMO_RULES),
    )).all())
    templates = list(db.scalars(select(CommunicationTemplate).where(
        CommunicationTemplate.organization_id == organization_id,
        CommunicationTemplate.name.in_(DEMO_TEMPLATES),
    )).all())
    # Do not erase a sample template repurposed for a real campaign or rule.
    removed_campaign_ids = {c.id for c in synthetic_campaigns}
    removed_rule_ids = {r.id for r in synthetic_rules}
    removable_templates = [
        t for t in templates
        if not any(c.template_id == t.id and c.id not in removed_campaign_ids
                   for c in campaigns)
        and not db.scalar(select(CommunicationRule.id).where(
            CommunicationRule.organization_id == organization_id,
            CommunicationRule.template_id == t.id,
            CommunicationRule.id.not_in(removed_rule_ids),
        ).limit(1))
    ]
    sample_names = {name for name, _ in SAMPLE_STAGES}
    stages = list(db.scalars(select(ProspectStageDefinition).where(
        ProspectStageDefinition.organization_id == organization_id,
        ProspectStageDefinition.name.in_(sample_names),
        ProspectStageDefinition.description
        == "Synthetic test stage; configurable and removable",
    )).all())
    removable_stages = [
        stage for stage in stages
        if all(p.pipeline_stage_id != stage.id or p.id in remove_ids
               for p in prospects)
    ]

    # Preflight the entire graph. One guarded failure means no partial cleanup.
    for p in remove_prospects:
        extra = _dependents(db, p, safe_tables={
            "promoter_assignments", "sponsorship_rates", "prospect_stage_transitions",
        })
        if extra or _external_recipient_evidence(db, organization_id, "prospect", p.id):
            raise ValueError(
                f"Seed prospect {p.id} has payment, consent or other history: {extra}"
            )
    for p in synthetic_promoters:
        extra = _dependents(db, p, safe_tables={"promoter_assignments"})
        if extra or _external_recipient_evidence(db, organization_id, "promoter", p.id):
            raise ValueError(f"Seed promoter {p.id} has protected history: {extra}")
    for p in synthetic_plans:
        if db.scalar(select(PayoutPayment.id).where(
            PayoutPayment.organization_id == organization_id,
            PayoutPayment.plan_id == p.id,
        ).limit(1)):
            raise ValueError("Seed payout has real payment evidence")
        extra = _dependents(db, p, safe_tables={"payout_plan_terms"})
        if extra:
            raise ValueError(f"Seed payout has other references: {extra}")
    for c in synthetic_campaigns:
        if (db.scalar(select(CommunicationPreparation.id).where(
            CommunicationPreparation.organization_id == organization_id,
            CommunicationPreparation.campaign_id == c.id,
        ).limit(1)) or db.scalar(select(SaasytoCampaignRun.id).where(
            SaasytoCampaignRun.organization_id == organization_id,
            SaasytoCampaignRun.campaign_id == c.id,
        ).limit(1))):
            raise ValueError("Seed campaign has a recipient review or approved send")
    result = {
        "keep": {
            "first_prospect": synthetic[1].full_name,
            "danny_danyal": danny.full_name,
            "linked_promoters_kept": len(keep_promoter_ids),
        },
        "remove": {
            "prospects": len(remove_prospects),
            "promoters": len(synthetic_promoters),
            "payout_plans": len(synthetic_plans),
            "communication_campaigns": len(synthetic_campaigns),
            "communication_rules": len(synthetic_rules),
            "communication_templates": len(removable_templates),
            "unused_sample_stages": len(removable_stages),
        },
        "applied": apply,
    }
    if not apply:
        return result

    # Delete child-to-parent. No real collection/verified credit/outbox rows
    # are deleted, because their existence already fails the preflight.
    for a in assignments:
        if a.prospect_id in remove_ids:
            db.delete(a)
    for model in (ProspectStageTransition, SponsorshipRate):
        rows = db.scalars(select(model).where(
            model.organization_id == organization_id,
            model.prospect_id.in_(remove_ids),
        )).all() if remove_ids else []
        for row in rows:
            db.delete(row)
    db.flush()
    for p in remove_prospects:
        db.delete(p)
    db.flush()
    for p in synthetic_promoters:
        db.delete(p)

    for plan in synthetic_plans:
        for term in db.scalars(select(PayoutPlanTerm).where(
            PayoutPlanTerm.organization_id == organization_id,
            PayoutPlanTerm.plan_id == plan.id,
        )).all():
            db.delete(term)
    db.flush()
    for plan in synthetic_plans:
        db.delete(plan)
    for rule in synthetic_rules:
        db.delete(rule)
    db.flush()
    for campaign in synthetic_campaigns:
        db.delete(campaign)
    db.flush()
    for template in removable_templates:
        db.delete(template)
    for stage in removable_stages:
        db.delete(stage)
    db.flush()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Guarded local CRM seed cleanup")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-synthetic-only", action="store_true")
    args = parser.parse_args()
    cfg = get_settings()
    if (cfg.app_env != "development" or not cfg.local_demo_login_enabled
            or cfg.messaging_delivery_enabled or cfg.saasyto_delivery_enabled):
        raise SystemExit("Refusing: requires local demo database with all sending disabled")
    if args.apply and not args.confirm_synthetic_only:
        raise SystemExit("Refusing apply without --confirm-synthetic-only")
    # The Settings validator restricts local_demo_login_enabled to
    # loopback sas_dev PostgreSQL. Do not weaken this protection.
    with Session(get_engine()) as db:
        admins = list(db.scalars(select(AdminUser)).all())
        if len(admins) != 1 or admins[0].email != "admin@local.sas.example":
            raise SystemExit("Refusing: not the standalone synthetic Admin database")
        try:
            result = cleanup_synthetic_crm(
                db, admins[0].organization_id, apply=args.apply,
            )
            print("Cleanup preview:", result)
            if args.apply:
                db.commit()
                print("Local synthetic cleanup committed")
            else:
                db.rollback()
                print("Dry run only — nothing deleted")
        except ValueError as exc:
            db.rollback()
            raise SystemExit(f"Cleanup refused: {exc}") from exc


if __name__ == "__main__":
    main()
