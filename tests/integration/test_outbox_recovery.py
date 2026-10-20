"""Disposable backup/restore and least-privilege checks, not pilot operations."""

import asyncio
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa

from tsetmc_marketdata.storage import schema_v3b1 as p
from tsetmc_marketdata.storage.config import DatabaseSettings
from tsetmc_marketdata.storage.database import Database
from tsetmc_marketdata.storage.outbox import RecoveryFence, SourceOutbox
from tsetmc_marketdata.storage.repository import Repository

from .conftest import migration
from .helpers import A, SyntheticSource
from .test_local_sync_state import stage
from .test_persistence import ingest
from .test_source_outbox import daily_events, enroll, fingerprint, rows

pytestmark = pytest.mark.postgres


async def test_disposable_pg_dump_restore_preserves_source_and_staging_then_fences_newer_proof(
    pg_database,
):
    db, url = pg_database
    binary = os.getenv("TSETMC_TEST_PG_BIN")
    if not binary:
        pytest.skip("portable pg_dump/pg_restore require explicit TSETMC_TEST_PG_BIN")
    binding, _ = await enroll(db)
    source = SyntheticSource()
    await ingest(db, source)
    batch_id, body = await stage(db, "tsetmc_daily")
    async with db.read() as conn:
        original = await fingerprint(conn)
    parsed = DatabaseSettings(url).validated_url()
    env = {**os.environ, "PGPASSWORD": parsed.password or ""}
    options = ["-h", str(parsed.host), "-p", str(parsed.port or 5432), "-U", str(parsed.username)]
    dump = await asyncio.to_thread(
        subprocess.run,
        [
            str(Path(binary) / "pg_dump"),
            *options,
            "-d",
            str(parsed.database),
            "--format=custom",
            "--no-owner",
            "--no-acl",
        ],
        env=env,
        capture_output=True,
        timeout=40,
    )
    assert dump.returncode == 0, "dump failed; sensitive diagnostics withheld"
    source.rows[0]["pClosing"] += 1
    await ingest(db, source)
    proof = {k: str(v) for k, v in binding.items()}
    proof["streams"] = {"tsetmc_daily": {"head": len(await daily_events(db)), "acknowledged": 0}}
    proof["staged"] = {str(batch_id): __import__("hashlib").sha256(body).hexdigest()}
    name = "tsetmc_test_" + uuid4().hex
    assert len(name) == 44 and name != parsed.database
    admin = db.engine.execution_options(isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    restored_url = parsed.set(database=name).render_as_string(hide_password=False)
    restored = Database(DatabaseSettings(restored_url))
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [
                str(Path(binary) / "pg_restore"),
                *options,
                "-d",
                name,
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
            ],
            env=env,
            input=dump.stdout,
            capture_output=True,
            timeout=40,
        )
        assert result.returncode == 0, "restore failed; sensitive diagnostics withheld"
        async with restored.read() as conn:
            assert await fingerprint(conn) == original
        saved = (await rows(restored, p.batches))[0]
        assert bytes(saved["request_bytes"]) == body and saved["batch_id"] == batch_id
        async with restored.owner(A) as conn:
            repo = Repository(conn, A)
            with pytest.raises(RecoveryFence):
                async with repo.atomic():
                    await SourceOutbox(repo).continuity(proof)
        assert (await rows(restored, p.datasets))[0]["source_epoch"] == binding["source_epoch"]
    finally:
        await restored.aclose()
        async with admin.connect() as conn:
            await conn.execute(sa.text(f'DROP DATABASE "{name}" WITH (FORCE)'))


async def test_migration_collector_role_grants_and_immutable_evidence(pg_database):
    db, _ = pg_database
    async with db.engine.begin() as conn:
        exists = await conn.scalar(
            sa.text("SELECT EXISTS(SELECT FROM pg_roles WHERE rolname='tsetmc_collector')")
        )
        if not exists:
            await conn.execute(sa.text("CREATE ROLE tsetmc_collector NOLOGIN"))
    try:
        await migration(db.engine, "downgrade", "0003_scheduling")
        await migration(db.engine)
        await enroll(db)
        async with db.engine.begin() as conn:
            # Model the pre-existing Docker collector privileges in this disposable DB.
            await conn.execute(sa.text("GRANT USAGE ON SCHEMA public TO tsetmc_collector"))
            for table in (
                "instruments",
                "source_observations",
                "collection_runs",
                "collection_status",
                "daily_records",
                "daily_revisions",
                "data_coverage",
                "quarantined_records",
                "reconciliation_decisions",
                "current_snapshots",
                "current_latest",
            ):
                await conn.execute(
                    sa.text(f"GRANT SELECT,INSERT,UPDATE,DELETE ON {table} TO tsetmc_collector")
                )
            await conn.execute(
                sa.text("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO tsetmc_collector")
            )
            await conn.execute(
                sa.text(
                    "GRANT SELECT ON daily_reviews,collector_runtime,scheduled_jobs "
                    "TO tsetmc_collector"
                )
            )
        # Switch only this owned session's effective role; no real login is created.
        async with db.owner(A) as conn:
            await conn.execute(sa.text("SET ROLE tsetmc_collector"))
            await conn.commit()
            try:
                repo = Repository(conn, A)
                from tsetmc_marketdata.collection.jobs import Collector

                await Collector(repo, SyntheticSource(), kind="synthetic").run("backfill-history")
                async with repo.atomic():
                    assert not await conn.scalar(
                        sa.text("SELECT has_table_privilege(current_user,'sync_datasets','UPDATE')")
                    )
                    assert not await conn.scalar(
                        sa.text("SELECT has_table_privilege(current_user,'sync_outbox','UPDATE')")
                    )
                    assert not await conn.scalar(
                        sa.text("SELECT has_table_privilege(current_user,'sync_batches','DELETE')")
                    )
            finally:
                if conn.in_transaction():
                    await conn.rollback()
                await conn.execute(sa.text("RESET ROLE"))
                await conn.commit()
        assert len(await daily_events(db)) == 1
    finally:
        if not exists:
            async with db.engine.begin() as conn:
                await conn.execute(sa.text("DROP OWNED BY tsetmc_collector"))
                await conn.execute(sa.text("DROP ROLE tsetmc_collector"))
