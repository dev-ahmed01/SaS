"""MySQL 8.4 *trial-only* schema, isolated from production and Alembic.

Do not point this at InterServer or real donor databases. SQLAlchemy's
PostgreSQL-only partial unique assignment index cannot be copied unmodified:
MySQL would incorrectly forbid historical assignments. The generated nullable
key below provides an equivalent one-current-assignment rule for a trial DB.

No application runtime or production migration uses this module.
"""

import os
import re

from sqlalchemy import (
    Column,
    Computed,
    DateTime,
    Index,
    MetaData,
    String,
    create_engine,
    inspect,
    text,
)
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
        # UTCInstant models compile to DATETIME(6) and convert future
        # offset-bearing writes to UTC. This legacy path catches a new generic
        # DateTime accidentally introduced outside the shared UTC type.
        for column in table.columns:
            if isinstance(column.type, DateTime):
                column.type = MySQLDateTime(fsp=6)
    return result


def make_trial_engine(url: str) -> Engine:
    """Match PostgreSQL READ COMMITTED semantics and UTC for disposable tests.

    MySQL's default REPEATABLE READ can serve stale snapshot reads after
    competing commits, and the server-local timezone can shift NOW() values.
    Production application configuration is intentionally not changed here.
    """
    parsed = make_url(url)
    if parsed.drivername != "mysql+pymysql":
        raise RuntimeError("Trial only supports mysql+pymysql driver")
    if not _TRIAL_NAME.fullmatch(parsed.database or "") or parsed.host not in {
        "127.0.0.1", "localhost",
    }:
        raise RuntimeError("Trial engine must target a disposable loopback database")
    return create_engine(
        url,
        pool_pre_ping=True,
        isolation_level="READ COMMITTED",
        connect_args={"init_command": "SET time_zone = '+00:00'"},
    )


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
        if connection.scalar(text("SELECT @@session.time_zone")) != "+00:00":
            raise RuntimeError("MySQL trial sessions must run in UTC")
        isolation = str(connection.scalar(text("SELECT @@session.transaction_isolation")))
        if isolation.upper().replace("-", " ") != "READ COMMITTED":
            raise RuntimeError("MySQL trial requires READ COMMITTED transactions")
        existing = inspect(connection).get_table_names()
        if existing:
            raise RuntimeError("Trial database must be empty; refusing overwrite")


def _install_financial_guards(engine: Engine) -> None:
    # MySQL DDL auto-commits. This must be executed AFTER a fully verified
    # historical trial copy, never within the data-copy transaction itself.
    with engine.connect() as connection:
        existing = connection.scalar(text("""
            SELECT COUNT(*) FROM information_schema.triggers
            WHERE trigger_schema = DATABASE()
              AND trigger_name IN ('sas_manual_collection_tier_insert',
                                   'sas_manual_collection_tier_update')
        """))
        if existing:
            raise RuntimeError("Trial financial guards already installed or partially applied")
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


def install_trial_financial_guards(engine: Engine) -> None:
    """Post-copy policy restoration, only in an explicitly gated local trial."""
    if (os.environ.get("APP_ENV") != "test"
            or os.environ.get("SAS_MYSQL_TRIAL_ONLY") != "1"
            or os.environ.get("SAS_MYSQL_COPY_TRIAL_ONLY") != "1"):
        raise RuntimeError("Historical-trial financial guards require copy-only gate")
    url = make_url(engine.url)
    if (engine.dialect.name != "mysql"
            or url.host != "127.0.0.1"
            or not _TRIAL_NAME.fullmatch(url.database or "")):
        raise RuntimeError("Refusing financial DDL outside localhost trial")
    with engine.connect() as connection:
        if connection.scalar(text("SELECT DATABASE()")) != url.database:
            raise RuntimeError("MySQL target name changed")
        expected_tables = set(Base.metadata.tables)
        if set(inspect(connection).get_table_names()) != expected_tables:
            raise RuntimeError("Incomplete target schema")
        count = connection.scalar(text("SELECT COUNT(*) FROM manual_collections"))
        if count is None:
            raise RuntimeError("Trial target is not readable")
    _install_financial_guards(engine)


def create_trial_schema(engine: Engine, *, defer_payment_guards: bool = False) -> None:
    """Create an empty disposable schema with or without import-only guards.

    Skipping guards is strictly limited to the offline synthetic copy
    rehearsal; NO production importer or live database path supports it.
    """
    assert_disposable_target(engine)
    if defer_payment_guards and os.environ.get("SAS_MYSQL_COPY_TRIAL_ONLY") != "1":
        raise RuntimeError("Only an isolated historical-copy trial may defer guards")
    trial_metadata().create_all(engine, checkfirst=False)
    if not defer_payment_guards:
        _install_financial_guards(engine)


def main() -> None:
    raw_url = os.environ.get("SAS_MYSQL_TRIAL_URL")
    if not raw_url:
        raise SystemExit("SAS_MYSQL_TRIAL_URL not configured")
    # No credentials or connection URI printed to stdout.
    engine = make_trial_engine(raw_url)
    try:
        create_trial_schema(engine)
    finally:
        engine.dispose()
    print("Isolated empty MySQL trial schema created; no donor data moved")


if __name__ == "__main__":
    main()
