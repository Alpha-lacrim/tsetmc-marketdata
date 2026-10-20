"""S04/S05 LOCAL simulated receipts; no upload, company server or credentials."""

import copy
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa

from tsetmc_marketdata.storage import schema_v1 as t
from tsetmc_marketdata.storage import schema_v3b1 as p
from tsetmc_marketdata.storage.config import OwnershipError
from tsetmc_marketdata.storage.outbox import (
    CapacityError,
    PublicationError,
    RecoveryFence,
    SourceOutbox,
)
from tsetmc_marketdata.storage.publication_wire import decode, record_sha
from tsetmc_marketdata.storage.queries import retain
from tsetmc_marketdata.storage.repository import Repository

from .helpers import A, B, SyntheticSource
from .test_persistence import ingest
from .test_source_outbox import daily_events, enroll, rows

pytestmark = pytest.mark.postgres


async def stage(db, stream, code=A, **kwargs):
    batch_id, session = uuid4(), uuid4()
    async with db.owner(code) as conn:
        repo = Repository(conn, code)
        async with repo.atomic():
            body = await SourceOutbox(repo).stage(
                stream,
                batch_id=batch_id,
                session_id=session,
                session_generation=1,
                simulate=True,
                **kwargs,
            )
    return batch_id, body


def simulated_receipt(body, binding):
    request = decode(body)
    receipt = {
        k: request[k]
        for k in (
            "protocol_version",
            "contract_version",
            "producer_id",
            "source_epoch",
            "batch_id",
            "instrument_id",
            "ownership_generation",
            "stream",
        )
    }
    receipt.update(
        destination_id=str(binding["destination_id"]),
        payload_sha256=hashlib.sha256(body).hexdigest(),
        state="committed",
        server_ingested_at="2026-03-22T10:00:00Z",
        event_cursor=None,
        counts={
            "applied": len(request["records"]),
            "recorded_no_change": 0,
            "superseded": 0,
            "duplicate": 0,
        },
        records=[
            {
                "observation_id": r["observation_id"],
                "source_position": r["source_position"],
                "record_sha256": record_sha(r),
                "outcome": "applied",
                "stored_state_version": r["observation"].get("state_version"),
                "stored_financial_hash": r["observation"].get("financial_hash"),
                "canonical_updated": r["kind"] in {"daily", "current"},
            }
            for r in request["records"]
        ],
    )
    return receipt


async def receive_ack(db, batch_id, receipt, code=A):
    async with db.owner(code) as conn:
        repo = Repository(conn, code)
        async with repo.atomic():
            await SourceOutbox(repo).receive(batch_id, receipt, simulate=True)
        async with repo.atomic():
            await SourceOutbox(repo).acknowledge(batch_id, simulate=True)


@pytest.mark.parametrize("stream", ["tsetmc_current", "tsetmc_status"])
async def test_s04_immutable_n_and_ack_n_leaves_n_plus_one_pending(pg_database, stream):
    db, _ = pg_database
    binding, _ = await enroll(db)
    source = SyntheticSource()
    await ingest(db, source, "observe-current")
    batch_id, body = await stage(db, stream)
    staged = decode(body)
    version = int(staged["records"][0]["source_position"])
    source.current["pClosing"] += 1
    source.current["hEven"] += 1
    source.receipt += timedelta(seconds=1)
    await ingest(db, source, "observe-current")
    # A -> B -> B with a newer clock: local false must still retain B pending.
    source.current["hEven"] += 1
    source.receipt += timedelta(seconds=1)
    await ingest(db, source, "observe-current")
    head = next(r for r in await rows(db, p.latest) if r["stream"] == stream)
    assert head["version"] > version
    if stream == "tsetmc_current":
        assert head["record"]["observation"]["financial_change"] is False
        assert head["record"]["observation"]["measurements"]["official_close"] == "1021"
    receipt = simulated_receipt(body, binding)
    await receive_ack(db, batch_id, receipt)
    pending = next(r for r in await rows(db, p.latest) if r["stream"] == stream)
    assert pending["version"] == head["version"] and pending["acknowledged_version"] == version
    saved = (await rows(db, p.batches))[0]
    assert bytes(saved["request_bytes"]) == body and saved["phase"] == "acknowledged"
    assert saved["simulated"] is True
    # A fresh instance can stage the successor after durable ACK; no process memory needed.
    _, successor = await stage(db, stream)
    assert int(decode(successor)["records"][0]["source_position"]) == head["version"]
    if stream == "tsetmc_status":
        original = staged["records"][0]["observation"]
        assert (
            original["expires_at"]
            == decode(bytes(saved["request_bytes"]))["records"][0]["observation"]["expires_at"]
        )


