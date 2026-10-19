"""Synthetic, offline source observations against actual disposable PostgreSQL 16."""

import asyncio
import hashlib
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa

from tsetmc_marketdata.adapters.chartdata import to_chartdata
from tsetmc_marketdata.collection.jobs import Collector
from tsetmc_marketdata.errors import ErrorKind, RecordError, TransportError
from tsetmc_marketdata.storage import schema_v1 as t
from tsetmc_marketdata.storage.config import DatabaseSettings, OwnershipError, SchemaError
from tsetmc_marketdata.storage.database import (
    SCHEMA_REVISION,
    Database,
    fence,
    make_engine,
    verify_schema,
)
from tsetmc_marketdata.storage.queries import collection_report, pending_dates, read_daily, retain
from tsetmc_marketdata.storage.repository import Repository

from .conftest import ROOT, migration
from .helpers import RECEIPT, A, B, SyntheticSource, row

pytestmark = pytest.mark.postgres


async def ingest(db, source, job="backfill-history", **kwargs):
    async with db.owner(source.code) as conn:
        return await Collector(Repository(conn, source.code), source, kind="synthetic").run(
            job, **kwargs
        )


async def count(db, table, code=A):
    async with db.read() as conn:
        return await conn.scalar(
            sa.select(sa.func.count()).select_from(table).where(table.c.ins_code == code)
        )


async def test_fresh_migration_rollback_and_missing_schema(pg_database):
    db, _ = pg_database
    async with db.read() as conn:
        result = await verify_schema(conn)
        assert result["server_version"].startswith("16.")
        assert result["schema_revision"] == SCHEMA_REVISION
        assert await conn.scalar(sa.select(sa.func.count()).select_from(t.instruments)) == 0
    await migration(db.engine, "downgrade", "base")
    with pytest.raises(SchemaError, match="absent|incompatible"):
        async with db.read():
            pass
    await migration(db.engine)
    async with db.engine.begin() as conn:
        await conn.execute(sa.text("UPDATE alembic_version SET version_num='wrong_revision'"))
    with pytest.raises(SchemaError, match="incompatible"):
        async with db.read():
            pass


async def test_archive_import_exact_precision_raw_and_chartdata(pg_database):
    db, _ = pg_database
    source = SyntheticSource(rows=[row(day=20260101), row(day=20251231)])
    # Numeric source strings are also accepted by M1; no binary float passes through this test.
    source.rows[0].update(
        qTotCap="1234567890123456789012345678901234567890.1234567890123456789",
        zTotTran=123456789012345678901234567890,
        qTotTran5J="999999999999999999999999999.1234",
        pClosing="1020.12345678901234567890123456789",
    )
    result = await ingest(db, source)
    assert result["inserted"] == 2 and result["status"] == "success"
    async with db.read() as conn:
        records, default = await read_daily(conn, A)
        assert records == [] and default["excluded_unverified"] == 2
        records, _ = await read_daily(conn, A, selection="accepted-unverified")
        assert [r.trading_date for r in records] == [date(2025, 12, 31), date(2026, 1, 1)]
        assert records[1].traded_value == Decimal(source.rows[0]["qTotCap"])
        assert records[1].trade_count == source.rows[0]["zTotTran"]
        assert records[1].official_close == Decimal(source.rows[0]["pClosing"])
        assert len(records[1].table_columns()) == 14
        observation = (
            (
                await conn.execute(
                    sa.select(t.observations).where(t.observations.c.endpoint.contains("DailyList"))
                )
            )
            .mappings()
            .one()
        )
        expected = await source.get_json(observation["endpoint"])
        assert observation["raw_body"] == expected.raw_body
        assert observation["raw_sha256"] == hashlib.sha256(expected.raw_body).hexdigest()
        assert observation["received_at"] == RECEIPT
        with pytest.raises(ValueError, match="int64"):
            to_chartdata(records)
        compatible = [records[0], replace(records[1], trade_count=1234)]
        chart = to_chartdata(compatible).to_dict(legacy_sample=True)
        assert list(chart) == list("abcdefghi")
        assert chart["i"] is None
        assert chart["c"][1] == float(records[1].official_close)
        assert chart["g"][1] == float(records[1].traded_volume)
        assert chart["h"][1] == float(records[1].traded_value)
        assert chart["f"][1] == 1234
        assert all(len(chart[key]) == 2 for key in "abcdefgh")


