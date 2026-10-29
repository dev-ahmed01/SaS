"""Fail-closed PostgreSQL -> MySQL *synthetic trial-only* table transfer.

No production deployment may import or call this module. Both databases must
be disposable loopback test databases with explicitly scoped names. The source
is read in one read-only repeatable-read snapshot; the target begins EMPTY
and either commits a fully verified table copy or rolls back all inserted rows.

This is NOT a production migration utility: historical below-tier receipts,
live concurrency, schema migrations, direct provider integrations and release
rollback all still need separately reviewed support.
"""

import base64
import hashlib
import hmac
import json
import math
import os
import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import Connection, Engine, make_url

from app.models import Base
from app.mysql_trial_schema import make_trial_engine

_SOURCE = re.compile(r"sas_pg_trial_[a-z0-9_]{3,48}\Z")
_TARGET = re.compile(r"sas_mysql_trial_[a-z0-9_]{3,48}\Z")
_CHUNK = 250


def _trial_pair_guard(source: Engine, target: Engine) -> None:
    """Refuse real or pre-existing target data BEFORE any transfer attempts."""
    if any(os.environ.get(key) != expected for key, expected in {
        "APP_ENV": "test",
        "SAS_MYSQL_TRIAL_ONLY": "1",
        "SAS_MYSQL_COPY_TRIAL_ONLY": "1",
    }.items()):
        raise RuntimeError("Trial copy requires explicit test-only gates")
    for engine, driver, pattern, port in (
        (source, "postgresql+psycopg", _SOURCE, 5432),
        (target, "mysql+pymysql", _TARGET, 3306),
    ):
        url = make_url(engine.url)
        if (
            url.drivername != driver
            or url.host != "127.0.0.1"
            or url.port != port
            or not pattern.fullmatch(url.database or "")
        ):
            raise RuntimeError("Copy permits disposable loopback databases only")


def _canonical(value: Any) -> Any:
    """Normalize PG aware timestamps and MySQL UTC-naive DATETIME(6) identically."""
    if isinstance(value, datetime):
        instant = (
            value.replace(tzinfo=UTC) if value.tzinfo is None
            else value.astimezone(UTC)
        )
        return {"utc": instant.isoformat(timespec="microseconds")}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    if isinstance(value, uuid.UUID):
        return {"uuid": str(value)}
    if isinstance(value, Decimal):
        return {"decimal": format(value, "f")}
    if isinstance(value, bytes):
        return {"binary": base64.b64encode(value).decode("ascii")}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite source numeric data")
        return {"float": repr(value)}
    if value is None or type(value) in (str, bool, int):
        return value
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, dict) and all(type(key) is str for key in value):
        return {key: _canonical(value[key]) for key in sorted(value)}
    raise ValueError("Unsupported value type for lossless canonical transfer")


def _digest_rows(connection: Connection, table, secret: bytes) -> tuple[int, str]:
    digest = hmac.new(secret, ("sas-mysql-copy-v1:" + table.name + "\n").encode(),
                      hashlib.sha256)
    pk = list(table.primary_key.columns)
    if not pk:
        raise ValueError("Table missing a primary key")
    stream = connection.execute(select(table).order_by(*pk)).mappings()
    count = 0
    for row in stream:
        normalized = {key: _canonical(row[key]) for key in sorted(row)}
        digest.update(json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":")).encode("utf-8") + b"\n")
        count += 1
    return count, digest.hexdigest()


def _utc_mysql_copy(row: dict[str, Any]) -> dict[str, Any]:
    """MySQL DATETIME has no offset: store the same instant as UTC-naive."""
    return {
        key: (value.astimezone(UTC).replace(tzinfo=None)
              if isinstance(value, datetime) and value.tzinfo is not None else value)
        for key, value in row.items()
    }