async def test_current_rejects_older_ambiguous_and_unknown_and_seed_repeated_pointer(pg_database):
    db, _ = pg_database
    source = SyntheticSource()
    await ingest(db, source, "observe-current")
    source.receipt += timedelta(seconds=1)
    await ingest(db, source, "observe-current")
    await enroll(db)
    initial = next(r for r in await rows(db, p.latest) if r["stream"] == "tsetmc_current")
    assert initial["record"]["event_type"] == "current.seed"
    assert initial["record"]["observation"]["accepted_decision"] == "repeated_state"
    for values in (
        {"dEven": 20260320, "pClosing": 1022},
        {"dEven": 20260321, "pClosing": 1022},
        {"dEven": 0, "hEven": 0, "pClosing": 1022},
    ):
        source.current.update(values)
        await ingest(db, source, "observe-current")
    latest = next(r for r in await rows(db, p.latest) if r["stream"] == "tsetmc_current")
    assert latest == initial
    source.current.update(dEven=20260321, hEven=123000, pClosing=1022)
    await ingest(db, source, "observe-current", correction_reason="Synthetic correction evidence")
    corrected = next(r for r in await rows(db, p.latest) if r["stream"] == "tsetmc_current")
    assert (
        corrected["record"]["observation"]["accepted_decision"] == "explicit_same_time_correction"
    )
    assert corrected["record"]["observation"]["correction_reason_sha256"]


async def test_daily_prefix_receipts_and_no_ack_without_saved_receipt(pg_database):
    db, _ = pg_database
    binding, _ = await enroll(db)
    source = SyntheticSource()
    await ingest(db, source)
    source.rows[0]["pClosing"] += 1
    await ingest(db, source)
    batch_id, body = await stage(db, "tsetmc_daily", limit=1)
    async with db.owner(A) as conn:
        repo = Repository(conn, A)
        with pytest.raises(PublicationError, match="receipt"):
            async with repo.atomic():
                await SourceOutbox(repo).acknowledge(batch_id, simulate=True)
    await receive_ack(db, batch_id, simulated_receipt(body, binding))
    second, body2 = await stage(db, "tsetmc_daily")
    assert [r["source_position"] for r in decode(body2)["records"]] == ["2"]
    await receive_ack(db, second, simulated_receipt(body2, binding))
    assert (
        next(r for r in await rows(db, p.clocks) if r["stream"] == "tsetmc_daily")["acknowledged"]
        == 2
    )


