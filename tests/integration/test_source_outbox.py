"""S01-S06 on real disposable PostgreSQL with two INVENTED instruments only."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import pytest
import sqlalchemy as sa

from tsetmc_marketdata.parsing import parse_daily
from tsetmc_marketdata.storage import schema_v1 as t
from tsetmc_marketdata.storage import schema_v3a as s
from tsetmc_marketdata.storage import schema_v3b1 as p
from tsetmc_marketdata.storage.database import SCHEMA_REVISION, verify_schema
from tsetmc_marketdata.storage.outbox import CapacityError, SourceOutbox
from tsetmc_marketdata.storage.publication_wire import (
    decode,
    encode,
    financial_hash,
    identity,
    record_sha,
)
from tsetmc_marketdata.storage.repository import Repository
from tsetmc_marketdata.storage.reviews import review_daily

from .conftest import ROOT, migration
from .helpers import A, B, SyntheticSource, row
from .test_daily_reviews import evidence
from .test_persistence import ingest

pytestmark = pytest.mark.postgres
DAY = date(2025, 7, 29)


async def enroll(db, code=A, **budgets):
    values = {
        key: uuid4() for key in ("source_epoch", "installation_id", "destination_id", "producer_id")
    }
    async with db.owner(code) as conn:
        repo = Repository(conn, code)
        async with repo.atomic():
            box = SourceOutbox(repo)
            await box.configure(**values, **budgets)
            result = await box.enroll(seed_id=uuid4(), allow_local_publication=True)
    return values, result


async def rows(db, table, code=A):
    async with db.read() as conn:
        query = (
            sa.select(table).where(table.c.ins_code == code).order_by(*table.primary_key.columns)
        )
        return [dict(r) for r in (await conn.execute(query)).mappings()]


async def daily_events(db, code=A):
    return [r["record"] for r in await rows(db, p.outbox, code) if r["stream"] == "tsetmc_daily"]


async def fingerprint(conn):
    result = {}
    for table in [*t.metadata.sorted_tables, *s.metadata.sorted_tables]:
        result[table.name] = [
            dict(r)
            for r in (
                await conn.execute(sa.select(table).order_by(*table.primary_key.columns))
            ).mappings()
        ]
    return result


async def test_disabled_default_and_exact_daily_publication(pg_database):
    db, _ = pg_database
    source = SyntheticSource()
    await ingest(db, source)
    assert not await rows(db, p.datasets)
    _, seed = await enroll(db)
    assert seed["daily_records"] == 1 and seed["network_delivery"] is False
    initial = (await daily_events(db))[0]
    assert initial["event_type"] == "daily.seed"
    for change in ({"last": False}, {"id": 999}):
        source.rows[0].update(change)
        await ingest(db, source)
    assert await daily_events(db) == [initial]
    source.rows[0].update(
        pClosing="1050.1234567890123456789",
        qTotCap="123456789012345678901234567890.123",
        zTotTran=10**30,
    )
    await ingest(db, source)
    corrected = (await daily_events(db))[-1]
    assert corrected["event_type"] == "daily.corrected"
    o = corrected["observation"]
    assert o["financial_revision"] == "2" and o["state_version"] == "2"
    assert o["measurements"]["official_close"] == "1050.1234567890123456789"
    assert o["measurements"]["trade_count"] == str(10**30)
    assert o["revision_evidence"]["old_financial_hash"] == initial["observation"]["financial_hash"]
    assert o["measurements"]["official_close"] > o["measurements"]["high"]
    for stored in await rows(db, p.outbox):
        assert bytes(stored["record_bytes"]) == encode(stored["record"])
        assert stored["record_sha256"] == record_sha(stored["record"])
        assert stored["observation_id"] == uuid5(
            stored["source_epoch"], stored["stream"] + ":" + str(stored["source_position"])
        )


async def test_s03_review_revoke_reconcile_and_conflict_quality(pg_database):
    db, _ = pg_database
    await enroll(db)
    source, args = await evidence(db)
    async with db.owner(A) as conn:
        await review_daily(Repository(conn, A), **args)
    confirmed = (await daily_events(db))[-1]
    assert confirmed["event_type"] == "daily.review_confirmed"
    # A later conflict discloses quality without erasing the historical review.
    source.target[20250729] = row(pClosing=1050)
    await ingest(db, source, "reconcile-history", dates=[DAY])
    disputed = (await daily_events(db))[-1]
    assert disputed["event_type"] == "daily.quality_changed"
    assert disputed["observation"]["reconciliation"]["open_quarantine_count"] == 1
    assert disputed["observation"]["financial_hash"] == confirmed["observation"]["financial_hash"]
    assert disputed["observation"]["local_finalization"] == "operator_finalized"
    async with db.owner(A) as conn:
        await review_daily(
            Repository(conn, A), **{**args, "review_id": uuid4(), "action": "revoke"}
        )
    revoked = (await daily_events(db))[-1]
    assert revoked["event_type"] == "daily.review_revoked"
    assert (
        revoked["observation"]["financial_revision"]
        == confirmed["observation"]["financial_revision"]
    )
    assert int(revoked["observation"]["state_version"]) > int(
        confirmed["observation"]["state_version"]
    )
    assert "synthetic-operator" not in encode(revoked).decode()
    assert "Synthetic manual review" not in encode(revoked).decode()


async def test_reconciliation_version_and_one_final_state_per_transaction(pg_database):
    db, _ = pg_database
    await enroll(db)
    source = SyntheticSource()
    await ingest(db, source)
    await ingest(db, source, "reconcile-history", dates=[DAY])
    events = await daily_events(db)
    assert [r["event_type"] for r in events] == ["daily.accepted", "daily.reconciled"]
    assert events[0]["observation"]["financial_hash"] == events[1]["observation"]["financial_hash"]
    await ingest(db, source, "reconcile-history", dates=[DAY])
    assert len(await daily_events(db)) == 2
    async with db.owner(A) as conn:
        repo = Repository(conn, A)
        async with repo.atomic(ingest=True):
            observation = await conn.scalar(
                sa.select(t.daily.c.observation_id).where(t.daily.c.ins_code == A)
            )
            await repo.quarantine_row(observation, 0, {"dEven": 20250729}, "synthetic invalid")
            await repo.quarantine_row(
                observation, 1, {"dEven": 20250729, "id": 2}, "synthetic invalid"
            )
    events = await daily_events(db)
    assert len(events) == 3
    assert events[-1]["observation"]["reconciliation"]["open_quarantine_count"] == 2


@pytest.mark.parametrize("operation", ["new", "correction", "current", "quarantine", "review"])
@pytest.mark.parametrize("boundary", ["before_commit", "after_commit"])
async def test_s01_actual_process_death_is_atomic(pg_database, operation, boundary):
    db, url = pg_database
    await enroll(db)
    if operation != "new":
        await ingest(db, SyntheticSource())
    initial_events = len(await daily_events(db))
    program = r"""
