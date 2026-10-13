"""Tenant-scoped, read-only operational and financial dashboard."""
from collections import defaultdict
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounting import (
    _load_account,
    evaluate_status,
    ist_today,
    month_start,
    period_balance,
    shift_month,
)
from app.auth import db_session, get_admin
from app.models import (
    AdminSession,
    AdminUser,
    ManualCollection,
    ManualCollectionReversal,
    MessageDispatch,
    MessageOutbox,
    PayoutPayment,
    PayoutPlan,
    PayoutPlanTerm,
    Promoter,
    ReminderBatch,
)
from app.security import as_utc, utc_now

router = APIRouter(prefix="/v1/dashboard", tags=["Admin dashboard"])


class MonthTrend(BaseModel):
    period_month: date
    due_paise: int = 0
    contributions_paise: int = 0
    payout_planned_paise: int = 0
    payout_disbursed_paise: int = 0


class Activity(BaseModel):
    kind: Literal["collection", "reversal", "payout_paid", "payout_plan", "reminder"]
    title: str
    amount_paise: int | None
    at: datetime
    href: str


class Overview(BaseModel):
    as_of_ist: date
    period_month: date
    sponsors_total: int
    sponsors_new: int
    sponsors_active: int
    sponsors_inactive: int
    promoters_active: int
    fully_paid_sponsors: int
    unpaid_sponsors: int
    due_paise: int
    recorded_contributions_paise: int
    outstanding_paise: int
    recurring_payouts_active: int
    payout_planned_paise: int
    payout_disbursed_paise: int
    payout_outstanding_paise: int
    reminder_batches_prepared: int
    acknowledgments_awaiting_setup: int
    whatsapp_deliveries_confirmed: int
    months: list[MonthTrend]
    activity: list[Activity]
    notice: str


def term_at(terms: list[PayoutPlanTerm], month: date) -> str | None:
    eligible = [t for t in terms if t.effective_month <= month]
    return max(eligible, key=lambda t: t.effective_month).status if eligible else None


def obligation(plan: PayoutPlan, terms: list[PayoutPlanTerm], month: date) -> int:
    if plan.start_month > month:
        return 0
    if plan.cadence == "one_time":
        return plan.amount_paise if plan.start_month == month else 0
    return plan.amount_paise if term_at(terms, month) == "active" else 0


def recent_activity(db: Session, org: object) -> list[Activity]:
    """Latest events from the current organization, without banking identifiers."""
    items: list[Activity] = []
    sources = [
        (ManualCollection, "collection", "Contribution recorded", "/collections/all"),
        (ManualCollectionReversal, "reversal", "Collection reversed", "/collections/all"),
        (PayoutPayment, "payout_paid", "Outgoing disbursement attested", "/payouts/all"),
        (PayoutPlan, "payout_plan", "Payout plan created", "/payouts/all"),
        (ReminderBatch, "reminder", "Reminder batch prepared, not sent", "/reminders/whatsapp"),
    ]
    for model, kind, title, href in sources:
        records = db.scalars(
            select(model).where(model.organization_id == org)
            .order_by(model.created_at.desc(), model.id.desc()).limit(8)
        ).all()
        for record in records:
            items.append(Activity(
                kind=kind, title=title,
                amount_paise=getattr(record, "amount_paise", None),
                at=as_utc(record.created_at), href=href,
            ))
    return sorted(items, key=lambda row: (row.at, row.kind), reverse=True)[:8]


