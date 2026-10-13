"""Read-only IST monthly accounting, plus audited status materialization.

Only VerifiedCredit rows are counted as collected. Phase 06 deliberately has no
credit-creation API: payment evidence will be assessed in Phases 07-08.
"""
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.auth import db_session, get_admin, require_csrf
from app.models import (
    AdminSession,
    AdminUser,
    AuditEvent,
    ManualCollection,
    ManualCollectionReversal,
    OrganizationSettings,
    Prospect,
    SponsorshipRate,
    VerifiedCredit,
)
from app.security import utc_now

router = APIRouter(prefix="/v1/accounting", tags=["Admin monthly accounting"])
IST = ZoneInfo("Asia/Kolkata")
MAX_PERIODS = 36


def month_start(value: date) -> date:
    return value.replace(day=1)


def shift_month(month: date, delta: int) -> date:
    """Calendar arithmetic: no fixed 30-day approximations."""
    month = month_start(month)
    total = month.year * 12 + month.month - 1 + delta
    year, zero_month = divmod(total, 12)
    if year < 1 or year > 9999:
        raise ValueError("Month exceeds representable range")
    return date(year, zero_month + 1, 1)


def ist_today(now: datetime | None = None) -> date:
    return (now or utc_now()).astimezone(IST).date()


def _month_from_query(value: str | None, today: date) -> date:
    if value is None:
        return month_start(today)
    try:
        if len(value) != 7 or value[4] != "-":
            raise ValueError("Expected YYYY-MM")
        requested = date.fromisoformat(value + "-01")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Use a valid YYYY-MM month") from exc
    if requested > month_start(today) or requested < shift_month(month_start(today), -35):
        raise HTTPException(status_code=422, detail="Month is outside the 36-month history")
    return requested


def effective_credits(
    database: Session, organization_id: object,
    sponsor_id: object | None = None, as_of: datetime | None = None,
) -> list[VerifiedCredit]:
    """Credit rows excluding fully voided manual entries; originals stay auditable.

    This is the shared financial projection used by ledger, manual entry and
    reversal status updates. Other (bank) credits are unaffected.
    """
    voided_credit_ids = (
        select(ManualCollection.verified_credit_id)
        .join(
            ManualCollectionReversal,
            and_(
                ManualCollectionReversal.organization_id == ManualCollection.organization_id,
                ManualCollectionReversal.collection_id == ManualCollection.id,
            ),
        )
        .where(ManualCollection.organization_id == organization_id)
    )
    filters = [
        VerifiedCredit.organization_id == organization_id,
        VerifiedCredit.id.not_in(voided_credit_ids),
    ]
    if sponsor_id is not None:
        filters.append(VerifiedCredit.prospect_id == sponsor_id)
    if as_of is not None:
        filters.append(VerifiedCredit.verified_at <= as_of)
    return list(database.scalars(select(VerifiedCredit).where(*filters)).all())


def _monthly_amount(rates: list[SponsorshipRate], month: date) -> int | None:
    matches = [r for r in rates if r.effective_month <= month]
    return max(matches, key=lambda row: row.effective_month).amount_paise if matches else None