def transfer_synthetic_snapshot(
    source: Engine, target: Engine, *, hmac_key: bytes,
) -> dict[str, Any]:
    """Copy all mapped data in one target transaction and verify before commit.

    No credentials, names, phones, payments, hashes, or source row data are
    logged or returned. A successful trial is never cutover authorization.
    """
    _trial_pair_guard(source, target)
    if not isinstance(hmac_key, bytes) or len(hmac_key) < 32:
        raise RuntimeError("A separate 32-byte minimum HMAC key is required")

    tables = Base.metadata.sorted_tables
    expected = set(Base.metadata.tables)
    with source.connect() as src:
        # Exactly one immutable snapshot, with no source writes allowed.
        src.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        source_db = src.scalar(text("SELECT current_database()"))
        if source_db != source.url.database:
            raise RuntimeError("PostgreSQL source mismatch")
        if src.scalar(text("SHOW transaction_read_only")) != "on":
            raise RuntimeError("PostgreSQL source is not read-only")
        if src.scalar(text("SHOW transaction_isolation")) != "repeatable read":
            raise RuntimeError("PostgreSQL source snapshot is not stable")
        if set(inspect(src).get_table_names()) != expected:
            raise RuntimeError("PostgreSQL trial schema drift")
        with target.begin() as dst:
            if dst.scalar(text("SELECT DATABASE()")) != target.url.database:
                raise RuntimeError("MySQL destination mismatch")
            if dst.scalar(text("SELECT @@session.time_zone")) != "+00:00":
                raise RuntimeError("MySQL session timezone must be UTC")
            if dst.scalar(text("SELECT @@session.transaction_isolation")) != "READ-COMMITTED":
                raise RuntimeError("MySQL copy requires READ COMMITTED")
            if set(inspect(dst).get_table_names()) != expected:
                raise RuntimeError("MySQL trial schema drift")
            if any(dst.scalar(select(func.count()).select_from(table)) for table in tables):
                raise RuntimeError("MySQL target is not empty; refusing to overwrite")

            signatures = {}
            for table in tables:
                signatures[table.name] = _digest_rows(src, table, hmac_key)
                cursor = src.execute(select(table).order_by(*table.primary_key.columns))
                while chunk := cursor.mappings().fetchmany(_CHUNK):
                    dst.execute(table.insert(), [_utc_mysql_copy(dict(row)) for row in chunk])

            # Read target through the SAME uncommitted transaction. Any
            # mismatch raises and rolls back every inserted target row.
            for table in tables:
                if _digest_rows(dst, table, hmac_key) != signatures[table.name]:
                    raise RuntimeError("Trial migration content mismatch: " + table.name)
            count = sum(pair[0] for pair in signatures.values())

    return {
        "result": "verified_synthetic_copy",
        "tables": len(tables),
        "rows": count,
        "cutover_authorized": False,
    }


def main() -> None:
    if os.environ.get("SAS_MYSQL_COPY_TRIAL_ONLY") != "1":
        raise SystemExit("Synthetic copy disabled")
    pg_url = os.environ.get("SAS_PG_TRIAL_SOURCE_URL", "")
    mysql_url = os.environ.get("SAS_MYSQL_TRIAL_URL", "")
    key = os.environ.get("SAS_MYSQL_TRIAL_HMAC_KEY", "").encode("utf-8")
    # Validate URL structure before opening any network connection.
    source_url, target_url = make_url(pg_url), make_url(mysql_url)
    if not (
        source_url.drivername == "postgresql+psycopg"
        and source_url.host == "127.0.0.1"
        and source_url.port == 5432
        and _SOURCE.fullmatch(source_url.database or "")
        and target_url.drivername == "mysql+pymysql"
        and target_url.host == "127.0.0.1"
        and target_url.port == 3306
        and _TARGET.fullmatch(target_url.database or "")
    ):
        raise SystemExit("Synthetic trial requires two approved loopback databases")
    source = create_engine(pg_url, isolation_level="REPEATABLE READ", pool_pre_ping=True)
    target = make_trial_engine(mysql_url)
    try:
        outcome = transfer_synthetic_snapshot(source, target, hmac_key=key)
    except Exception:
        # Never echo exceptions that might contain SQL params or donor fields.
        raise SystemExit("Synthetic copy rejected; inspect private CI status") from None
    finally:
        source.dispose()
        target.dispose()
    print(json.dumps(outcome, sort_keys=True))


if __name__ == "__main__":
    main()