async def test_idempotency_corrections_financial_hash_and_run_replay(pg_database):
    db, _ = pg_database
    source = SyntheticSource()
    rid = uuid4()
    first = await ingest(db, source, run_id=rid)
    source.calls.clear()
    replay = await ingest(db, source, run_id=rid)
    assert replay["replayed_committed_run"] and not source.calls
    assert first["inserted"] == 1
    assert (await ingest(db, source))["unchanged"] == 1
    source.rows[0] = dict(reversed(list(source.rows[0].items())))
    source.rows[0]["last"] = False
    assert (await ingest(db, source))["unchanged"] == 1
    assert await count(db, t.revisions) == 0
    source.rows[0]["pClosing"] = 1021
    assert (await ingest(db, source))["corrected"] == 1
    assert (await ingest(db, source))["unchanged"] == 1
    assert await count(db, t.daily) == 1 and await count(db, t.revisions) == 1
    async with db.read() as conn:
        revision = (await conn.execute(sa.select(t.revisions))).mappings().one()
        assert revision["old_state"]["official_close"] == "1020"
        assert revision["new_state"]["official_close"] == "1021"
        assert revision["old_observation_id"] != revision["new_observation_id"]
        assert revision["revision"] == 2


async def test_quarantine_july_equivalent_reconciliation_and_evidence(pg_database):
    db, _ = pg_database
    source = SyntheticSource(rows=[row(priceFirst=0), row(day=20250730)])
    initial = await ingest(db, source)
    assert initial["status"] == "partial" and initial["quarantined"] == 1
    assert initial["accepted"] == 1
    async with db.read() as conn:
        assert await pending_dates(conn, A) == [date(2025, 7, 29)]
    resolved = await ingest(db, source, "reconcile-history", dates=[date(2025, 7, 29)])
    assert resolved["reconciled"] == 1
    repeated = await ingest(db, source, "reconcile-history", dates=[date(2025, 7, 29)])
    assert repeated["reconciled"] == 1 and await count(db, t.revisions) == 0
    await ingest(db, source)
    async with db.read() as conn:
        q = (await conn.execute(sa.select(t.quarantine))).mappings().one()
        assert q["status"] == "resolved" and q["raw_row"]["priceFirst"] == 0
        assert q["sightings"] == 2
        assert q["resolution_observation_id"] != q["observation_id"]
        assert q["resolution_method"] == "validated_target_replaces_invalid_list"
        rows, _ = await read_daily(conn, A, selection="accepted-unverified")
        assert rows[0].opening_price == 1010
        assert (
            await conn.scalar(
                sa.select(t.coverage.c.state).where(
                    t.coverage.c.ins_code == A, t.coverage.c.trading_date == date(2025, 7, 29)
                )
            )
            == "reconciled"
        )


async def test_valid_target_disagreement_and_invalid_target_are_not_overwrites(pg_database):
    db, _ = pg_database
    source = SyntheticSource()
    await ingest(db, source)
    source.target[20250729] = row(pClosing=1022)
    unresolved = await ingest(db, source, "reconcile-history", dates=[date(2025, 7, 29)])
    assert unresolved["unresolved"] == 1 and unresolved["status"] == "partial"
    source.target[20250730] = row(day=20250730, priceFirst=0)
    invalid = await ingest(db, source, "reconcile-history", dates=[date(2025, 7, 30)])
    assert invalid["unresolved"] == 1
    assert await count(db, t.daily) == 1
    assert await count(db, t.revisions) == 0
    assert await count(db, t.quarantine) == 2


