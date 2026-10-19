"""One dedicated session per owner. Lost sessions cannot silently regain write ownership."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from tsetmc_marketdata.config import validate_ins_code
from tsetmc_marketdata.storage.config import DatabaseSettings, OwnershipError, SchemaError
from tsetmc_marketdata.storage.schema_v1 import instruments, metadata

LOCK_NAMESPACE = 81483
SCHEMA_REVISION = "0002_instrument_links"


def make_engine(settings: DatabaseSettings) -> AsyncEngine:
    return create_async_engine(
        settings.validated_url(),
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={
            "timeout": 5,
            "server_settings": {
                "application_name": "tsetmc_marketdata",
                "timezone": "UTC",
                "statement_timeout": "60000",
                "lock_timeout": "5000",
            },
        },
    )


async def verify_schema(conn: AsyncConnection) -> dict[str, Any]:
    database, version = (
        await conn.execute(sa.text("SELECT current_database(), current_setting('server_version')"))
    ).one()
    table = await conn.scalar(sa.text("SELECT to_regclass('public.alembic_version')"))
    if table is None:
        raise SchemaError("TSETMC schema is absent; run Alembic explicitly")
    revisions = (
        (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalars().all()
    )
    if list(revisions) != [SCHEMA_REVISION]:
        raise SchemaError("TSETMC schema revision is incompatible")
    existing = set(
        (
            await conn.execute(sa.text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
        ).scalars()
    )
    if not set(metadata.tables) <= existing:
        raise SchemaError("TSETMC schema is incomplete")
    return {"database": database, "server_version": version, "schema_revision": SCHEMA_REVISION}


class Database:
    def __init__(self, settings: DatabaseSettings) -> None:
        self.engine = make_engine(settings)

    async def aclose(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def read(self) -> AsyncIterator[AsyncConnection]:
        async with self.engine.connect() as conn:
            await verify_schema(conn)
            await conn.commit()
            async with conn.begin():
                await conn.execute(sa.text("SET TRANSACTION READ ONLY"))
                yield conn

    @asynccontextmanager
    async def owner(self, ins_code: str) -> AsyncIterator[AsyncConnection]:
        validate_ins_code(ins_code)
        async with self.engine.connect() as conn:
            await verify_schema(conn)
            await conn.execute(
                insert(instruments)
                .values(ins_code=ins_code, active=False)
                .on_conflict_do_nothing(index_elements=[instruments.c.ins_code])
            )
            key = await conn.scalar(
                sa.select(instruments.c.ownership_key).where(instruments.c.ins_code == ins_code)
            )
            acquired = await conn.scalar(
                sa.text("SELECT pg_try_advisory_lock(:ns,:key)"), {"ns": LOCK_NAMESPACE, "key": key}
            )
            await conn.commit()
            if not acquired:
                raise OwnershipError("another TSETMC collector owns this instrument")
            conn.info["tsetmc_owner_code"] = ins_code
            conn.info["tsetmc_owner_key"] = key
            try:
                yield conn
            finally:
                if not conn.invalidated and not conn.closed:
                    if conn.in_transaction():
                        await conn.rollback()
                    try:
                        await conn.execute(
                            sa.text("SELECT pg_advisory_unlock(:ns,:key)"),
                            {"ns": LOCK_NAMESPACE, "key": key},
                        )
                        await conn.commit()
                    except sa.exc.SQLAlchemyError:
                        await conn.invalidate()


async def fence(conn: AsyncConnection, ins_code: str) -> None:
    if conn.invalidated or conn.closed:
        raise OwnershipError("collector database session was lost")
    if conn.info.get("tsetmc_owner_code") != ins_code:
        raise OwnershipError("collector ownership belongs to a different instrument")
    held = await conn.scalar(
        sa.text("""SELECT EXISTS (SELECT 1 FROM pg_locks
        WHERE locktype='advisory' AND pid=pg_backend_pid() AND classid=:ns
        AND objid=:key AND objsubid=2 AND granted)"""),
        {"ns": LOCK_NAMESPACE, "key": conn.info["tsetmc_owner_key"]},
    )
    if not held:
        raise OwnershipError("collector session no longer holds its advisory lock")
