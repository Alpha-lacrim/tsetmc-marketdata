"""No network: delivery configuration and transport trust boundaries."""

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from tsetmc_marketdata.delivery import DeliveryConfig, DeliveryError, Worker
from tsetmc_marketdata.storage.config import DatabaseSettings
from tsetmc_marketdata.storage.database import Database
from tsetmc_marketdata.storage.outbox import RecoveryFence, SourceOutbox
from tsetmc_marketdata.storage.repository import Repository


def config(tmp_path, **changes):
    data = dict(
        endpoint="https://company.example",
        ins_code="900000000000000001",
        producer_id=str(uuid4()),
        destination_id=str(uuid4()),
        session_id=str(uuid4()),
        session_generation=1,
        token_file=str(tmp_path / "token"),
        anchor_file=str(tmp_path / "anchor"),
    )
    data.update(changes)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    return DeliveryConfig.load(path)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://company.example",
        "https://name:password@company.example",
        "https://company.example/api",
        "https://company.example?secret=x",
        "file:///private",
    ],
)
def test_https_origin_only(tmp_path, endpoint):
    with pytest.raises(ValueError, match="HTTPS"):
        config(tmp_path, endpoint=endpoint)


def test_explicit_private_paths_and_generation(tmp_path):
    with pytest.raises(ValueError, match="absolute"):
        config(tmp_path, anchor_file="relative.json")
    with pytest.raises(ValueError, match="generation"):
        config(tmp_path, session_generation=True)
    assert config(tmp_path).session_generation == 1


@pytest.mark.parametrize(
    "status,retryable",
    [(307, False), (401, False), (403, False), (409, False), (429, True), (503, True)],
)
async def test_transport_classification_without_body_or_token_leaks(tmp_path, status, retryable):
    settings = config(tmp_path)
    settings.token_file.write_text("test." + "a" * 43)
    db = Database(DatabaseSettings("postgresql+asyncpg://tsetmc_test@127.0.0.1/tsetmc_test_ab"))
    worker = Worker(db, settings)
    await worker.http.aclose()
    worker.http = httpx.AsyncClient(
        base_url=settings.endpoint,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                status, text="secret diagnostic", headers={"Location": "https://evil.example"}
            )
        ),
    )
    try:
        with pytest.raises(DeliveryError) as caught:
            await worker.request("POST", "/session", b"{}")
        assert caught.value.retryable is retryable
        assert str(caught.value) == "http_" + str(status)
    finally:
        await worker.http.aclose()
        await db.aclose()


@pytest.mark.parametrize("operation", ["stage", "receive", "acknowledge"])
async def test_connection_info_does_not_authorize_delivery(operation):
    connection = SimpleNamespace(info={"authenticated_delivery": True})
    box = SourceOutbox(Repository(connection, "900000000000000001"))
    with pytest.raises(ValueError, match="fenced delivery"):
        if operation == "stage":
            await box.stage(
                "tsetmc_daily", batch_id=uuid4(), session_id=uuid4(), session_generation=1
            )
        elif operation == "receive":
            await box.receive(uuid4(), {})
        else:
            await box.acknowledge(uuid4())


@pytest.mark.parametrize(
    "closed,invalidated,active", [(True, False, True), (False, True, True), (False, False, False)]
)
async def test_delivery_fence_rejects_ended_transaction(tmp_path, closed, invalidated, active):
    worker = Worker(None, config(tmp_path))
    try:
        with pytest.raises(RecoveryFence, match="no longer active"):
            await worker.fence(
                SimpleNamespace(
                    closed=closed, invalidated=invalidated, in_transaction=lambda: active
                )
            )
    finally:
        await worker.http.aclose()