async def test_reconciled_record_protected_from_valid_list_conflict(pg_database):
    db, _ = pg_database
    source = SyntheticSource()
    await ingest(db, source, "reconcile-history", dates=[date(2025, 7, 29)])
    source.rows[0]["pClosing"] = 1033
    result = await ingest(db, source)
    assert result["conflict"] == 1 and result["status"] == "partial"
    async with db.read() as conn:
        assert await conn.scalar(sa.select(t.daily.c.official_close)) == 1020


async def test_unusual_close_zero_unknown_and_duplicate_coverage(pg_database):
    db, _ = pg_database
    source = SyntheticSource(
        rows=[
            row(day=20250101, pClosing=950),
            row(day=20250102, zTotTran=0, qTotTran5J=0, qTotCap=0, priceFirst=0, pDrCotVal=0),
            row(day=20250103, zTotTran=None, qTotTran5J=None, qTotCap=None),
            row(day=20250104),
            row(day=20250104, pClosing=1022),
            row(day=20250105),
            row(day=20250105),
        ]
    )
    result = await ingest(db, source)
    assert result["accepted"] == 4 and result["quarantined"] == 2
    async with db.read() as conn:
        states = dict(
            (await conn.execute(sa.select(t.coverage.c.trading_date, t.coverage.c.state))).all()
        )
        assert states[date(2025, 1, 2)] == "confirmed_no_trade"
        assert states[date(2025, 1, 3)] == "observed"
        assert states[date(2025, 1, 4)] == "quarantined"
        assert date(2025, 1, 6) not in states  # No calendar interpolation.
        records, _ = await read_daily(conn, A, selection="accepted-unverified")
        chart = to_chartdata(records).to_dict()
        assert chart["c"][0] == 950 and chart["e"][0] == 1000
        assert chart["f"][1:3] == [0, 0]  # Internal None and genuine zero remain distinct.
        assert records[2].trade_count is None


@pytest.mark.parametrize(
    "kind",
    [
        ErrorKind.TIMEOUT,
        ErrorKind.DNS,
        ErrorKind.NETWORK,
        ErrorKind.ACCESS_DENIED,
        ErrorKind.RATE_LIMIT,
        ErrorKind.SERVER,
        ErrorKind.INVALID_JSON,
        ErrorKind.SCHEMA,
    ],
)
async def test_source_failure_preserves_data_and_restarts(pg_database, kind):
    db, _ = pg_database
    source = SyntheticSource()
    await ingest(db, source)
    status = (
        403 if kind == ErrorKind.ACCESS_DENIED else 429 if kind == ErrorKind.RATE_LIMIT else None
    )
    source.error = TransportError(kind, "synthetic failure", status=status)
    with pytest.raises(TransportError):
        await ingest(db, source)
    assert await count(db, t.daily) == 1
    async with db.read() as conn:
        report = await collection_report(conn, A)
        assert report["status"][0]["failure_category"] == kind.value
        assert report["status"][0]["last_success_at"] is not None
        failed = (
            (
                await conn.execute(
                    sa.select(t.observations).where(
                        t.observations.c.processing_status == "request_failed"
                    )
                )
            )
            .mappings()
            .one()
        )
        assert failed["raw_body"] is None and failed["received_at"] is None
    source.error = None
    assert (await ingest(db, source))["unchanged"] == 1


async def test_empty_valid_is_distinct_from_failure(pg_database):
    db, _ = pg_database
    source = SyntheticSource()
    await ingest(db, source)
    source.rows = []
    result = await ingest(db, source)
    assert result["empty_valid_response"] and result["status"] == "success"
    assert result["archive_completeness"] == "unproven" and await count(db, t.daily) == 1


