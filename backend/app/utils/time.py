"""Timezone-aware date helpers. The whole codebase stores UTC-aware datetimes."""

from __future__ import annotations

import datetime as dt

UTC = dt.UTC


def now() -> dt.datetime:
    return dt.datetime.now(UTC)


def ensure_aware(value: dt.datetime | None) -> dt.datetime | None:
    """PostgreSQL may hand back naive datetimes depending on driver settings."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def add_days(value: dt.datetime, days: int) -> dt.datetime:
    return value + dt.timedelta(days=days)


def add_months(value: dt.datetime, months: int) -> dt.datetime:
    """Calendar-month arithmetic, clamped to the last valid day."""
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, _days_in_month(year, month))
    return value.replace(year=year, month=month, day=day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (dt.date(year, month + 1, 1) - dt.date(year, month, 1)).days


def days_between(start: dt.datetime, end: dt.datetime) -> int:
    return (end - start).days


def is_within(value: dt.datetime, seconds: int) -> bool:
    return abs((now() - value).total_seconds()) <= seconds


def to_local(value: dt.datetime | None, offset_hours: int = 3) -> dt.datetime | None:
    """MSK by default — the only timezone our users care about."""
    if value is None:
        return None
    tz = dt.timezone(dt.timedelta(hours=offset_hours))
    return value.astimezone(tz)
