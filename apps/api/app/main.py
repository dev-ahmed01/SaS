"""Operational probes and authenticated Sponsor a Salah business endpoints."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.accounting import router as accounting_router
from app.admin_settings import router as settings_router
from app.auth import router as auth_router
from app.collections import router as collections_router
from app.communication import router as communication_router
from app.communication_bulk_consent import router as communication_bulk_consent_router
from app.communication_results import router as communication_results_router
from app.config import get_settings
from app.dashboard import router as dashboard_router
from app.db import get_engine
from app.messaging import admin_router as messaging_admin_router
from app.messaging import internal_router as messaging_internal_router
from app.payouts import router as payouts_router
from app.promoters import router as promoters_router
from app.prospect_stages import router as prospect_stages_router
from app.prospects import router as prospects_router
from app.reminders import router as reminders_router
from app.saasyto import router as saasyto_router
from app.saasyto_campaigns import admin_router as saasyto_campaigns_admin_router
from app.saasyto_campaigns import internal_router as saasyto_campaigns_internal_router
from app.sponsor_otp import router as sponsor_otp_router

app = FastAPI(title="Sponsor a Salah API", version="0.11.0", docs_url=None, redoc_url=None)


def _expected_migration_heads() -> set[str]:
    """Read the deployed migration scripts, never a hard-coded revision."""
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    return set(ScriptDirectory.from_config(config).get_heads())
app.include_router(auth_router)
app.include_router(settings_router)
app.include_router(prospects_router)
app.include_router(sponsor_otp_router)
app.include_router(prospect_stages_router)
app.include_router(promoters_router)
app.include_router(accounting_router)
app.include_router(collections_router)
app.include_router(payouts_router)
app.include_router(reminders_router)
app.include_router(communication_router)
app.include_router(communication_results_router)
app.include_router(communication_bulk_consent_router)
app.include_router(saasyto_router)
app.include_router(saasyto_campaigns_admin_router)
app.include_router(saasyto_campaigns_internal_router)
app.include_router(messaging_admin_router)
app.include_router(messaging_internal_router)
app.include_router(dashboard_router)


@app.get("/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> JSONResponse:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
            if get_settings().app_env in ("staging", "production"):
                # A responsive DB with old/missing tables must not receive traffic.
                actual = set(
                    connection.execute(text("SELECT version_num FROM alembic_version"))
                    .scalars()
                    .all()
                )
                if not actual or actual != _expected_migration_heads():
                    raise ValueError("Database migrations not at release head")
    except (SQLAlchemyError, OSError, ValueError):
        # Never disclose DSNs, database hostnames or exception details to callers.
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(content={"status": "ready"})
