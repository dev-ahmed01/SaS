"""Minimal operational probes. Business endpoints require Phase-3 authentication first."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import get_engine
from app.auth import router as auth_router
from app.admin_settings import router as settings_router

app = FastAPI(title="Sponsor a Salah API", version="0.3.0", docs_url=None, redoc_url=None)
app.include_router(auth_router)
app.include_router(settings_router)


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
