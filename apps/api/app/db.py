"""SQLAlchemy connection lifecycle; no schema creation on application startup."""

from functools import lru_cache

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.config import get_settings


def _mysql_staging_engine(url: str) -> Engine:
    """Read-only schema preflight for an existing, disposable trial target."""
    # Import the test-only driver and schema helper only in explicitly guarded
    # staging. Production still uses the unchanged psycopg connection.
    from app.models import Base
    from app.mysql_trial_schema import make_trial_engine

    engine = make_trial_engine(url)
    try:
        with engine.connect() as conn:
            version = str(conn.scalar(text("SELECT VERSION()"))).split("-")[0]
            if not version.startswith("8.4."):
                raise RuntimeError("MySQL staging trial requires MySQL 8.4")
            if conn.scalar(text("SELECT @@session.time_zone")) != "+00:00":
                raise RuntimeError("MySQL staging sessions must use UTC")
            if conn.scalar(text("SELECT @@session.transaction_isolation")) != "READ-COMMITTED":
                raise RuntimeError("MySQL staging requires READ COMMITTED")
            if set(inspect(conn).get_table_names()) != set(Base.metadata.tables):
                raise RuntimeError("MySQL staging schema does not match mapped tables")
            guards = conn.scalar(text("""
                SELECT COUNT(*) FROM information_schema.triggers
                WHERE trigger_schema = DATABASE()
                  AND trigger_name IN ('sas_manual_collection_tier_insert',
                                       'sas_manual_collection_tier_update')
            """))
            if guards != 2:
                raise RuntimeError("MySQL trial financial guards are missing")
            if conn.scalar(text("SELECT @@session.foreign_key_checks")) != 1:
                raise RuntimeError("MySQL foreign-key checks must be enabled")
    except Exception:
        engine.dispose()
        raise
    return engine


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    if settings.mysql_staging_trial_enabled:
        return _mysql_staging_engine(settings.database_url)
    return create_engine(settings.database_url, pool_pre_ping=True)