def _verified_sum(
    credits: list[VerifiedCredit], month: date, as_of: datetime
) -> int:
    return sum(
        row.amount_paise for row in credits
        if row.period_month == month and _utc(row.verified_at) <= as_of
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        # SQLite test/runtime fallback: persisted timestamps are UTC.
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def period_balance(
    prospect: Prospect, rates: list[SponsorshipRate],
    credits: list[VerifiedCredit], period: date, now: datetime,
) -> tuple[int, int, int, bool]:
    # Registrations before first payment are valid; months prior to enrollment
    # can never be marked as unpaid.
    start = prospect.start_month
    if start is None or period < start:
        return (0, 0, 0, False)
    if prospect.archived_at is not None:
        final_month = month_start(_utc(prospect.archived_at).astimezone(IST).date())
        if period > final_month:
            # Archival ends new recurring dues without erasing past statements.
            return (0, _verified_sum(credits, period, now), 0, False)
    due = _monthly_amount(rates, period)
    if due is None:
        # Fail closed rather than silently charging an invented amount.
        raise ValueError("Missing effective sponsor rate; migration repair required")
    paid = _verified_sum(credits, period, now)
    remaining = max(0, due - paid)
    return (due, paid, remaining, paid >= due)


def evaluate_status(
    prospect: Prospect, rates: list[SponsorshipRate],
    credits: list[VerifiedCredit], as_of: date, verified_until: datetime,
    inactivity_months: int = 2,
) -> Literal["new", "active", "inactive"]:
    if inactivity_months < 1:
        raise ValueError("Inactivity threshold must be positive")
    current = month_start(as_of)
    start = prospect.start_month
    if start is None or start > current:
        return "new"
    # A fully paid current month immediately reactivates an inactive sponsor.
    if period_balance(prospect, rates, credits, current, verified_until)[3]:
        return "active"
    prior = [shift_month(current, -(i + 1)) for i in range(inactivity_months)]
    if all(
        start <= month and
        not period_balance(prospect, rates, credits, month, verified_until)[3]
        for month in prior
    ):
        return "inactive"
    # A partial payment is accounted for but not represented as a paid month.
    months = 1 + (current.year - start.year) * 12 + current.month - start.month
    has_fully_paid = any(
        period_balance(
            prospect, rates, credits, shift_month(start, i), verified_until
        )[3]
        for i in range(max(0, months))
    )
    return "active" if has_fully_paid else "new"


class AccountingRow(BaseModel):
    prospect_id: str
    name: str
    period_month: date
    status: Literal["new", "active", "inactive", "archived"]
    due_paise: int
    verified_paise: int
    outstanding_paise: int
    fully_paid: bool


class AccountingOverview(BaseModel):
    period_month: date
    as_of: date
    timezone: str
    currency: str
    total_sponsors: int
    due_paise: int
    verified_paise: int
    outstanding_paise: int
    fully_paid_sponsors: int
    new_sponsors: int
    active_sponsors: int
    inactive_sponsors: int
    archived_sponsors: int
    items: list[AccountingRow]
    offset: int
    limit: int


def _load_account(
    db: Session, admin: AdminUser, now: datetime
) -> tuple[OrganizationSettings, list[Prospect],
           dict[str, list[SponsorshipRate]], dict[str, list[VerifiedCredit]]]:
    settings = db.get(OrganizationSettings, admin.organization_id)
    if settings is None:
        raise HTTPException(status_code=503, detail="Organization settings unavailable")
    if settings.timezone != "Asia/Kolkata" or settings.currency_code != "INR":
        raise HTTPException(status_code=409, detail="Unsupported accounting locale")
    sponsors = db.scalars(
        select(Prospect).where(
            Prospect.organization_id == admin.organization_id,
        ).order_by(Prospect.full_name, Prospect.id)
    ).all()
    rates = defaultdict(list)
    for rate in db.scalars(
        select(SponsorshipRate).where(
            SponsorshipRate.organization_id == admin.organization_id
        ).order_by(SponsorshipRate.effective_month)
    ):
        rates[str(rate.prospect_id)].append(rate)
    credits = defaultdict(list)
    for credit in effective_credits(db, admin.organization_id, as_of=now):
        credits[str(credit.prospect_id)].append(credit)
    return settings, sponsors, rates, credits


@router.get("/overview", response_model=AccountingOverview)
def overview(
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(get_admin)],
    database: Annotated[Session, Depends(db_session)],
    month: Annotated[str | None, Query(max_length=7)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AccountingOverview:
    now = utc_now()
    today = ist_today(now)
    period = _month_from_query(month, today)
    settings, sponsors, rates_by_id, credits_by_id = _load_account(
        database, context[0], now
    )
    rows: list[AccountingRow] = []
    totals = dict(due=0, verified=0, outstanding=0, paid=0, new=0, active=0, inactive=0, archived=0)
    for sponsor in sponsors:
        pid = str(sponsor.id)
        rates, credits = rates_by_id[pid], credits_by_id[pid]
        status = ("archived" if sponsor.archived_at is not None else
                  evaluate_status(
                      sponsor, rates, credits, today, now, settings.inactivity_months
                  ))
        due, verified, outstanding, paid = period_balance(
            sponsor, rates, credits, period, now
        )
        # Exclude not-yet-registered sponsors from older statements.
        if sponsor.start_month is None or sponsor.start_month > period:
            continue
        if sponsor.archived_at is not None:
            final_month = month_start(_utc(sponsor.archived_at).astimezone(IST).date())
            if period > final_month and verified == 0:
                continue
        totals["due"] += due
        totals["verified"] += verified
        totals["outstanding"] += outstanding
        totals["paid"] += int(paid)
        totals[status] += 1
        rows.append(AccountingRow(
            prospect_id=pid, name=sponsor.full_name, period_month=period,
            status=status, due_paise=due, verified_paise=verified,
            outstanding_paise=outstanding, fully_paid=paid,
        ))
    response.headers["Cache-Control"] = "no-store"
    return AccountingOverview(
        period_month=period, as_of=today, timezone=settings.timezone,
        currency=settings.currency_code, total_sponsors=len(rows),
        due_paise=totals["due"], verified_paise=totals["verified"],
        outstanding_paise=totals["outstanding"], fully_paid_sponsors=totals["paid"],
        new_sponsors=totals["new"], active_sponsors=totals["active"],
        inactive_sponsors=totals["inactive"],
        archived_sponsors=totals["archived"],
        items=rows[offset:offset + limit], limit=limit, offset=offset,
    )


class StatusSyncResult(BaseModel):
    evaluated: int
    changed: int
    as_of: date


@router.post("/refresh-statuses", response_model=StatusSyncResult)
def refresh_statuses(
    response: Response,
    context: Annotated[tuple[AdminUser, AdminSession, str], Depends(require_csrf)],
    database: Annotated[Session, Depends(db_session)],
) -> StatusSyncResult:
    """Explicit, audited materialization. Scheduled execution is Phase 10."""
    now = utc_now()
    today = ist_today(now)
    admin = context[0]
    # Serialize status refreshes per organization.
    database.scalars(
        select(OrganizationSettings).where(
            OrganizationSettings.organization_id == admin.organization_id
        ).with_for_update()
    ).one()
    settings, sponsors, rates_by_id, credits_by_id = _load_account(
        database, admin, now
    )
    changed = 0
    for sponsor in sponsors:
        if sponsor.archived_at is not None:
            # Archived sponsors remain archived, and are not reminder eligible.
            continue
        pid = str(sponsor.id)
        status = evaluate_status(
            sponsor, rates_by_id[pid], credits_by_id[pid],
            today, now, settings.inactivity_months,
        )
        if sponsor.lifecycle_status == status:
            continue
        original = sponsor.lifecycle_status
        sponsor.lifecycle_status = status
        sponsor.status_updated_at = now
        sponsor.updated_at = now
        sponsor.version += 1
        database.add(AuditEvent(
            organization_id=admin.organization_id,
            actor_admin_id=admin.id,
            action="prospect.status_recalculated",
            entity_type="prospect", entity_id=pid,
            before_data={"status": original},
            after_data={"status": status},
        ))
        changed += 1
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return StatusSyncResult(evaluated=len(sponsors), changed=changed, as_of=today)
