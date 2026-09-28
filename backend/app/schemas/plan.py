"""Plan (tariff) schemas."""

from __future__ import annotations

import datetime as dt
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel


class PlanRead(ORMModel):
    id: UUID
    code: str
    title: str
    description: str | None = None
    days: int
    price_kopeks: int
    currency: str
    features: list[str] = Field(default_factory=list)
    badge: str | None = None
    is_popular: bool = False
    is_active: bool = True
    sort_order: int = 0
    server_id: UUID | None = None

    @property
    def price_label(self) -> str:
        return f"{self.price_kopeks / 100:.0f} ₽" if self.price_kopeks % 100 == 0 else f"{self.price_kopeks / 100:.2f} ₽"


class PlanCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=32, pattern=r"^[a-z0-9_]+$")
    title: str = Field(..., min_length=1, max_length=128)
    days: int = Field(..., ge=1, le=3650)
    price_kopeks: int = Field(..., ge=0, le=100_000_000)
    currency: str = Field("RUB", min_length=3, max_length=3)
    description: str | None = None
    features: list[str] = Field(default_factory=list)
    badge: str | None = None
    is_popular: bool = False
    is_active: bool = True
    sort_order: int = 0
    server_id: UUID | None = None

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


class PlanUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = None
    days: int | None = Field(None, ge=1, le=3650)
    price_kopeks: int | None = Field(None, ge=0, le=100_000_000)
    features: list[str] | None = None
    badge: str | None = None
    is_popular: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = None
    server_id: UUID | None = None


class PlanWithStats(PlanRead):
    subscriptions_count: int = 0
    revenue_kopeks: int = 0
    created_at: dt.datetime
