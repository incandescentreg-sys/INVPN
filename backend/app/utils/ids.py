"""Identifier helpers.

Schemas expose UUID fields as `UUID`, while query/path params always arrive as
strings, so every conversion goes through here.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.utils.exceptions import NotFoundError


def to_uuid(value: Any, *, what: str = "объект") -> uuid.UUID:
    """Accept a UUID or any string/UUID-like value and return a UUID."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise NotFoundError(f"Некорректный идентификатор: {what}") from exc
