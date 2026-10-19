"""Migrations are explicit and use only the independently configured local database."""

import asyncio
from typing import Any

from alembic import context

from tsetmc_marketdata.storage.config import DatabaseSettings
from tsetmc_marketdata.storage.database import make_engine
from tsetmc_marketdata.storage.schema_v1 import metadata


def migrate(connection: Any) -> None:
    context.configure(connection=connection, target_metadata=metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def online() -> None:
    engine = make_engine(DatabaseSettings.from_env(migration=True))
    try:
        async with engine.connect() as connection:
            await connection.run_sync(migrate)
    finally:
        await engine.dispose()


if context.config.attributes.get("connection") is not None:
    migrate(context.config.attributes["connection"])
else:
    asyncio.run(online())