@pytest.mark.parametrize(
    "tamper",
    [
        "instrument",
        "epoch",
        "hash",
        "record_hash",
        "version",
        "missing",
        "duplicate",
        "count",
        "destination",
    ],
)
async def test_invalid_receipts_cannot_advance_checkpoint(pg_database, tamper):
    db, _ = pg_database
    binding, _ = await enroll(db)
    await ingest(db, SyntheticSource())
    batch_id, body = await stage(db, "tsetmc_daily")
    receipt = simulated_receipt(body, binding)
    if tamper in {"instrument", "epoch", "destination"}:
        receipt[
            {
                "instrument": "instrument_id",
                "epoch": "source_epoch",
                "destination": "destination_id",
            }[tamper]
        ] = str(uuid4())
    elif tamper == "hash":
        receipt["payload_sha256"] = "0" * 64
    elif tamper == "record_hash":
        receipt["records"][0]["record_sha256"] = "0" * 64
    elif tamper == "version":
        receipt["records"][0]["stored_state_version"] = "999"
    elif tamper == "missing":
        receipt["records"] = []
    elif tamper == "duplicate":
        receipt["records"].append(copy.deepcopy(receipt["records"][0]))
    else:
        receipt["counts"]["applied"] = 2
    with pytest.raises((ValueError, PublicationError)):
        await receive_ack(db, batch_id, receipt)
    assert (await rows(db, p.batches))[0]["phase"] == "staged"
    assert (
        next(r for r in await rows(db, p.clocks) if r["stream"] == "tsetmc_daily")["acknowledged"]
        == 0
    )


async def test_s05_isolation_constraints_immutability_and_binding(pg_database):
    db, _ = pg_database
    binding, _ = await enroll(db)
    await enroll(db, B)
    await ingest(db, SyntheticSource())
    await ingest(db, SyntheticSource(B))
    batch_id, body = await stage(db, "tsetmc_daily")
    receipt = simulated_receipt(body, binding)
    with pytest.raises(PublicationError):
        await receive_ack(db, batch_id, receipt, B)
    a = (await rows(db, p.outbox))[0]
    for mutation in ("outbox", "batch", "dataset", "fk"):
        with pytest.raises(sa.exc.DBAPIError):
            async with db.engine.begin() as conn:
                if mutation == "outbox":
                    await conn.execute(
                        p.outbox.update().where(p.outbox.c.ins_code == A).values(record={})
                    )
                elif mutation == "batch":
                    await conn.execute(
                        p.batches.update()
                        .where(p.batches.c.batch_id == batch_id)
                        .values(request_bytes=b"{}")
                    )
                elif mutation == "dataset":
                    await conn.execute(
                        p.datasets.update()
                        .where(p.datasets.c.ins_code == A)
                        .values(source_epoch=uuid4())
                    )
                else:
                    value = {**a, "ins_code": B, "observation_id": uuid4()}
                    await conn.execute(p.outbox.insert().values(**value))
    await receive_ack(db, batch_id, receipt)
    assert (
        next(r for r in await rows(db, p.clocks, B) if r["stream"] == "tsetmc_daily")[
            "acknowledged"
        ]
        == 0
    )
    async with db.owner(A) as conn:
        repo = Repository(conn, A)
        with pytest.raises(RecoveryFence):
            async with repo.atomic():
                await SourceOutbox(repo).configure(**{**binding, "source_epoch": uuid4()})


