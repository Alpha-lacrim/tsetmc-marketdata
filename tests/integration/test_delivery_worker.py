"""Real source transactions with an explicitly simulated HTTPS company transport."""

import copy
from uuid import uuid4

import httpx
import pytest

from tsetmc_marketdata.collection.jobs import Collector
from tsetmc_marketdata.delivery import DeliveryConfig, Worker
from tsetmc_marketdata.storage import schema_v3b1 as p
from tsetmc_marketdata.storage.outbox import RecoveryFence
from tsetmc_marketdata.storage.publication_wire import decode
from tsetmc_marketdata.storage.repository import Repository

from .helpers import A, SyntheticSource
from .test_local_sync_state import simulated_receipt
from .test_persistence import ingest
from .test_source_outbox import enroll, rows

pytestmark = pytest.mark.postgres


async def test_worker_delivers_during_collection_and_checks_receipts_on_restart(
    pg_database, tmp_path
):
    db, _ = pg_database
    await ingest(db, SyntheticSource())
    binding, _ = await enroll(db)
    config = DeliveryConfig(
        endpoint="https://synthetic.example",
        ins_code=A,
        producer_id=binding["producer_id"],
        destination_id=binding["destination_id"],
        session_id=uuid4(),
        session_generation=1,
        token_file=tmp_path / "token",
        anchor_file=tmp_path / "anchor",
    )
    config.token_file.write_text("synthetic." + "a" * 43)
    receipts = {}
    uploads = []
    workers = []
    collector_connection = None

    async def run():
        worker = Worker(db, config)
        workers.append(worker)

        async def respond(request):
            if request.url.path.endswith("/session/renew"):
                return httpx.Response(
                    200,
                    json=dict(
                        producer_id=str(config.producer_id),
                        session_id=str(config.session_id),
                        session_generation=1,
                        streams=worker.state["streams"],
                    ),
                )
            if request.method == "GET":
                receipt = receipts.get(request.url.path.rsplit("/", 1)[-1])
                return httpx.Response(200, json=receipt) if receipt else httpx.Response(404)
            batch = decode(request.content)
            assert request.url.path.endswith("/tsetmc/batches")
            uploads.append(request.content)
            if collector_connection is not None and len(uploads) == 1:
                with pytest.raises(RecoveryFence, match="producer already owned"):
                    await Worker(db, config).run(seconds=1)
                # Publication must finish while the delivery HTTP request is in flight.
                await Collector(
                    Repository(collector_connection, A), SyntheticSource(), kind="synthetic"
                ).run("observe-current")
            receipt = simulated_receipt(request.content, binding)
            receipts[batch["batch_id"]] = receipt
            return httpx.Response(200, json=receipt)

        await worker.http.aclose()
        worker.http = httpx.AsyncClient(
            base_url=config.endpoint, transport=httpx.MockTransport(respond)
        )
        return await worker.run(seconds=30)

    async with db.owner(A) as owner:
        collector_connection = owner
        assert await run() > 0
    collector_connection = None
    saved = await rows(db, p.batches)
    assert saved and all(r["phase"] == "acknowledged" and not r["simulated"] for r in saved)
    count = len(uploads)
    assert await run() == 0
    assert len(uploads) == count
    for worker in workers:
        with pytest.raises(RecoveryFence, match="coordinator lost"):
            async with worker.transaction():
                pytest.fail("stopped worker retained delivery authority")
    key = next(iter(receipts))
    changed = copy.deepcopy(receipts[key])
    changed["server_ingested_at"] = "2026-03-23T10:00:00Z"
    receipts[key] = changed
    with pytest.raises(RecoveryFence, match="company continuity mismatch"):
        await run()
    assert len(uploads) == count