async def test_transaction_rollback_and_cancelled_run(pg_database):
    db, _ = pg_database
    source = SyntheticSource()

    def fail(stage):
        if stage == "before_commit":
            raise asyncio.CancelledError()

    async with db.owner(A) as conn:
        collector = Collector(Repository(conn, A, fault=fail), source, kind="synthetic")
        with pytest.raises(asyncio.CancelledError):
            await collector.run("backfill-history")
    assert await count(db, t.daily) == 0
    async with db.read() as conn:
        run = (await conn.execute(sa.select(t.runs))).mappings().one()
        assert run["status"] == "interrupted" and run["checkpoint"]["phase"] != "committed"
    assert (await ingest(db, source))["inserted"] == 1


@pytest.mark.parametrize("stage", ["before_commit", "after_commit"])
async def test_actual_process_crash_and_repeat(pg_database, stage):
    db, url = pg_database
    run_id = uuid4()
    program = """
import asyncio, os, sys
from uuid import UUID
sys.path.insert(0, "tests/integration")
from helpers import A, SyntheticSource
from tsetmc_marketdata.collection.jobs import Collector
from tsetmc_marketdata.storage.config import DatabaseSettings
from tsetmc_marketdata.storage.database import Database
from tsetmc_marketdata.storage.repository import Repository
async def run():
    db = Database(DatabaseSettings(os.environ["TSETMC_DATABASE_URL"]))
    async with db.owner(A) as conn:
        def fault(stage):
            if stage == os.environ["TSETMC_CRASH_STAGE"]:
                os._exit(73)
        c = Collector(Repository(conn, A, fault=fault), SyntheticSource(), kind="synthetic")
        await c.run("backfill-history", run_id=UUID(os.environ["TSETMC_RUN_ID"]))
asyncio.run(run())
"""
    env = {
        **os.environ,
        "TSETMC_DATABASE_URL": url,
        "TSETMC_CRASH_STAGE": stage,
        "TSETMC_RUN_ID": str(run_id),
    }
    process = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-c", program],
        env=env,
        cwd=ROOT,
        capture_output=True,
        timeout=30,
    )
    assert process.returncode == 73, process.stderr.decode(errors="replace")
    assert await count(db, t.daily) == (0 if stage == "before_commit" else 1)
    source = SyntheticSource()
    if stage == "after_commit":
        result = await ingest(db, source, run_id=run_id)
        assert result["replayed_committed_run"] and source.calls == []
    else:
        result = await ingest(db, source)
        assert result["inserted"] == 1
        async with db.read() as conn:
            assert (
                await conn.scalar(sa.select(t.runs.c.status).where(t.runs.c.run_id == run_id))
                == "interrupted"
            )


async def test_lost_successful_commit_acknowledgment(pg_database):
    db, _ = pg_database
    run_id = uuid4()

    def fault(stage):
        if stage == "after_commit":
            raise ConnectionError("synthetic lost commit acknowledgment")

    async with db.owner(A) as conn:
        c = Collector(Repository(conn, A, fault=fault), SyntheticSource(), kind="synthetic")
        with pytest.raises(ConnectionError):
            await c.run("backfill-history", run_id=run_id)
    source = SyntheticSource()
    result = await ingest(db, source, run_id=run_id)
    assert result["replayed_committed_run"] and not source.calls
    assert await count(db, t.daily) == 1


@pytest.mark.parametrize("job", ["backfill-history", "observe-current"])
async def test_concurrent_same_instrument_ownership(pg_database, job):
    db, _ = pg_database
    waiting = asyncio.Event()
    release = asyncio.Event()
    source = SyntheticSource()
    original = source.get_json

    async def slow(path):
        waiting.set()
        await release.wait()
        return await original(path)

    source.get_json = slow
    first = asyncio.create_task(ingest(db, source, job))
    await asyncio.wait_for(waiting.wait(), 5)
    second = SyntheticSource()
    try:
        with pytest.raises(OwnershipError):
            await ingest(db, second, job)
        assert second.calls == []
    finally:
        release.set()
    assert (await first)["status"] == "success"


