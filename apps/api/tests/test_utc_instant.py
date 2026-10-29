"""Time conversion regression contract for PostgreSQL and MySQL.

No database connections are needed for these checks.
"""

from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.schema import CreateTable

from app.models import Base
from app.utc_instant import UTCInstant


def test_all_59_timestamp_columns_have_mysql_utc_mapping():
    time_columns = [
        col
        for table in Base.metadata.tables.values()
        for col in table.columns
        if isinstance(col.type, UTCInstant)
    ]
    assert len(time_columns) == 59
    for column in time_columns:
        compiled = column.type.compile(dialect=mysql.dialect())
        assert compiled == "DATETIME(6)"


def test_offset_bearing_campaign_datetime_roundtrips_exactly():
    column_type = UTCInstant()
    value = datetime(
        2026, 11, 5, 9, 15, 40, 654321,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )
    stored = column_type.process_bind_param(value, mysql.dialect())
    assert stored == datetime(2026, 11, 5, 3, 45, 40, 654321)
    recovered = column_type.process_result_value(stored, mysql.dialect())
    assert recovered == value.astimezone(UTC)
    assert recovered.tzinfo == UTC
    assert recovered.microsecond == 654321


def test_sqlite_and_postgres_remain_compatible_with_current_timestamp_contract():
    value = datetime(2026, 10, 28, 18, 2, 5, 123456, tzinfo=UTC)
    field = UTCInstant()
    assert field.compile(dialect=postgresql.dialect()) == "TIMESTAMP WITH TIME ZONE"
    assert field.process_bind_param(value, postgresql.dialect()) == value
    assert field.process_result_value(value, postgresql.dialect()) == value
    assert field.process_bind_param(value, sqlite.dialect()) == value
    assert field.process_result_value(value.replace(tzinfo=None), sqlite.dialect()) == (
        value.replace(tzinfo=None)
    )
    # Unchanged PostgreSQL constraints may continue to use migrations 0001–0024.
    assert "TIMESTAMP WITH TIME ZONE" in str(
        CreateTable(Base.metadata.tables["sponsor_otp_challenges"])
        .compile(dialect=postgresql.dialect())
    )


def test_mysql_naive_legacy_timestamps_treated_as_utc_and_not_local_time():
    field = UTCInstant()
    naive = datetime(2026, 11, 5, 3, 45, 40, 123456)
    assert field.process_bind_param(naive, mysql.dialect()) == naive
    assert field.process_result_value(naive, mysql.dialect()) == naive.replace(tzinfo=UTC)
    assert field.process_result_value(None, mysql.dialect()) is None
