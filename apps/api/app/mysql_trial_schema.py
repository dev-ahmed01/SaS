"""MySQL 8.4 *trial-only* schema, isolated from production and Alembic.

Do not point this at InterServer or real donor databases. SQLAlchemy's
PostgreSQL-only partial unique assignment index cannot be copied unmodified:
MySQL would incorrectly forbid historical assignments. The generated nullable
key below provides an equivalent one-current-assignment rule for a trial DB.

No application runtime or production migration uses this module.
"""

import os
import re

from sqlalchemy import Column, Computed, DateTime, Index, MetaData, String, create_engine, inspect, text
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.engine import Engine, make_url

from app.models import Base

_TRIAL_NAME = re.compile(r"sas_mysql_trial_[a-z0-9_]{3,48}\Z")
_PARTIAL_INDEX = "uq_assignment_current_prospect"
_GENERATED = "mysql_current_prospect_id"
_MYSQL_INDEX = "uq_mysql_assignment_current_prospect"


def trial_metadata() -> MetaData:
    """Create a detached candidate schema without changing ORM metadata."""
    result = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(result)

    assignments = result.tables["promoter_assignments"]
    legacy = [i for i in assignments.indexes if i.name == _PARTIAL_INDEX]
    if len(legacy) != 1:
        raise AssertionError("PostgreSQL current-assignment index changed")
    assignments.indexes.remove(legacy[0])

    assignments.append_column(
        Column(
            _GENERATED,
            String(32),
            Computed("CASE WHEN ended_at IS NULL THEN prospect_id ELSE NULL END",
                     persisted=True),
            nullable=True,
        )
    )
    Index(
        _MYSQL_INDEX,
        assignments.c.organization_id,
        assignments.c[_GENERATED],
        unique=True,
    )

    # Force transactional FK enforcement and explicit case-sensitive text
    # comparison rather than relying on server-specific defaults.
    for table in result.tables.values():
        table.dialect_options["mysql"]["engine"] = "InnoDB"
        table.dialect_options["mysql"]["charset"] = "utf8mb4"
        table.dialect_options["mysql"]["collate"] = "utf8mb4_0900_as_cs"
        # Generic SQLAlchemy DateTime compiles to MySQL DATETIME(0), which
        # silently truncates historical PostgreSQL microseconds. Preserve
        # six fractional digits in the detached candidate schema only.
        for column in table.columns:
            if isinstance(column.type, DateTime):
                column.type = MySQLDateTime(fsp=6)
    return result


def assert_disposable_target(engine: Engine) -> None:
    """Fail closed before any DDL; no production DB may be touched."""
    if os.environ.get("APP_ENV") != "test" or os.environ.get(
        "SAS_MYSQL_TRIAL_ONLY"
    ) != "1":
        raise RuntimeError("Disposable MySQL trial requires explicit test-only gate")
    if engine.dialect.name != "mysql":
        raise RuntimeError("Trial requires MySQL engine")
    url = make_url(engine.url)
    database = url.database or ""
    if not _TRIAL_NAME.fullmatch(database) or not url.host:
        raise RuntimeError("Refusing non-trial database or socket")
    if url.host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("Trial must use loopback MySQL only")
    with engine.connect() as connection:
        actual_db = connection.scalar(text("SELECT DATABASE()"))
        if actual_db != database:
            raise RuntimeError("Connected database does not match trial DB")
        version = str(connection.scalar(text("SELECT VERSION()"))).split("-")[0]
        if not version.startswith("8.4."):
            raise RuntimeError("Trial is pinned to MySQL 8.4, got incompatible version")
        existing = inspect(connection).get_table_names()
        if existing:
            raise RuntimeError("Trial database must be empty; refusing overwrite")


def create_trial_schema(engine: Engine) -> None:
    """Create disposable schema after all preflight checks; no data transfer."""
    assert_disposable_target(engine)
    trial_metadata().create_all(engine, checkfirst=False)
    # Live PostgreSQL permits older, below-tier entries but blocks NEW ones.
    # MySQL table-level CHECK would reject those historical receipts on copy,
    # so matching triggers are installed on a fresh trial database instead.
    # Later import tooling must install these only AFTER historical import.
    with engine.begin() as connection:
        connection.exec_driver_sql("""
            CREATE TRIGGER sas_manual_collection_tier_insert
            BEFORE INSERT ON manual_collections FOR EACH ROW
            BEGIN
                IF NEW.amount_paise < 25000
                   OR NEW.amount_paise > 1000000000
                   OR MOD(NEW.amount_paise, 25000) <> 0 THEN
                    SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'Collection must be in INR 250 increments';
                END IF;
            END
        """)
        connection.exec_driver_sql("""
            CREATE TRIGGER sas_manual_collection_tier_update
            BEFORE UPDATE ON manual_collections FOR EACH ROW
            BEGIN
                IF NEW.amount_paise <> OLD.amount_paise
                   AND (NEW.amount_paise < 25000
                        OR NEW.amount_paise > 1000000000
                        OR MOD(NEW.amount_paise, 25000) <> 0) THEN
                    SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'Collection must be in INR 250 increments';
                END IF;
            END
        """)


def main() -> None:
    raw_url = os.environ.get("SAS_MYSQL_TRIAL_URL")
    if not raw_url:
        raise SystemExit("SAS_MYSQL_TRIAL_URL not configured")
    parsed = make_url(raw_url)
    if parsed.drivername != "mysql+pymysql":
        raise SystemExit("Trial only supports mysql+pymysql driver")
    # No credentials or connection URI printed to stdout.
    engine = create_engine(raw_url, pool_pre_ping=True)
    try:
        create_trial_schema(engine)
    finally:
        engine.dispose()
    print("Isolated empty MySQL trial schema created; no donor data moved")


if __name__ == "__main__":
    main()
