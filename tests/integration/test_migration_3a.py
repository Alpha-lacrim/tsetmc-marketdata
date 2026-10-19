"""Forward upgrade and interrupted transactional DDL preserve Milestone 2 measurements."""

import asyncio
import os
import subprocess
import sys

import pytest
import sqlalchemy as sa

from tsetmc_marketdata.storage.database import verify_schema

from .conftest import ROOT, migration
from .helpers import SyntheticSource
from .test_persistence import ingest

pytestmark = pytest.mark.postgres


async def test_upgrade_m2_preserves_data_and_recovers_from_migration_process_crash(pg_database):
    db, url = pg_database
    source = SyntheticSource()
    await ingest(db, source)
    source.rows[0]["pClosing"] += 1
    await ingest(db, source)
    await ingest(db, source, "observe-current")
    async with db.read() as conn:
        before = {
            name: (await conn.execute(sa.text("SELECT * FROM " + name))).all()
            for name in (
                "daily_records",
                "daily_revisions",
                "current_snapshots",
                "source_observations",
            )
        }
    await migration(db.engine, "downgrade", "0002_instrument_links")
    program = """
import asyncio, os
from alembic import command
from alembic.config import Config
from tsetmc_marketdata.storage.config import DatabaseSettings
from tsetmc_marketdata.storage.database import make_engine
async def run():
    engine = make_engine(DatabaseSettings(os.environ['TSETMC_MIGRATION_URL']))
    async with engine.begin() as conn:
        def upgrade(sync):
            config = Config('alembic.ini'); config.attributes['connection'] = sync
            command.upgrade(config, 'head')
        await conn.run_sync(upgrade)
        os._exit(74)
asyncio.run(run())
"""
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-c", program],
        cwd=ROOT,
        env={**os.environ, "TSETMC_MIGRATION_URL": url},
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 74, "migration child failed; sensitive diagnostics withheld"
    async with db.engine.connect() as conn:
        assert (
            await conn.scalar(sa.text("SELECT version_num FROM alembic_version"))
            == "0002_instrument_links"
        )
        assert await conn.scalar(sa.text("SELECT to_regclass('scheduled_jobs')")) is None
    await migration(db.engine)
    async with db.read() as conn:
        assert (await verify_schema(conn))["schema_revision"] == "0003_scheduling"
        for name, rows in before.items():
            assert (await conn.execute(sa.text("SELECT * FROM " + name))).all() == rows
