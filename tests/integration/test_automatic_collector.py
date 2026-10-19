"""Synthetic source behavior through the actual PostgreSQL scheduler and recovery path."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from tsetmc_marketdata.collection.budget import BudgetSource
from tsetmc_marketdata.collection.jobs import Collector
from tsetmc_marketdata.collection.service import CollectionService
from tsetmc_marketdata.collection.service_config import ScheduledJob, ServiceConfig
from tsetmc_marketdata.collection.sessions import Expectation, SessionEvidence
from tsetmc_marketdata.errors import ErrorKind, TransportError
from tsetmc_marketdata.storage import schema_v1 as t
from tsetmc_marketdata.storage import schema_v3a as s
from tsetmc_marketdata.storage.config import OwnershipError
from tsetmc_marketdata.storage.health import health_report
from tsetmc_marketdata.storage.repository import Repository

from .helpers import A, B, SyntheticSource
from .test_persistence import count, ingest

pytestmark = pytest.mark.postgres
NOW = datetime(2026, 3, 21, 10, tzinfo=UTC)


class FakeClock:
    def __init__(self, now=NOW):
        self.instant = now
        self.ticks = 0.0
        self.delays = []
        self.jump = 0

    def now(self):
        return self.instant

    def monotonic(self):
        return self.ticks

    def advance(self, seconds):
        self.instant += timedelta(seconds=seconds)
        self.ticks += seconds

    async def sleep(self, seconds):
        assert 0 <= seconds <= 5
        self.delays.append(seconds)
        self.advance(seconds)
        self.instant += timedelta(seconds=self.jump)
        self.jump = 0
        await asyncio.sleep(0)


class TimedSource(SyntheticSource):
    def __init__(self, clock, code=A):
        super().__init__(code)
        self.clock = clock
        self.request_times = []
        self.slow = 0

    async def get_json(self, path):
        self.request_times.append((path, self.clock.monotonic()))
        self.clock.advance(self.slow)
        self.receipt = self.clock.now()
        return await super().get_json(path)


def config(clock, code=A, jobs=None, **changes):
    start = clock.now()
    job = ScheduledJob(
        "current",
        "observe-current",
        start,
        30,
        eligibility="OPERATOR_WINDOW",
        provenance="Explicit synthetic observation window",
    )
    result = ServiceConfig(
        code,
        start,
        start + timedelta(seconds=95),
        tuple(jobs or [job]),
        enabled=True,
        expected_instrument_id="TEST-" + code,
        request_budget=20,
    )
    return replace(result, **changes)


async def run_service(db, cfg, clock, source=None, **kwargs):
    source = source or TimedSource(clock, cfg.ins_code)
    async with db.owner(cfg.ins_code) as conn:
        budget = BudgetSource(source, cfg.ins_code, cfg.request_budget)
        service = CollectionService(
            Repository(conn, cfg.ins_code), budget, cfg, clock=clock, kind="synthetic", **kwargs
        )
        return await service.run(), source


async def test_identical_http_receipts_cache_identity_without_inventing_trades(pg_database):
    db, _ = pg_database
    clock = FakeClock()
    result, source = await run_service(db, config(clock), clock)
    assert result["completed_jobs"] == 4 and result["logical_requests"] == 5
    assert len([p for p in source.calls if "Instrument" in p]) == 1
    assert await count(db, t.snapshots) == 4 and await count(db, t.observations) == 5
    async with db.read() as conn:
        snapshots = (
            (await conn.execute(sa.select(t.snapshots).order_by(t.snapshots.c.snapshot_id)))
            .mappings()
            .all()
        )
        assert [r["is_state_change"] for r in snapshots] == [True, False, False, False]
        assert [r["decision"] for r in snapshots[1:]] == ["repeated_state"] * 3
        market = (
            (
                await conn.execute(
                    sa.select(t.observations).where(
                        t.observations.c.endpoint.contains("GetClosingPriceInfo")
                    )
                )
            )
            .mappings()
            .all()
        )
        assert all(r["request_parameters"]["identity_observation_id"] == 1 for r in market)
        report = await health_report(conn, A, clock.now())
        assert report["process_state"] == "stopped"
        assert report["source_availability"] == "http_observed"
        assert report["data_freshness"] == "stale_session_unknown"
        assert report["last_financial_change_at"] == NOW.isoformat()
        assert "raw_row" not in report["latest"] and "last_traded_price" not in report["latest"]


async def test_metadata_cache_expiry_fetches_and_verifies_identity_again(pg_database):
    db, _ = pg_database
    clock = FakeClock()
    cfg = config(clock, metadata_ttl=60, end=NOW + timedelta(seconds=125))
    _, source = await run_service(db, cfg, clock)
    assert len([p for p in source.calls if "Instrument" in p]) == 3


async def test_expired_cache_rejects_changed_metadata_identity(pg_database):
    import json
    from dataclasses import replace

    db, _ = pg_database
    clock = FakeClock()
    source = TimedSource(clock)
    original = source.get_json

    async def changed(path):
        response = await original(path)
        if "GetInstrumentInfo" in path and clock.monotonic() >= 60:
            response.payload["instrumentInfo"]["instrumentID"] = "WRONG-SYNTHETIC-ID"
            return replace(response, raw_body=json.dumps(response.payload).encode())
        return response

    source.get_json = changed
    await run_service(db, config(clock, metadata_ttl=60), clock, source)
    assert await count(db, t.snapshots) == 2
    assert len([p for p in source.calls if "GetClosingPriceInfo" in p]) == 2


async def test_invalid_current_identity_invalidates_cache(pg_database):
    db, _ = pg_database
    clock = FakeClock()
    source = TimedSource(clock)
    source.current["insCode"] = B
    async with db.owner(A) as conn:
        collector = Collector(
            Repository(conn, A),
            source,
            kind="synthetic",
            clock=clock,
            metadata_ttl=900,
            expected_instrument_id="TEST-" + A,
        )
        with pytest.raises(Exception, match="instrument|insCode"):
            await collector.run("observe-current")
        source.current["insCode"] = A
        await collector.run("observe-current")
    assert len([p for p in source.calls if "Instrument" in p]) == 2


@pytest.mark.parametrize("state", list(Expectation))
async def test_dated_session_expectation_controls_requests_without_calendar_gaps(
    pg_database, state
):
    db, _ = pg_database
    clock = FakeClock()
    cfg = config(clock)
    cfg = replace(
        cfg,
        jobs=(replace(cfg.jobs[0], eligibility="EXPECTED"),),
        sessions=(SessionEvidence(A, NOW, cfg.end, state, "Invented session/closure evidence"),),
    )
    result, source = await run_service(db, cfg, clock)
    assert bool(source.calls) == (state == Expectation.EXPECTED)
    assert result["session_expectation"] == Expectation.UNKNOWN  # Evidence expired at end.
    assert await count(db, t.coverage) == 0


async def test_current_has_priority_and_full_audit_waits_outside_observation_window(pg_database):
    db, _ = pg_database
    clock = FakeClock()
    current = config(clock).jobs[0]
    history = ScheduledJob(
        "recent",
        "refresh-history",
        NOW - timedelta(days=20),
        86400,
        eligibility="OPERATOR_WINDOW",
        provenance="Invented maintenance approval",
    )
    audit = replace(history, key="audit", job="audit-history", interval=604800)
    cfg = config(clock, jobs=[current, history, audit], max_jobs=3)
    result, source = await run_service(db, cfg, clock)
    assert result["completed_jobs"] == 3
    paths = [p for p in source.calls if "Instrument" not in p]
    assert "Info" in paths[0] and "/20" in paths[1] and "Info" in paths[2]
    assert not any(p.endswith("/0") for p in paths)
    async with db.read() as conn:
        recent = (
            (
                await conn.execute(
                    sa.select(s.schedules).where(
                        s.schedules.c.ins_code == A, s.schedules.c.schedule_key == "recent"
                    )
                )
            )
            .mappings()
            .one()
        )
        assert recent["coalesced_slots"] == 20
        assert recent["last_completed_slot"] == NOW


async def test_audit_and_pending_reconciliation_run_in_approved_closed_window(pg_database):
    db, _ = pg_database
    clock = FakeClock()
    audit = ScheduledJob("weekly", "audit-history", NOW, 604800, provenance="Synthetic closure")
    reconcile = replace(audit, key="pending", job="reconcile-history", interval=3600)
    cfg = config(
        clock,
        jobs=[audit, reconcile],
        max_jobs=2,
        sessions=(
            SessionEvidence(
                A,
                NOW,
                NOW + timedelta(hours=1),
                Expectation.NOT_EXPECTED,
                "Invented closed session",
            ),
        ),
    )
    result, source = await run_service(db, cfg, clock)
    assert result["completed_jobs"] == 2
    assert len(source.calls) == 2 and any(p.endswith("/0") for p in source.calls)
    assert await count(db, t.daily) == 1


async def test_crash_after_data_commit_before_schedule_checkpoint_replays_without_http(pg_database):
    db, _ = pg_database
    clock = FakeClock()
    cfg = config(clock, max_jobs=1, end=NOW + timedelta(seconds=180))

    def fault(stage):
        raise RuntimeError("synthetic crash after data commit")

    with pytest.raises(RuntimeError):
        await run_service(db, cfg, clock, fault=fault)
    assert await count(db, t.snapshots) == 1
    async with db.read() as conn:
        pending = (await conn.execute(sa.select(s.schedules))).mappings().one()
        assert pending["active_run_id"] is not None and pending["last_completed_slot"] is None
    clock.advance(31)
    result, source = await run_service(db, cfg, clock)
    assert result["completed_jobs"] == 1 and source.calls == []
    assert await count(db, t.snapshots) == 1
    async with db.read() as conn:
        row = (await conn.execute(sa.select(s.schedules))).mappings().one()
        assert row["last_completed_slot"] == NOW and row["active_run_id"] is None


@pytest.mark.parametrize("kind", [ErrorKind.TIMEOUT, ErrorKind.ACCESS_DENIED, ErrorKind.RATE_LIMIT])
async def test_scheduled_source_outages_have_bounded_retries_and_durable_failure(pg_database, kind):
    db, _ = pg_database
    clock = FakeClock()
    source = TimedSource(clock)
    source.error = TransportError(kind, "synthetic failure")
    cfg = config(clock, end=NOW + timedelta(seconds=200))
    result, _ = await run_service(db, cfg, clock, source)
    assert result["state"] == "failed"
    async with db.read() as conn:
        row = (await conn.execute(sa.select(s.schedules))).mappings().one()
        assert row["failure_count"] == (1 if kind == ErrorKind.ACCESS_DENIED else 3)
        assert row["last_completed_slot"] is None
        report = await health_report(conn, A, clock.now())
        assert report["latest_failure_category"] == kind.value
        assert report["source_availability"] == "latest_request_failed"
    assert await count(db, t.snapshots) == 0


@pytest.mark.parametrize("jump", [-3600, 3600])
async def test_clock_changes_do_not_extend_lifetime_or_create_request_bursts(pg_database, jump):
    db, _ = pg_database
    clock = FakeClock()
    clock.jump = jump
    result, source = await run_service(db, config(clock), clock)
    assert result["state"] == "stopped" and clock.monotonic() <= 95
    current = [
        instant for path, instant in source.request_times if "Info/" in path and "Price" in path
    ]
    assert all(b - a >= 30 for a, b in zip(current, current[1:], strict=False))


async def test_slow_requests_do_not_overlap_or_trigger_catchup_burst(pg_database):
    db, _ = pg_database
    clock = FakeClock()
    source = TimedSource(clock)
    source.slow = 10
    result, _ = await run_service(db, config(clock), clock, source)
    times = [when for path, when in source.request_times if "GetClosingPriceInfo" in path]
    assert result["completed_jobs"] == 3
    assert all(b - a >= 40 for a, b in zip(times, times[1:], strict=False))


async def test_duplicate_service_ownership_and_cancellation_during_retrieval(pg_database):
    db, _ = pg_database
    clock = FakeClock()
    source = TimedSource(clock)
    waiting, release = asyncio.Event(), asyncio.Event()
    original = source.get_json

    async def blocked(path):
        waiting.set()
        await release.wait()
        return await original(path)

    source.get_json = blocked
    task = asyncio.create_task(run_service(db, config(clock), clock, source))
    await waiting.wait()
    other = TimedSource(clock)
    with pytest.raises(OwnershipError):
        await run_service(db, config(clock), clock, other)
    assert not other.calls
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with db.read() as conn:
        report = await health_report(conn, A, clock.now())
        assert report["process_state"] == "stopped"
        assert report["failed_or_interrupted_runs"][0]["status"] == "interrupted"


async def test_lost_postgres_connection_releases_owner_and_preserves_pending_work(pg_database):
    db, _ = pg_database
    clock = FakeClock()
    async with db.owner(A) as conn:
        repo = Repository(conn, A)
        source = TimedSource(clock)
        original = source.get_json
        pid = await conn.scalar(sa.text("SELECT pg_backend_pid()"))
        await conn.commit()

        async def terminate(path):
            response = await original(path)
            if "GetClosingPriceInfo" in path:
                async with db.engine.connect() as admin:
                    await admin.execute(sa.text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
            return response

        source.get_json = terminate
        with pytest.raises((sa.exc.SQLAlchemyError, OwnershipError)):
            await CollectionService(
                repo, BudgetSource(source, A, 10), config(clock), clock=clock, kind="synthetic"
            ).run()
    assert await count(db, t.snapshots) == 0
    async with db.read() as conn:
        report = await health_report(conn, A, clock.now())
        assert report["process_state"] == "interrupted_owner_absent"


async def test_two_synthetic_services_and_health_are_isolated(pg_database):
    db, _ = pg_database
    for code in (A, B):
        clock = FakeClock()
        await run_service(db, config(clock, code=code, max_jobs=1), clock)
    async with db.read() as conn:
        for code in (A, B):
            report = await health_report(conn, code, NOW)
            assert report["ins_code"] == code and report["latest"] is not None
            assert len(report["scheduled_jobs"]) == 1
            assert report["scheduled_jobs"][0]["ins_code"] == code
        assert await conn.scalar(sa.select(sa.func.count()).select_from(s.runtime)) == 2


async def test_audit_cannot_choose_a_valid_unresolved_target_conflict(pg_database):
    db, _ = pg_database
    from datetime import date

    from .helpers import row

    source = SyntheticSource()
    await ingest(db, source)
    source.target[20250729] = row(pClosing=1022)
    await ingest(db, source, "reconcile-history", dates=[date(2025, 7, 29)])
    source.rows[0]["pClosing"] = 1022
    audit = await ingest(db, source, "audit-history")
    assert audit["conflict"] == 1 and audit["corrected"] == 0
    assert await count(db, t.revisions) == 0
    async with db.read() as conn:
        assert await conn.scalar(sa.select(t.daily.c.official_close)) == 1020


async def test_delayed_daily_publication_changes_and_flags_never_establish_finality(pg_database):
    from .helpers import row

    db, _ = pg_database
    clock = FakeClock()
    source = TimedSource(clock)
    original = source.get_json

    async def publication(path):
        source.rows = (
            []
            if clock.monotonic() < 60
            else [
                row(
                    day=20260321,
                    pClosing=1020 if clock.monotonic() < 120 else 1021,
                    iClose=True,
                    yClose=True,
                    last=True,
                )
            ]
        )
        return await original(path)

    source.get_json = publication
    recent = ScheduledJob(
        "publication",
        "refresh-history",
        NOW,
        60,
        eligibility="OPERATOR_WINDOW",
        provenance="Synthetic publication test",
    )
    cfg = config(clock, jobs=[recent], end=NOW + timedelta(seconds=185))
    await run_service(db, cfg, clock, source)
    async with db.read() as conn:
        assert await conn.scalar(sa.select(t.daily.c.finalization_state)) == "source_unverified"
        assert await conn.scalar(sa.select(t.daily.c.official_close)) == 1021
    assert await count(db, t.revisions) == 1 and await count(db, t.coverage) == 1


async def test_retry_success_retains_failure_history_in_durable_checkpoint(pg_database):
    db, _ = pg_database
    clock = FakeClock()
    source = TimedSource(clock)
    source.error = TransportError(ErrorKind.TIMEOUT, "synthetic transient failure")
    original_sleep = clock.sleep

    async def sleep(seconds):
        await original_sleep(seconds)
        if clock.monotonic() >= 60:
            source.error = None

    clock.sleep = sleep
    await run_service(db, config(clock, max_jobs=1), clock, source)
    async with db.read() as conn:
        run = (await conn.execute(sa.select(t.runs))).mappings().one()
        assert run["status"] == "success" and run["checkpoint"]["attempt_count"] == 2
        assert run["checkpoint"]["attempt_history"][0]["failure_category"] == "timeout"
        report = await health_report(conn, A, clock.now())
        assert report["source_availability"] == "http_observed"
        assert report["failed_or_interrupted_runs"][0]["checkpoint"]["attempt_history"]


async def test_actual_scheduler_process_death_recovers_committed_slot_without_refetch(pg_database):
    import os
    import subprocess
    import sys

    from .conftest import ROOT

    db, url = pg_database
    program = """