import asyncio,os
from datetime import UTC,date,datetime
from uuid import uuid4
import sqlalchemy as sa
from tests.integration.helpers import A,SyntheticSource,row
from tsetmc_marketdata.storage.database import Database
from tsetmc_marketdata.storage.config import DatabaseSettings
from tsetmc_marketdata.storage.repository import Repository
from tsetmc_marketdata.storage.reviews import review_daily
from tsetmc_marketdata.storage import schema_v1 as t
from tsetmc_marketdata.collection.jobs import Collector
async def run():
    db=Database(DatabaseSettings(os.environ['TASK_DB']))
    def fault(stage):
        if stage==os.environ['TASK_BOUNDARY']: os._exit(74)
    async with db.owner(A) as conn:
        repo=Repository(conn,A,fault=fault); operation=os.environ['TASK_OPERATION']
        if operation=='review':
            digest=await conn.scalar(sa.select(t.daily.c.financial_hash)
                .where(t.daily.c.ins_code==A))
            await conn.commit()
            await review_daily(repo,review_id=uuid4(),day=date(2025,7,29),
                expected_hash=digest,action='revoke',actor='synthetic',
                reason='synthetic',now=datetime(2026,3,22,tzinfo=UTC))
        elif operation=='quarantine':
            async with repo.atomic(ingest=True):
                oid=await conn.scalar(sa.select(t.daily.c.observation_id)
                    .where(t.daily.c.ins_code==A))
                await repo.quarantine_row(oid,0,{'dEven':20250729},'synthetic')
        else:
            source=SyntheticSource()
            if operation=='correction': source.rows[0]['pClosing']=1021
            job='observe-current' if operation=='current' else 'backfill-history'
            await Collector(repo,source,kind='synthetic').run(job)