async def test_lost_session_is_fenced(pg_database):
    db, _ = pg_database
    async with db.owner(A) as conn:
        await conn.execute(sa.text("SELECT pg_advisory_unlock_all()"))
        await conn.commit()
        with pytest.raises(OwnershipError):
            async with Repository(conn, A).atomic():
                pass


async def test_current_latest_order_repeat_correction_and_unknown(pg_database):
    db, _ = pg_database
    source = SyntheticSource()
    first = await ingest(db, source, "observe-current")
    assert first["latest_updated"] and first["state_change"]
    source.receipt += timedelta(seconds=1)
    repeat = await ingest(db, source, "observe-current")
    assert repeat["decision"] == "repeated_state" and not repeat["state_change"]
    source.current["dEven"] = 20260320
    source.current["pClosing"] = 1022
    assert (await ingest(db, source, "observe-current"))["decision"] == "older_session"
    source.current["dEven"] = 20260321
    source.current["hEven"] = 122959
    assert (await ingest(db, source, "observe-current"))["decision"] == "older_source_clock"
    source.current["hEven"] = 123000
    conflict = await ingest(db, source, "observe-current")
    assert conflict["status"] == "partial" and not conflict["latest_updated"]
    corrected = await ingest(db, source, "observe-current", correction_reason="reviewed correction")
    assert corrected["decision"] == "explicit_same_time_correction"
    source.current["hEven"] = 0
    source.current["pClosing"] = 1023
    assert not (await ingest(db, source, "observe-current"))["latest_updated"]
    async with db.read() as conn:
        latest = (
            (
                await conn.execute(
                    sa.select(t.snapshots).join(
                        t.latest, t.latest.c.snapshot_id == t.snapshots.c.snapshot_id
                    )
                )
            )
            .mappings()
            .one()
        )
        assert latest["official_close"] == 1022 and latest["last_traded_price"] == 1030
        assert latest["source_reported_at"].tzinfo is not None
        assert latest["received_at"] != latest["source_reported_at"]
        assert latest["decision_reason"] == "reviewed correction"
    assert await count(db, t.snapshots) == 7


async def test_two_synthetic_instruments_are_completely_isolated(pg_database):
    db, _ = pg_database
    a = SyntheticSource(A, rows=[row(A, priceFirst=0)])
    b = SyntheticSource(B, rows=[row(B, pClosing=999)])
    # Distinct advisory keys permit independent ownership concurrently.
    async with db.owner(A) as ca, db.owner(B) as cb:
        assert ca.info["tsetmc_owner_key"] != cb.info["tsetmc_owner_key"]
        await Collector(Repository(ca, A), a, kind="synthetic").run("backfill-history")
        await Collector(Repository(cb, B), b, kind="synthetic").run("backfill-history")
        with pytest.raises(OwnershipError):
            await fence(ca, B)
        await ca.rollback()
    assert await count(db, t.daily, A) == 0 and await count(db, t.daily, B) == 1
    assert await count(db, t.quarantine, A) == 1 and await count(db, t.quarantine, B) == 0
    await ingest(db, a, "reconcile-history", dates=[date(2025, 7, 29)])
    b.rows[0]["pClosing"] = 998
    await ingest(db, b)
    await ingest(db, a, "observe-current")
    b.current["pClosing"] = 999
    await ingest(db, b, "observe-current")
    assert await count(db, t.revisions, A) == 0 and await count(db, t.revisions, B) == 1
    async with db.read() as conn:
        for code, close, state in [(A, 1020, "reconciled"), (B, 998, "observed")]:
            records, _ = await read_daily(conn, code, selection="accepted-unverified")
            assert len(records) == 1 and records[0].official_close == close
            report = await collection_report(conn, code)
            assert report["coverage"] == {state: 1}
            assert all(r["ins_code"] == code for r in report["recent_runs"])
            assert all(r["checkpoint"]["phase"] == "committed" for r in report["recent_runs"])
            assert report["latest"]["ins_code"] == code
        b_snapshot = await conn.scalar(
            sa.select(t.latest.c.snapshot_id).where(t.latest.c.ins_code == B)
        )
        b_observation = await conn.scalar(
            sa.select(t.snapshots.c.observation_id).where(t.snapshots.c.ins_code == B)
        )
        b_run = await conn.scalar(
            sa.select(t.runs.c.run_id).where(
                t.runs.c.ins_code == B, t.runs.c.job == "observe-current"
            )
        )
    # Database constraints prevent linking A's latest pointer to B's snapshot.
    async with db.owner(A) as conn:
        with pytest.raises(sa.exc.IntegrityError):
            async with conn.begin():
                await conn.execute(
                    t.latest.update().where(t.latest.c.ins_code == A).values(snapshot_id=b_snapshot)
                )
        for table, column, value in (
            (t.daily, "observation_id", b_observation),
            (t.coverage, "observation_id", b_observation),
            (t.quarantine, "resolution_observation_id", b_observation),
            (t.instruments, "metadata_observation_id", b_observation),
            (t.status, "last_run_id", b_run),
        ):
            with pytest.raises(sa.exc.IntegrityError):
                async with conn.begin():
                    await conn.execute(
                        table.update().where(table.c.ins_code == A).values(**{column: value})
                    )
    # Run identities also cannot be reused across instruments.
    rid = uuid4()
    await ingest(db, a, "observe-current", run_id=rid)
    with pytest.raises(ValueError, match="another instrument"):
        await ingest(db, b, "observe-current", run_id=rid)
    assert await count(db, t.quarantine, B) == 0