import asyncio, os, sys
sys.path.insert(0, 'tests')
from integration.test_automatic_collector import FakeClock, config, run_service
from tsetmc_marketdata.storage.database import Database
from tsetmc_marketdata.storage.config import DatabaseSettings
async def run():
    db = Database(DatabaseSettings(os.environ['TSETMC_DATABASE_URL']))
    clock = FakeClock()
    def fault(stage): os._exit(75)
    await run_service(db, config(clock, max_jobs=1), clock, fault=fault)
asyncio.run(run())
"""
    child = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-c", program],
        cwd=ROOT,
        env={**os.environ, "TSETMC_DATABASE_URL": url},
        capture_output=True,
        timeout=30,
    )
    assert child.returncode == 75, "child failed; private diagnostics withheld"
    async with db.read() as conn:
        assert (await health_report(conn, A, NOW))["process_state"] == "interrupted_owner_absent"
    clock = FakeClock(NOW + timedelta(seconds=31))
    cfg = config(FakeClock(), max_jobs=1)
    result, source = await run_service(db, cfg, clock)
    assert result["completed_jobs"] == 1 and source.calls == []
    assert await count(db, t.snapshots) == 1


async def test_scheduler_cancellation_inside_persistence_does_not_advance_checkpoint(pg_database):
    db, _ = pg_database
    clock = FakeClock()
    cfg = config(clock, max_jobs=1, end=NOW + timedelta(seconds=180))

    def cancel(stage):
        if stage == "before_commit":
            raise asyncio.CancelledError()

    async with db.owner(A) as conn:
        service = CollectionService(
            Repository(conn, A, fault=cancel),
            BudgetSource(TimedSource(clock), A, 10),
            cfg,
            clock=clock,
            kind="synthetic",
        )
        with pytest.raises(asyncio.CancelledError):
            await service.run()
    assert await count(db, t.snapshots) == 0
    async with db.read() as conn:
        assert await conn.scalar(sa.select(s.schedules.c.last_completed_slot)) is None
    clock.advance(31)
    await run_service(db, cfg, clock)
    assert await count(db, t.snapshots) == 1


async def test_slow_commit_keeps_completion_relative_cadence_without_overlap(pg_database):
    db, _ = pg_database
    clock = FakeClock()
    source = TimedSource(clock)
    cfg = config(clock, max_jobs=3, end=NOW + timedelta(seconds=150))

    def slow_commit(stage):
        if stage == "before_commit":
            # Deterministic elapsed commit time, not a PostgreSQL performance claim.
            clock.advance(12)

    async with db.owner(A) as conn:
        budget = BudgetSource(source, A, 10)
        result = await CollectionService(
            Repository(conn, A, fault=slow_commit),
            budget,
            cfg,
            clock=clock,
            kind="synthetic",
        ).run()
    times = [tick for path, tick in source.request_times if "GetClosingPriceInfo" in path]
    assert times == [0, 42, 84]
    assert result["completed_jobs"] == 3 and await count(db, t.snapshots) == 3
    jobs = [event for event in budget.events if event["kind"] == "committed_job"]
    assert all(event["receipt_to_schedule_commit_seconds"] == 12 for event in jobs)