async def test_backend_loss_fences_local_publication(pg_database):
    db, _ = pg_database
    await enroll(db)
    async with db.owner(A) as conn:
        pid = await conn.scalar(sa.text("SELECT pg_backend_pid()"))
        await conn.commit()
        async with db.engine.begin() as killer:
            assert await killer.scalar(sa.text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
        with pytest.raises((sa.exc.DBAPIError, OwnershipError)):
            async with Repository(conn, A).atomic():
                pass
        with pytest.raises(OwnershipError):
            async with Repository(conn, A).atomic():
                pass


async def test_conservative_capacity_refuses_canonical_commit_and_reports_threshold(pg_database):
    db, _ = pg_database
    await enroll(db, max_rows=2)
    source = SyntheticSource()
    await ingest(db, source)
    source.rows[0]["pClosing"] += 1
    await ingest(db, source)
    original = await rows(db, t.daily)
    source.rows[0]["pClosing"] += 1
    # Failure-report publication is also bounded; no canonical/outbox data is lost.
    with pytest.raises(CapacityError):
        await ingest(db, source)
    assert await rows(db, t.daily) == original
    assert len(await daily_events(db)) == 2
    async with db.owner(A) as conn:
        repo = Repository(conn, A)
        async with repo.atomic():
            health = await SourceOutbox(repo).health()
            assert any(r["capacity"] == "critical" for r in health["streams"])


async def test_staged_evidence_survives_original_retention(pg_database):
    db, _ = pg_database
    await enroll(db)
    source = SyntheticSource()
    await ingest(db, source, "observe-current")
    await stage(db, "tsetmc_current")
    source.current["hEven"] += 1
    source.receipt += timedelta(seconds=1)
    await ingest(db, source, "observe-current")
    async with db.owner(A) as conn:
        repo = Repository(conn, A)
        async with repo.atomic():
            await retain(conn, A, apply=True, now=datetime(2028, 1, 1, tzinfo=UTC))
    assert len(await rows(db, t.snapshots)) == 2
    for r in await rows(db, p.evidence):
        async with db.read() as conn:
            body = await conn.scalar(
                sa.select(t.observations.c.raw_body).where(
                    t.observations.c.observation_id == r["local_observation_id"]
                )
            )
            assert body is not None


async def test_supplied_continuity_proof_fences_restore_without_epoch_rotation(pg_database):
    db, _ = pg_database
    binding, _ = await enroll(db)
    proof = {k: str(v) for k, v in binding.items()}
    proof["streams"] = {"tsetmc_daily": {"head": 1, "acknowledged": 0}}
    async with db.owner(A) as conn:
        repo = Repository(conn, A)
        with pytest.raises(RecoveryFence):
            async with repo.atomic():
                await SourceOutbox(repo).continuity(proof)
    assert (await rows(db, p.datasets))[0]["source_epoch"] == binding["source_epoch"]


async def test_resnapshot_cannot_promote_rejected_older_source_pointer(pg_database):
    db, _ = pg_database
    await enroll(db)
    source = SyntheticSource()
    await ingest(db, source, "observe-current")
    original = next(r for r in await rows(db, p.latest) if r["stream"] == "tsetmc_current")
    source.current.update(dEven=20260320, pClosing=1021)
    await ingest(db, source, "observe-current")
    # Simulate partial source corruption in this disposable DB, not a normal mutator.
    async with db.owner(A) as conn:
        repo = Repository(conn, A)
        async with repo.atomic():
            rejected = await conn.scalar(
                sa.select(t.snapshots.c.snapshot_id).where(
                    t.snapshots.c.ins_code == A, t.snapshots.c.decision == "older_session"
                )
            )
            await conn.execute(
                t.latest.update().where(t.latest.c.ins_code == A).values(snapshot_id=rejected)
            )
        with pytest.raises(PublicationError):
            async with repo.atomic():
                box = SourceOutbox(repo)
                await box.load()
                await box.lock_clocks()
                await box.current(resnapshot=True)
    assert next(r for r in await rows(db, p.latest) if r["stream"] == "tsetmc_current") == original


async def test_capture_cannot_be_disabled_after_enrollment(pg_database):
    db, _ = pg_database
    await enroll(db)
    with pytest.raises(sa.exc.DBAPIError):
        async with db.engine.begin() as conn:
            await conn.execute(
                p.datasets.update().where(p.datasets.c.ins_code == A).values(enabled=False)
            )


@pytest.mark.parametrize("limit", [0, 101])
async def test_staging_refuses_invalid_record_bounds(pg_database, limit):
    db, _ = pg_database
    await enroll(db)
    with pytest.raises(ValueError):
        await stage(db, "tsetmc_daily", limit=limit)


async def test_readonly_publication_status_does_not_register_an_instrument(pg_database):
    from tsetmc_marketdata.storage.queries import publication_report

    db, _ = pg_database
    async with db.read() as conn:
        report = await publication_report(conn, A)
        assert report == {
            "enabled": False,
            "enrolled": False,
            "network_delivery": False,
            "streams": [],
        }
        assert await conn.scalar(sa.select(sa.func.count()).select_from(t.instruments)) == 0
