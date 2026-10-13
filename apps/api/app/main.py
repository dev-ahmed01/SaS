"""Operational probes and authenticated Sponsor a Salah business endpoints."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.accounting import router as accounting_router
from app.admin_settings import router as settings_router
from app.auth import router as auth_router
from app.collections import router as collections_router
from app.db import get_engine
from app.payouts import router as payouts_router
from app.promoters import router as promoters_router
from app.prospects import router as prospects_router

app = FastAPI(title="Sponsor a Salah API", version="0.7.0", docs_url=None, redoc_url=None)
app.include_router(auth_router)
app.include_router(settings_router)
app.include_router(prospects_router)
app.include_router(promoters_router)
app.include_router(accounting_router)
app.include_router(collections_router)
app.include_router(payouts_router)


@app.get("/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> JSONResponse:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError, ValueError):
        # Never disclose DSNs, database hostnames or exception details to callers.
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(content={"status": "ready"})