async def test_retention_protects_latest_revision_and_quarantine(pg_database):
    db, _ = pg_database
    source = SyntheticSource()
    await ingest(db, source)
    source.rows[0]["pClosing"] = 1021
    await ingest(db, source)
    await ingest(db, source, "observe-current")
    await ingest(db, source, "observe-current")
    async with db.owner(A) as conn:
        async with conn.begin():
            dry = await retain(conn, A, now=datetime(2027, 1, 1, tzinfo=UTC))
            assert dry["snapshot_rows"] == 1
            result = await retain(conn, A, apply=True, now=datetime(2027, 1, 1, tzinfo=UTC))
            assert result["snapshot_rows"] == 1
    assert await count(db, t.snapshots) == 1
    async with db.read() as conn:
        revision = (await conn.execute(sa.select(t.revisions))).mappings().one()
        for obs in (revision["old_observation_id"], revision["new_observation_id"]):
            assert (
                await conn.scalar(
                    sa.select(t.observations.c.raw_body).where(
                        t.observations.c.observation_id == obs
                    )
                )
                is not None
            )


async def test_dry_run_does_not_mutate_database(pg_database):
    db, _ = pg_database
    async with db.read() as conn:
        result = await Collector(Repository(conn, A), SyntheticSource(), kind="synthetic").run(
            "backfill-history", dry_run=True
        )
        assert result == {"dry_run": True, "accepted": 1, "quarantined": 0}
        assert await conn.scalar(sa.select(sa.func.count()).select_from(t.instruments)) == 0
        assert await conn.scalar(sa.select(sa.func.count()).select_from(t.runs)) == 0


async def test_instrument_identifier_verification_prevents_import(pg_database):
    db, _ = pg_database
    async with db.owner(A) as conn:
        collector = Collector(
            Repository(conn, A),
            SyntheticSource(),
            kind="synthetic",
            expected_instrument_id="TEST-ANOTHER-IDENTITY",
        )
        with pytest.raises(RecordError, match="ID"):
            await collector.run("backfill-history")
    assert await count(db, t.daily) == 0
    async with db.read() as conn:
        assert await conn.scalar(sa.select(t.runs.c.status)) == "failed"


