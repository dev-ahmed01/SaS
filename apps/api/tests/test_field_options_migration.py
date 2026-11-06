"""Migration 0027 imports previous payout purposes without rewriting evidence."""
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import OrganizationFieldOption, PayoutPlan


def test_historical_payout_purposes_are_preserved_on_upgrade(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    url = "sqlite+pysqlite:///" + str(tmp_path / "old-payouts.sqlite")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.chdir(root)
    get_settings.cache_clear()
    cfg = Config(str(root / "alembic.ini"))
    try:
        command.upgrade(cfg, "0026_admin_roles")
        org_id = uuid.uuid4()
        first_id,second_id = uuid.uuid4(),uuid.uuid4()
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO organizations (id, name)
                VALUES (:id, 'Legacy Payout Organization')
            """), {"id": org_id.hex})
            for plan_id,label in [
                (first_id,"Historical facility upkeep"),
                (second_id,"Rent"),
            ]:
                conn.execute(text("""
                    INSERT INTO payout_plans (
                        id,organization_id,create_request_id,create_hash,
                        payee_name,purpose,cadence,amount_paise,start_month
                    ) VALUES (
                        :id,:org,:request_id,:digest,:payee,:purpose,
                        'recurring',50000,'2026-10-01'
                    )
                """), {
                    "id":plan_id.hex, "org":org_id.hex,
                    "request_id":uuid.uuid4().hex, "digest":"a"*64,
                    "payee":"Historical payee", "purpose":label,
                })
        engine.dispose()

        command.upgrade(cfg, "head")
        engine = create_engine(url)
        with Session(engine) as db:
            rows=list(db.scalars(select(PayoutPlan).order_by(PayoutPlan.purpose)).all())
            assert {r.purpose for r in rows} == {
                "Historical facility upkeep", "Rent",
            }
            choices=list(db.scalars(select(OrganizationFieldOption).where(
                OrganizationFieldOption.organization_id == org_id
            )).all())
            labels={x.label for x in choices}
            assert "Historical facility upkeep" in labels
            assert {"Rent","Utilities","Maintenance","Other"} <= labels
            for row in rows:
                option=next((x for x in choices if x.id==row.purpose_option_id),None)
                assert option is not None
                assert option.label == row.purpose
        engine.dispose()
        command.check(cfg)
    finally:
        get_settings.cache_clear()
