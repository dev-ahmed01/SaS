"""UTC instants stored losslessly on PostgreSQL and MySQL.

This type changes *bind/result semantics*, not business calendar dates:
ordinary Date columns continue to represent the IST billing month/date.

PostgreSQL keeps timezone-aware TIMESTAMP WITH TIME ZONE. MySQL DATETIME(6)
cannot encode offsets, so all MySQL binds normalize to UTC and results become
UTC-aware. SQLite keeps its existing compatibility semantics.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.types import TypeDecorator


class UTCInstant(TypeDecorator):
    impl = DateTime
    cache_ok = True
    # Preserve introspection and migration-test expectations of aware instants.
    timezone = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "mysql":
            return dialect.type_descriptor(MySQLDateTime(fsp=6))
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError("UTC instant requires datetime")
        if dialect.name == "mysql":
            # Existing ORM clients use UTC-aware instants, while public
            # scheduled-campaign inputs may contain an explicit IST offset.
            # Naive historic timestamps are canonicalized as UTC.
            instant = (
                value.replace(tzinfo=UTC)
                if value.tzinfo is None else value.astimezone(UTC)
            )
            return instant.replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is None or dialect.name != "mysql":
            return value
        if not isinstance(value, datetime):
            raise TypeError("Unexpected datetime representation")
        return (
            value.replace(tzinfo=UTC)
            if value.tzinfo is None else value.astimezone(UTC)
        )
