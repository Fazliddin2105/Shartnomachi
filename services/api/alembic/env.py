"""Async Alembic environment. Database URL comes from application settings."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.types import TypeDecorator

import app.db.models  # noqa: F401  (populate metadata)
from alembic import context
from app.core.config import get_settings
from app.db.base import Base

config = context.config
# "%" must be escaped for ConfigParser (URL-encoded passwords)
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata


def render_item(type_: str, obj: Any, autogen_context: Any) -> str | bool:
    """Render our TypeDecorators as their storage type so migrations never import app code."""
    if type_ == "type" and isinstance(obj, TypeDecorator):
        impl = obj.impl if not isinstance(obj.impl, type) else obj.impl()
        length = getattr(impl, "length", None)
        name = type(impl).__name__
        return f"sa.{name}({length})" if length else f"sa.{name}()"
    return False


def _configure(connection: Connection | None = None, **kw: Any) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_item=render_item,
        compare_type=True,
        render_as_batch=connection is not None and connection.dialect.name == "sqlite",
        **kw,
    )


def run_migrations_offline() -> None:
    _configure(url=config.get_main_option("sqlalchemy.url"), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