async def test_postgres_write_error_rollback_and_recovery(pg_database):
    db, _ = pg_database
    async with db.owner(A) as conn:
        async with conn.begin():
            await conn.execute(sa.text("SET default_transaction_read_only=on"))
        # begin_run cannot commit: no false durable success and no financial rows.
        with pytest.raises(sa.exc.DBAPIError):
            await Collector(Repository(conn, A), SyntheticSource()).run("backfill-history")
        await conn.rollback()
        await conn.execute(sa.text("SET default_transaction_read_only=off"))
        await conn.commit()
    assert await count(db, t.daily) == 0
    assert (await ingest(db, SyntheticSource()))["inserted"] == 1


async def test_database_error_during_data_transaction_records_failure(pg_database):
    db, _ = pg_database

    class BrokenRepository(Repository):
        async def ingest_history(self, *args, **kwargs):
            async with self.atomic():
                await self.conn.execute(sa.text("SELECT 1/0"))

    async with db.owner(A) as conn:
        with pytest.raises(sa.exc.DBAPIError):
            await Collector(BrokenRepository(conn, A), SyntheticSource()).run("backfill-history")
    assert await count(db, t.daily) == 0
    async with db.read() as conn:
        report = await collection_report(conn, A)
        assert report["status"][0]["failure_category"] == "postgres_write_failure"
        assert report["recent_runs"][0]["checkpoint"]["phase"] == "failed_before_data_commit"
    assert (await ingest(db, SyntheticSource()))["inserted"] == 1


async def test_new_current_arrival_waits_for_prior_transaction(pg_database):
    db, _ = pg_database
    async with db.owner(A) as conn:
        repo = Repository(conn, A)
        await Collector(repo, SyntheticSource(), kind="synthetic").run("observe-current")
        async with repo.atomic():
            # A second observation arrives while the first owner is persisting.
            other = SyntheticSource()
            other.current["hEven"] = 123100
            with pytest.raises(OwnershipError):
                await ingest(db, other, "observe-current")
            assert not other.calls
    result = await ingest(db, other, "observe-current")
    assert result["decision"] == "newer_source_clock"


async def test_backup_restore_disposable_database(pg_database):
    container = os.environ.get("TSETMC_TEST_DOCKER_CONTAINER")
    if not container:
        pytest.skip("pg_dump/restore requires explicit TSETMC_TEST_DOCKER_CONTAINER")
    assert container == "tsetmc-m2-local-postgres-1"
    db, url = pg_database
    await ingest(db, SyntheticSource())
    await ingest(db, SyntheticSource(), "observe-current")
    source_name = DatabaseSettings(url).validated_url().database
    dump = await asyncio.to_thread(
        subprocess.run,
        [
            "docker",
            "exec",
            container,
            "pg_dump",
            "-U",
            "tsetmc_owner",
            "-d",
            source_name,
            "--format=custom",
            "--no-owner",
            "--no-acl",
        ],
        capture_output=True,
        timeout=30,
    )
    assert dump.returncode == 0 and dump.stdout.startswith(b"PGDMP")
    name = "tsetmc_test_" + uuid4().hex

    admin = make_engine(DatabaseSettings(url)).execution_options(isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    restored = Database(
        DatabaseSettings(
            DatabaseSettings(url)
            .validated_url()
            .set(database=name)
            .render_as_string(hide_password=False)
        )
    )
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "docker",
                "exec",
                "-i",
                container,
                "pg_restore",
                "-U",
                "tsetmc_owner",
                "-d",
                name,
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
            ],
            input=dump.stdout,
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0, "restore failed; sensitive diagnostics withheld"
        assert await count(restored, t.daily) == 1
        assert await count(restored, t.snapshots) == 1
        async with restored.read() as conn:
            records, _ = await read_daily(conn, A, selection="accepted-unverified")
            assert records[0].official_close == 1020
            observations = (await conn.execute(sa.select(t.observations))).mappings().all()
            assert all(
                hashlib.sha256(r["raw_body"]).hexdigest() == r["raw_sha256"] for r in observations
            )
    finally:
        await restored.aclose()
        async with admin.connect() as conn:
            await conn.execute(sa.text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()
