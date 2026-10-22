"""Retry policy preserves exact bytes and distinguishes transient from permanent failures."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from tsetmc_marketdata import simple_delivery as delivery


@pytest.mark.parametrize("status", [429, 503, 507])
async def test_transient_http_retry_preserves_bytes_and_honors_date(
    status, tmp_path, monkeypatch, capsys
):
    sent, sleeps = [], []
    retry_at = format_datetime(datetime.now(UTC) + timedelta(seconds=120))

    async def response(request):
        sent.append(request.content)
        if len(sent) == 1:
            return httpx.Response(status, headers={"Retry-After": retry_at})
        batch = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "batch_id": batch["batch_id"],
                "sha256": hashlib.sha256(request.content).hexdigest(),
                "accepted": 1,
            },
        )

    async def sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(delivery.asyncio, "sleep", sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
        pending = delivery.PendingUpload("http://company", tmp_path / "pending.json", http)
        pending.stage([{"synthetic": True}])
        await pending.drain()
        assert not pending.path.exists()
    assert sent[0] == sent[1]
    assert 115 <= sleeps[0] <= 120
    output = capsys.readouterr().out
    assert f"HTTP {status}" in output and "API recovered" in output


@pytest.mark.parametrize("receipt", [[], None, "not-json"])
async def test_malformed_receipt_keeps_file(receipt, tmp_path):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, content=json.dumps(receipt) if receipt != "not-json" else "not-json"
            )
        )
    ) as http:
        pending = delivery.PendingUpload("http://company", tmp_path / "pending.json", http)
        pending.stage([{"synthetic": True}])
        original = pending.path.read_bytes()
        with pytest.raises(ValueError, match="receipt"):
            await pending.drain()
        assert pending.path.read_bytes() == original


async def test_access_denied_does_not_retry(tmp_path, monkeypatch):
    async def unexpected_sleep(_):
        pytest.fail("permanent rejection must not retry")

    monkeypatch.setattr(delivery.asyncio, "sleep", unexpected_sleep)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(403))
    ) as http:
        pending = delivery.PendingUpload("http://company", tmp_path / "pending.json", http)
        pending.stage([{"synthetic": True}])
        with pytest.raises(ValueError, match="HTTP 403"):
            await pending.drain()
        assert pending.path.exists()


async def test_network_failures_back_off_and_preserve_file_on_cancel(tmp_path, monkeypatch, capsys):
    sleeps = []

    async def response(_):
        raise httpx.ConnectError("sensitive connection text")

    async def sleep(delay):
        sleeps.append(delay)
        if len(sleeps) == 5:
            raise delivery.asyncio.CancelledError()

    monkeypatch.setattr(delivery.asyncio, "sleep", sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
        pending = delivery.PendingUpload("http://company", tmp_path / "pending.json", http)
        pending.stage([{"synthetic": True}])
        original = pending.path.read_bytes()
        with pytest.raises(delivery.asyncio.CancelledError):
            await pending.drain()
        assert pending.path.read_bytes() == original
    assert sleeps == [30, 60, 120, 240, 300]
    output = capsys.readouterr().out
    assert "ConnectError" in output and "sensitive connection text" not in output


@pytest.mark.parametrize("header", ["NaN", "Infinity", "bad-date", "-1"])
def test_invalid_retry_after_uses_minimum(header):
    assert delivery.retry_delay(header, 60) == 60


def test_long_retry_after_is_not_shortened():
    assert delivery.retry_delay("7200", 60) == 7200
