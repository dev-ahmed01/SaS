"""Monthly accounting acceptance: precise IST boundaries, partials, credit controls."""
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.accounting import evaluate_status, ist_today, period_balance, shift_month
from app.bootstrap_admin import provision_admin
from app.main import app
from app.models import (
    AuditEvent,
    Base,
    Prospect,
    SponsorshipRate,
    VerifiedCredit,
)
from test_prospects import create as create_prospect, login

@pytest.fixture
def accounting_system(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        provision_admin(
            db, email="office@foundation.org", password="synthetic-long-admin-password",
            organization_name="Emlen Foundation",
        )
    monkeypatch.setattr("app.auth.get_engine", lambda: engine)
    monkeypatch.setattr(
        "app.auth.get_settings",
        lambda: SimpleNamespace(
            auth_secret="synthetic-auth-secret-more-than-thirty-two-characters",
            app_env="test",
        ),
    )
    monkeypatch.setattr(
        "app.prospects.get_settings",
        lambda: SimpleNamespace(
            upi_match_secret="synthetic-independent-upi-hmac-key-for-tests",
        ),
    )
    with TestClient(app) as client:
        yield client, engine
    engine.dispose()


IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 1, 0, 15, tzinfo=IST)
CURRENT_UTC = NOW.astimezone(UTC)


def sponsor(start: date) -> SimpleNamespace:
    return SimpleNamespace(start_month=start)


def rate(start: date, amount: int = 50000) -> SimpleNamespace:
    return SimpleNamespace(effective_month=start, amount_paise=amount)


def credit(month: date, value: int, verified_at: datetime = CURRENT_UTC) -> SimpleNamespace:
    return SimpleNamespace(
        period_month=month, amount_paise=value, verified_at=verified_at,
    )


def test_calendar_arithmetic_and_ist_month_transition():
    assert shift_month(date(2026, 1, 31), -1) == date(2025, 12, 1)
    assert shift_month(date(2024, 2, 29), 1) == date(2024, 3, 1)
    assert ist_today(datetime(2026, 10, 31, 18, 29, tzinfo=UTC)) == date(2026, 10, 31)
    assert ist_today(datetime(2026, 10, 31, 18, 30, tzinfo=UTC)) == date(2026, 11, 1)


def test_two_completed_months_and_reactivation_are_deterministic():
    p = sponsor(date(2026, 9, 1))
    rates = [rate(date(2026, 9, 1))]
    assert evaluate_status(p, rates, [], date(2026, 10, 31), CURRENT_UTC) == "new"
    assert evaluate_status(p, rates, [], date(2026, 11, 1), CURRENT_UTC) == "inactive"
    # Paying October but not September removes consecutive-miss ineligibility.
    october = credit(date(2026, 10, 1), 50000)
    assert evaluate_status(p, rates, [october], date(2026, 11, 1), CURRENT_UTC) == "active"
    # A verified full November payment reactivates immediately.
    november = credit(date(2026, 11, 1), 50000)
    assert evaluate_status(p, rates, [november], date(2026, 11, 1), CURRENT_UTC) == "active"


def test_partial_payment_is_accounted_but_not_falsely_marked_paid():
    p = sponsor(date(2026, 9, 1))
    r = [rate(date(2026, 9, 1))]
    c = [credit(date(2026, 11, 1), 25000)]
    assert period_balance(p, r, c, date(2026, 11, 1), CURRENT_UTC) == (
        50000, 25000, 25000, False
    )
    assert evaluate_status(p, r, c, date(2026, 11, 1), CURRENT_UTC) == "inactive"
    c.append(credit(date(2026, 11, 1), 25000))
    assert evaluate_status(p, r, c, date(2026, 11, 1), CURRENT_UTC) == "active"


def test_registration_does_not_bill_prior_months_and_rate_is_effective_dated():
    p = sponsor(date(2026, 10, 1))
    rates = [rate(date(2026, 10, 1)), rate(date(2026, 11, 1), 70000)]
    assert period_balance(p, rates, [], date(2026, 9, 1), CURRENT_UTC)[0] == 0
    assert period_balance(p, rates, [], date(2026, 10, 1), CURRENT_UTC)[0] == 50000
    assert period_balance(p, rates, [], date(2026, 11, 1), CURRENT_UTC)[0] == 70000
    assert evaluate_status(p, rates, [], date(2026, 11, 1), CURRENT_UTC) == "new"


def test_unverified_or_late_credits_not_counted_in_balance():
    p = sponsor(date(2026, 11, 1))
    rates = [rate(date(2026, 11, 1))]
    next_day = credit(
        date(2026, 11, 1), 50000,
        datetime(2026, 11, 2, tzinfo=UTC),
    )
    assert period_balance(p, rates, [next_day], date(2026, 11, 1), CURRENT_UTC)[1] == 0