@router.get("/overview", response_model=Overview)
def overview(
    response: Response,
    identity: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    db: Annotated[Session, Depends(db_session)],
) -> Overview:
    admin = identity[0]
    org = admin.organization_id
    now = utc_now()
    today = ist_today(now)
    month = month_start(today)
    settings, sponsors, rates, credits = _load_account(db, admin, now)
    months = [
        MonthTrend(period_month=shift_month(month, delta))
        for delta in range(-5, 1)
    ]
    counts = dict(new=0, active=0, inactive=0)
    full = unpaid = outstanding = 0
    for person in sponsors:
        sponsor_rates = rates[str(person.id)]
        sponsor_credits = credits[str(person.id)]
        if person.archived_at is None:
            status = evaluate_status(
                person, sponsor_rates, sponsor_credits, today, now,
                settings.inactivity_months,
            )
            counts[status] += 1
        for item in months:
            period = item.period_month
            if person.start_month is None or person.start_month > period:
                continue
            due, received, remaining, settled = period_balance(
                person, sponsor_rates, sponsor_credits, period, now,
            )
            item.due_paise += due
            item.contributions_paise += received
            if period == month:
                outstanding += remaining
                if due > 0 and settled:
                    full += 1
                elif due > 0 and remaining > 0 and person.archived_at is None:
                    unpaid += 1

    plans = db.scalars(select(PayoutPlan).where(
        PayoutPlan.organization_id == org
    )).all()
    terms_by_id = defaultdict(list)
    for term in db.scalars(select(PayoutPlanTerm).where(
        PayoutPlanTerm.organization_id == org
    )):
        terms_by_id[term.plan_id].append(term)
    for plan in plans:
        for item in months:
            item.payout_planned_paise += obligation(
                plan, terms_by_id[plan.id], item.period_month,
            )
    payments = db.scalars(select(PayoutPayment).where(
        PayoutPayment.organization_id == org
    )).all()
    monthly_paid = defaultdict(int)
    for payment in payments:
        if as_utc(payment.created_at) <= now:
            monthly_paid[payment.period_month] += payment.amount_paise
    for item in months:
        item.payout_disbursed_paise = monthly_paid[item.period_month]

    active_plans = sum(
        1 for p in plans if p.cadence == "recurring"
        and p.start_month <= month
        and term_at(terms_by_id[p.id], month) == "active"
    )
    def count(table, *clauses):
        return db.scalar(select(func.count(table.id)).where(*clauses)) or 0
    current = months[-1]
    response.headers["Cache-Control"] = "no-store"
    return Overview(
        as_of_ist=today, period_month=month,
        sponsors_total=sum(counts.values()),
        sponsors_new=counts["new"], sponsors_active=counts["active"],
        sponsors_inactive=counts["inactive"],
        promoters_active=count(Promoter, Promoter.organization_id == org,
                               Promoter.is_active.is_(True)),
        fully_paid_sponsors=full, unpaid_sponsors=unpaid,
        due_paise=current.due_paise,
        recorded_contributions_paise=current.contributions_paise,
        outstanding_paise=outstanding,
        recurring_payouts_active=active_plans,
        payout_planned_paise=current.payout_planned_paise,
        payout_disbursed_paise=current.payout_disbursed_paise,
        payout_outstanding_paise=max(
            0, current.payout_planned_paise-current.payout_disbursed_paise
        ),
        reminder_batches_prepared=count(
            ReminderBatch, ReminderBatch.organization_id == org,
            ReminderBatch.period_month == month,
        ),
        acknowledgments_awaiting_setup=count(
            MessageOutbox, MessageOutbox.organization_id == org,
            MessageOutbox.status == "awaiting_integration",
            ~select(MessageDispatch.id).where(
                MessageDispatch.organization_id == MessageOutbox.organization_id,
                MessageDispatch.outbox_id == MessageOutbox.id,
            ).exists(),
        ),
        whatsapp_deliveries_confirmed=count(
            MessageDispatch, MessageDispatch.organization_id == org,
            MessageDispatch.status == "delivered",
        ),
        months=months, activity=recent_activity(db, org),
        notice=(
            "Contributions are Admin-attested and exclude reversed entries. "
            "Payout plans are not bank disbursements. WhatsApp delivery is "
            "counted only after authenticated provider confirmation."
        ),
    )