asyncio.run(run())
"""
    child = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-c", program],
        cwd=ROOT,
        env={**os.environ, "TASK_DB": url, "TASK_BOUNDARY": boundary, "TASK_OPERATION": operation},
        capture_output=True,
        timeout=40,
    )
    assert child.returncode == 74, "child failed; private diagnostics withheld"
    committed = boundary == "after_commit"
    if operation == "current":
        assert bool(await rows(db, t.latest)) == committed
        assert (
            bool([r for r in await rows(db, p.latest) if r["stream"] == "tsetmc_current"])
            == committed
        )
    else:
        assert len(await daily_events(db)) == initial_events + int(committed)
        if operation == "correction":
            assert len(await rows(db, t.revisions)) == int(committed)
        if operation == "review":
            assert len(await rows(db, s.reviews)) == int(committed)
        if operation == "quarantine":
            assert len(await rows(db, t.quarantine)) == int(committed)
    daily_clock = next(r for r in await rows(db, p.clocks) if r["stream"] == "tsetmc_daily")
    assert daily_clock["head"] == len(await daily_events(db))


@pytest.mark.parametrize("rollback", [False, True])
async def test_s02_row_counter_serializes_commit_and_other_instrument_progress(
    pg_database, rollback
):
    db, _ = pg_database
    binding, _ = await enroll(db)
    await enroll(db, B)
    template = decode(
        (ROOT / "docs/contracts/milestone3b/examples/daily.request.json").read_bytes()
    )["records"][0]

    async def allocate(conn, code, epoch):
        pos = await conn.scalar(
            p.clocks.update()
            .where(p.clocks.c.ins_code == code, p.clocks.c.stream == "tsetmc_daily")
            .values(head=p.clocks.c.head + 1)
            .returning(p.clocks.c.head)
        )
        record = {
            **template,
            "source_position": str(pos),
            "observation_id": str(uuid5(epoch, f"tsetmc_daily:{pos}")),
        }
        record["observation"] = {**template["observation"], **identity(code, None)}
        record["observation"]["financial_hash"] = financial_hash(record["observation"])
        await conn.execute(
            p.outbox.insert().values(
                ins_code=code,
                source_epoch=epoch,
                stream="tsetmc_daily",
                source_position=pos,
                observation_id=UUID(record["observation_id"]),
                record=record,
                record_bytes=encode(record),
                record_sha256=record_sha(record),
                created_at=datetime.now(UTC),
            )
        )
        return pos

    async with db.engine.connect() as a:
        tx = await a.begin()
        assert await allocate(a, A, binding["source_epoch"]) == 1
        started = asyncio.Event()

        async def writer_b():
            async with db.engine.begin() as b:
                started.set()
                return await allocate(b, A, binding["source_epoch"])

        task = asyncio.create_task(writer_b())
        await started.wait()
        await asyncio.sleep(0.1)
        assert not task.done()
        # A different instrument's clock has no dependency on A's uncommitted tail.
        async with db.engine.begin() as other:
            epoch = await other.scalar(
                sa.select(p.datasets.c.source_epoch).where(p.datasets.c.ins_code == B)
            )
            assert await asyncio.wait_for(allocate(other, B, epoch), 2) == 1
        async with db.read() as read:
            assert not list(
                await read.scalars(
                    sa.select(p.outbox.c.source_position).where(p.outbox.c.ins_code == A)
                )
            )
        await tx.rollback() if rollback else await tx.commit()
        assert await asyncio.wait_for(task, 3) == (1 if rollback else 2)
    positions = [r["source_position"] for r in await rows(db, p.outbox)]
    assert positions == ([1] if rollback else [1, 2])


async def test_documented_unsafe_sequence_counterexample(pg_database):
    db, _ = pg_database
    async with db.engine.begin() as conn:
        await conn.execute(sa.text("CREATE SEQUENCE unsafe_demo"))
        await conn.execute(sa.text("CREATE TABLE unsafe_rows(position bigint PRIMARY KEY)"))
    async with db.engine.connect() as a:
        tx = await a.begin()
        first = await a.scalar(
            sa.text("INSERT INTO unsafe_rows VALUES(nextval('unsafe_demo')) RETURNING position")
        )
        async with db.engine.begin() as b:
            second = await b.scalar(
                sa.text("INSERT INTO unsafe_rows VALUES(nextval('unsafe_demo')) RETURNING position")
            )
        async with db.read() as conn:
            assert list(await conn.scalars(sa.text("SELECT position FROM unsafe_rows"))) == [second]
        await tx.commit()
        assert first < second  # A MAX-based checkpoint through second would now skip first.


async def test_s06_seed_4662_synthetic_days_preserves_all_original_tables(pg_database):
    db, _ = pg_database
    dates = [date(2007, 3, 11) + timedelta(days=i) for i in range(4662)]
    source = SyntheticSource(
        rows=[
            row(day=int(d.strftime("%Y%m%d")), pClosing=1050 if i < 285 else 1020)
            for i, d in enumerate(dates)
        ]
    )
    await ingest(db, source)
    source.rows[1000]["pClosing"] += 1
    await ingest(db, source)
    await ingest(db, source, "observe-current")
    async with db.read() as conn:
        before = await fingerprint(conn)
        assert sum(r["official_close"] > r["high"] for r in before["daily_records"]) == 285
    binding, result = await enroll(db)
    assert result["daily_records"] == 4662 and result["serialized_bytes"] < 32 * 1024 * 1024
    async with db.read() as conn:
        assert await fingerprint(conn) == before
        for r in before["source_observations"]:
            assert hashlib.sha256(r["raw_body"]).hexdigest() == r["raw_sha256"]
    events = await daily_events(db)
    assert events[0]["event_type"] == "daily.revision_seed"
    assert len([e for e in events if e["event_type"] == "daily.seed"]) == 4662
    pages = [r["record"] for r in await rows(db, p.outbox) if r["stream"] == "tsetmc_coverage"]
    assert len(pages) == 47 and sum(len(r["observation"]["coverage_rows"]) for r in pages) == 4662
    source.rows = [dict(source.rows[-1], pClosing=1021)]
    await ingest(db, source)
    correction = (await daily_events(db))[-1]
    assert correction["event_type"] == "daily.corrected"
    assert correction["observation"]["state_version"] == "2"
    assert int(correction["source_position"]) > len(events)
    # Report only invented-data size measurements; never infer actual pilot integrity.
    path = Path(
        os.environ.get(
            "TSETMC_SYNTHETIC_SEED_REPORT", ROOT / ".local/milestone3b1/synthetic-seed.json"
        )
    )
    if path.parent.is_dir():
        await asyncio.to_thread(
            path.write_text,
            json.dumps(
                {
                    **result,
                    "source_epoch": str(binding["source_epoch"]),
                    "original_tables_equal": True,
                    "synthetic": True,
                },
                indent=2,
            ),
        )


@pytest.mark.parametrize("bound", ["rows", "bytes"])
async def test_seed_limits_rollback_without_enabling_or_editing_canonical(pg_database, bound):
    db, _ = pg_database
    await ingest(db, SyntheticSource())
    async with db.read() as conn:
        before = await fingerprint(conn)
    with pytest.raises(CapacityError):
        async with db.owner(A) as conn:
            repo = Repository(conn, A)
            async with repo.atomic():
                box = SourceOutbox(repo)
                await box.configure(
                    **{
                        k: uuid4()
                        for k in (
                            "source_epoch",
                            "installation_id",
                            "destination_id",
                            "producer_id",
                        )
                    }
                )
                await box.enroll(
                    seed_id=uuid4(),
                    allow_local_publication=True,
                    **({"max_daily_rows": 0} if bound == "rows" else {"max_bytes": 1}),
                )
    assert not await rows(db, p.datasets) and not await rows(db, p.outbox)
    async with db.read() as conn:
        assert await fingerprint(conn) == before


async def test_populated_0003_upgrade_interruption_and_disposable_downgrade(pg_database):
    db, url = pg_database
    await ingest(db, SyntheticSource())
    await ingest(db, SyntheticSource(), "observe-current")
    async with db.read() as conn:
        before = await fingerprint(conn)
    await migration(db.engine, "downgrade", "0003_scheduling")
    program = """
