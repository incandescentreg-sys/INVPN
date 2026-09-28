"""Alembic environment.

Online migrations run through the *async* engine (asyncpg) and are applied with
`connection.run_sync(...)`, which is the standard Alembic async recipe — no
sync driver such as psycopg2 needs to be installed.

Offline mode (`alembic upgrade head --sql`) uses a synchronised DSN instead,
because it only renders SQL text.
"""

from __future__ import annotations

import asyncio
import re
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import db_settings
from app.models import Base  # noqa: F401 - importing registers every table

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def render_item(type_: str, obj: object, autogen_context: Any) -> str | bool:
    """Emit an import for our custom column types (GUID, etc.)."""
    if type_ == "type":
        autogen_context.imports.add("import app.models.base")
        return f"app.models.base.{obj.__class__.__name__}()"
    return False


def _sync_url(url: str) -> str:
    """Strip the async driver so the DSN can be rendered offline."""
    url = url.replace("+asyncpg", "").replace("+aiosqlite", "")
    url = re.sub(r"\+aiomysql", "", url)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_schemas=False,
        render_item=render_item,
        # SQLite cannot ALTER most things in place.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        url=db_settings.url,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations)
    await connectable.dispose()


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(db_settings.url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(_run_async())
