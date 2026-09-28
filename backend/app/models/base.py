"""Shared model base, UUID type and mixins."""

from __future__ import annotations

import datetime as dt
import enum
import uuid
from typing import Any

from sqlalchemy import CHAR, DateTime, MetaData, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, TypeDecorator

from app.database import Base

# Deterministic constraint names keep Alembic autogenerate diffs stable.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata_obj = MetaData(naming_convention=NAMING_CONVENTION)


class GUID(TypeDecorator):
    """UUID mapped to native ``uuid`` on PostgreSQL and CHAR(36) elsewhere."""
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PGUUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        return value if dialect.name == "postgresql" else str(value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None or isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


def utcnow() -> dt.datetime:
    """Timezone-aware now(). Prefer this over datetime.utcnow()."""
    return dt.datetime.now(dt.UTC)


class TZDateTime(TypeDecorator):
    """`DateTime(timezone=True)` that always yields a UTC-aware value.

    PostgreSQL/asyncpg already return aware datetimes, but SQLite (tests!) and a
    few drivers return naive ones — comparing those with `now(UTC)` raises
    `TypeError`. This normalises on the way in.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, dt.datetime) and value.tzinfo is None:
            return value.replace(tzinfo=dt.UTC)
        return value

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, dt.datetime) and value.tzinfo is None:
            return value.replace(tzinfo=dt.UTC)
        return value


def enum_column(enum_cls: type[enum.Enum], *, length: int | None = None) -> SAEnum:
    """VARCHAR-backed enum that stores the enum *value* (e.g. 'active').

    By default SQLAlchemy persists the member **name** ("ACTIVE"); forcing
    values keeps the database readable and lets raw SQL filters work. It also
    works on SQLite, so tests and production agree.
    """
    members = list(enum_cls)  # type: ignore[call-overload]
    size = length or max((len(str(m.value)) for m in members), default=16)
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=size,
        values_callable=lambda cls: [member.value for member in cls],
        validate_strings=True,
    )


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=utcnow, nullable=False
    )


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)


__all__ = [
    "GUID",
    "JSON",
    "NAMING_CONVENTION",
    "Base",
    "TZDateTime",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "enum_column",
    "metadata_obj",
    "utcnow",
]