def _make_history(client, engine, csrf):
    p = create_prospect(client, csrf).json()
    with Session(engine) as db:
        record = db.get(Prospect, uuid.UUID(p["id"]))
        record.start_month = date(2026, 9, 1)
        record.monthly_contribution_paise = 50000
        rate_row = db.scalars(
            select(SponsorshipRate).where(SponsorshipRate.prospect_id == record.id)
        ).one()
        rate_row.effective_month = date(2026, 9, 1)
        rate_row.amount_paise = 50000
        db.commit()
    return p


def test_overview_is_read_only_zero_verified_and_sync_is_audited(accounting_system, monkeypatch):
    client, engine = accounting_system
    csrf = login(client)
    p = _make_history(client, engine, csrf)
    monkeypatch.setattr("app.accounting.utc_now", lambda: CURRENT_UTC)
    response = client.get("/v1/accounting/overview?month=2026-11")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total_sponsors"] == 1
    assert data["due_paise"] == 50000
    assert data["verified_paise"] == 0
    assert data["outstanding_paise"] == 50000
    assert data["items"][0]["status"] == "inactive"
    assert client.get("/v1/accounting/overview?month=2026-12").status_code == 422
    assert client.get("/v1/accounting/overview?month=notmonth").status_code == 422
    assert client.get("/v1/accounting/overview?limit=120").status_code == 422
    assert client.post("/v1/accounting/refresh-statuses").status_code == 403
    first = client.post("/v1/accounting/refresh-statuses", headers=csrf)
    assert first.status_code == 200, first.text
    assert first.json()["changed"] == 1
    again = client.post("/v1/accounting/refresh-statuses", headers=csrf)
    assert again.status_code == 200
    assert again.json()["changed"] == 0
    with Session(engine) as db:
        record = db.get(Prospect, uuid.UUID(p["id"]))
        assert record.lifecycle_status == "inactive"
        assert record.version == 2
        assert db.scalar(select(func.count()).select_from(
            AuditEvent
        ).where(AuditEvent.action == "prospect.status_recalculated")) == 1


def test_only_verified_evidence_credits_pay_and_reactivate(accounting_system, monkeypatch):
    client, engine = accounting_system
    csrf = login(client)
    p = _make_history(client, engine, csrf)
    monkeypatch.setattr("app.accounting.utc_now", lambda: CURRENT_UTC)
    with Session(engine) as db:
        record = db.get(Prospect, uuid.UUID(p["id"]))
        db.add(VerifiedCredit(
            organization_id=record.organization_id, prospect_id=record.id,
            period_month=date(2026, 11, 1), amount_paise=25000,
            source_type="bank_reconciled", source_key="synthetic-unique-evidence-1",
            verified_at=CURRENT_UTC - timedelta(hours=1),
        ))
        db.commit()
    one = client.get("/v1/accounting/overview?month=2026-11").json()
    assert one["verified_paise"] == 25000
    assert one["outstanding_paise"] == 25000
    assert one["items"][0]["status"] == "inactive"
    with Session(engine) as db:
        record = db.get(Prospect, uuid.UUID(p["id"]))
        db.add(VerifiedCredit(
            organization_id=record.organization_id, prospect_id=record.id,
            period_month=date(2026, 11, 1), amount_paise=25000,
            source_type="bank_reconciled", source_key="synthetic-unique-evidence-2",
            verified_at=CURRENT_UTC - timedelta(minutes=5),
        ))
        db.commit()
    two = client.get("/v1/accounting/overview?month=2026-11").json()
    assert two["fully_paid_sponsors"] == 1
    assert two["items"][0]["status"] == "active"
    assert client.post("/v1/accounting/refresh-statuses", headers=csrf).json()["changed"] == 1


def test_next_month_rate_change_does_not_rewrite_current_due(accounting_system, monkeypatch):
    client, engine = accounting_system
    csrf = login(client)
    monkeypatch.setattr("app.prospects._ist_month", lambda: date(2026, 11, 1))
    monkeypatch.setattr("app.accounting.utc_now", lambda: CURRENT_UTC)
    record = create_prospect(
        client, csrf, monthly_contribution_paise=50000
    ).json()
    path = "/v1/prospects/" + record["id"]
    changed = client.patch(
        path, headers=csrf,
        json={"version": 1, "monthly_contribution_paise": 70000}
    )
    assert changed.status_code == 200, changed.text
    now = client.get("/v1/accounting/overview?month=2026-11").json()
    assert now["due_paise"] == 50000
    with Session(engine) as db:
        schedule = db.scalars(select(SponsorshipRate).order_by(
            SponsorshipRate.effective_month
        )).all()
        assert [(r.effective_month, r.amount_paise) for r in schedule] == [
            (date(2026, 11, 1), 50000), (date(2026, 12, 1), 70000)
        ]
