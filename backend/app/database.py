"""Async SQLAlchemy engine/session wiring."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, ClassVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import db_settings


class Base(DeclarativeBase):
    """Declarative base shared by every model."""

    type_annotation_map: ClassVar[dict[Any, Any]] = {}


_engine_kwargs: dict[str, object] = {
    "echo": db_settings.echo,
    "pool_pre_ping": db_settings.pool_pre_ping,
    "future": True,
}

# SQLite (tests) does not support these pool options.
if not db_settings.url.startswith("sqlite"):
    _engine_kwargs.update(
        pool_size=db_settings.pool_size,
        max_overflow=db_settings.max_overflow,
        pool_recycle=db_settings.pool_recycle,
    )

engine = create_async_engine(db_settings.url, **_engine_kwargs)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, rolled back on error."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Standalone transactional scope for workers, seeds and CLI scripts."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    await engine.dispose()
