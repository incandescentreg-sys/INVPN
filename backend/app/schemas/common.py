"""Shared response envelopes and pagination."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Message(BaseModel):
    detail: str
    ok: bool = True


class ErrorResponse(BaseModel):
    error: str
    code: str
    detail: str


class Page(BaseModel, Generic[T]):  # noqa: UP046 - explicit Generic keeps Pydantic v2 happy
    items: list[T]
    total: int = 0
    limit: int = 50
    offset: int = 0

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total

    @classmethod
    def build(cls, items: list[T], total: int, limit: int, offset: int) -> Page[T]:
        return cls(items=items, total=total, limit=limit, offset=offset)


class PageParams(BaseModel):
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)

    @property
    def as_query(self) -> dict[str, int]:
        return {"limit": self.limit, "offset": self.offset}


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    bot: str
    payment_provider: str
    vpn_servers: list[dict[str, Any]] = Field(default_factory=list)
    detail: dict[str, Any] | None = None
