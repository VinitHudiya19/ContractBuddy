"""
Cross-database compatible column type mappings (SQLite + PostgreSQL).
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.types import CHAR, Text, TypeDecorator


class GUID(TypeDecorator):
    """Platform-independent GUID type.
    Uses PostgreSQL's UUID type, otherwise uses CHAR(36).
    """
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class JSONBType(TypeDecorator):
    """JSON type decorator that uses JSONB on Postgres and Text on SQLite."""
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB)
        return dialect.type_descriptor(Text)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        try:
            return json.loads(value)
        except Exception:
            return value


class UUIDArray(TypeDecorator):
    """List of UUIDs that uses ARRAY on Postgres and Text (JSON) on SQLite."""
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(UUID(as_uuid=True)))
        return dialect.type_descriptor(Text)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return [v if isinstance(v, uuid.UUID) else uuid.UUID(str(v)) for v in value]
        return json.dumps([str(v) for v in value])

    def process_result_value(self, value, dialect):
        if value is None:
            return []
        if dialect.name == "postgresql":
            return [v if isinstance(v, uuid.UUID) else uuid.UUID(str(v)) for v in value]
        try:
            raw = json.loads(value)
            return [uuid.UUID(str(v)) for v in raw]
        except Exception:
            return []


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()
