"""Real PostgreSQL tests. Only uniquely created tsetmc_test_<hex> databases are dropped."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from tsetmc_marketdata.storage.config import DatabaseSettings
from tsetmc_marketdata.storage.database import Database, make_engine

ROOT = Path(__file__).resolve().parents[2]


class PrivateURL(str):
    def __repr__(self):
        return "<private test database URL>"


async def migration(engine, direction="upgrade", revision="head"):
    config = Config(str(ROOT / "alembic.ini"))

    def invoke(conn):
        config.attributes["connection"] = conn
        getattr(command, direction)(config, revision)

    async with engine.begin() as conn:
        await conn.run_sync(invoke)


@pytest.fixture
async def pg_database():
    raw = os.environ.get("TSETMC_TEST_ADMIN_URL")
    if not raw:
        pytest.fail("--postgres requires TSETMC_TEST_ADMIN_URL for the independent local DB")
    settings = DatabaseSettings(raw)
    admin = make_engine(settings).execution_options(isolation_level="AUTOCOMMIT")
    name = "tsetmc_test_" + uuid4().hex
    url = settings.validated_url().set(database=name).render_as_string(hide_password=False)
    async with admin.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    db = Database(DatabaseSettings(url))
    try:
        await migration(db.engine)
        yield db, PrivateURL(url)
    finally:
        await db.aclose()
        # name is generated here, not supplied by configuration or inferred from a persistent DB.
        assert name.startswith("tsetmc_test_") and len(name) == 44
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()