import asyncio,os
from alembic import command
from alembic.config import Config
from tsetmc_marketdata.storage.config import DatabaseSettings
from tsetmc_marketdata.storage.database import make_engine
async def run():
    engine=make_engine(DatabaseSettings(os.environ['TASK_DB']))
    async with engine.begin() as conn:
        def run_sync(c):
            cfg=Config('alembic.ini'); cfg.attributes['connection']=c; command.upgrade(cfg,'head')
        await conn.run_sync(run_sync)
        os._exit(74)
asyncio.run(run())
"""
    child = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-c", program],
        cwd=ROOT,
        env={**os.environ, "TASK_DB": url},
        capture_output=True,
        timeout=30,
    )
    assert child.returncode == 74
    async with db.engine.connect() as conn:
        assert (
            await conn.scalar(sa.text("SELECT version_num FROM alembic_version"))
            == "0003_scheduling"
        )
        assert await conn.scalar(sa.text("SELECT to_regclass('sync_outbox')")) is None
        assert await fingerprint(conn) == before
    await migration(db.engine)
    async with db.read() as conn:
        assert (await verify_schema(conn))["schema_revision"] == SCHEMA_REVISION
        assert await fingerprint(conn) == before
        assert not await conn.scalar(sa.select(sa.func.count()).select_from(p.datasets))
    await migration(db.engine, "downgrade", "0003_scheduling")
    async with db.engine.connect() as conn:
        assert await fingerprint(conn) == before
    await migration(db.engine)


async def test_final_state_retains_two_intratransaction_corrections(pg_database):
    db, _ = pg_database
    await enroll(db)
    source = SyntheticSource()
    await ingest(db, source)
    async with db.owner(A) as conn:
        repo = Repository(conn, A)
        async with repo.atomic(ingest=True):
            run_id = await conn.scalar(sa.select(t.runs.c.run_id).where(t.runs.c.ins_code == A))
            for price in (1021, 1022):
                source.rows[0]["pClosing"] = price
                response = await source.get_json(f"ClosingPrice/GetClosingPriceDailyList/{A}/0")
                evidence_id = await repo.observation(run_id, response, kind="synthetic")
                await repo.daily_record(parse_daily(source.rows[0], A), evidence_id)
    events = await daily_events(db)
    assert [e["event_type"] for e in events] == [
        "daily.accepted",
        "daily.revision_seed",
        "daily.corrected",
    ]
    assert events[-1]["observation"]["state_version"] == "2"
    assert events[-1]["observation"]["financial_revision"] == "3"
    assert events[1]["observation"]["revision_evidence"]["financial_revision"] == "2"


async def test_invalid_only_day_publishes_coverage_without_accepted_financial_record(pg_database):
    db, _ = pg_database
    await enroll(db)
    await ingest(db, SyntheticSource(rows=[row(priceFirst=0)]))
    assert not await daily_events(db)
    coverage = [r for r in await rows(db, p.outbox) if r["stream"] == "tsetmc_coverage"]
    assert coverage[0]["record"]["observation"]["coverage_rows"][0]["financial_hash"] is None
