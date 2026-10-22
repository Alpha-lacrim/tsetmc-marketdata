import asyncio
import json
import socket
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import format_datetime

import httpx
import pytest

from tsetmc_marketdata.config import PILOT_INS_CODE, Settings
from tsetmc_marketdata.errors import ErrorKind, SourceDataError, TransportError
from tsetmc_marketdata.providers.closing_prices import fetch_current, fetch_daily, fetch_history
from tsetmc_marketdata.providers.http_client import TSETMCClient
from tsetmc_marketdata.providers.instruments import fetch_instrument


def settings(**kwargs):
    return Settings(pacing_seconds=0, backoff_seconds=0, **kwargs)


async def test_connection_reuse_lifecycle_precision():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=b'{"price":0.10000000000000000001}')

    client = TSETMCClient(settings(), transport=httpx.MockTransport(handle))
    async with client:
        a = await client.get_json("a")
        b = await client.get_json("b")
        assert not client.is_closed
        assert a.payload["price"] == Decimal("0.10000000000000000001")
        assert a.received_at.tzinfo == UTC and b.received_at >= a.received_at
        assert a.raw_body == b'{"price":0.10000000000000000001}'
    assert client.is_closed and len(requests) == 2
    with pytest.raises(RuntimeError):
        await client.get_json("a")


@pytest.mark.parametrize(
    "status,kind,retries",
    [
        (401, ErrorKind.ACCESS_DENIED, 1),
        (403, ErrorKind.ACCESS_DENIED, 1),
        (404, ErrorKind.HTTP, 1),
        (400, ErrorKind.HTTP, 1),
        (302, ErrorKind.HTTP, 1),
        (429, ErrorKind.RATE_LIMIT, 3),
        (500, ErrorKind.SERVER, 3),
        (502, ErrorKind.SERVER, 3),
        (503, ErrorKind.SERVER, 3),
        (504, ErrorKind.SERVER, 3),
        (501, ErrorKind.SERVER, 1),
    ],
)
async def test_status_policy(status, kind, retries):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, text="not logged; secret-token")

    async with TSETMCClient(settings(), transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(TransportError) as error:
            await client.get_json("a")
    assert error.value.kind == kind and error.value.attempts == retries
    assert len(calls) == retries
    assert "secret-token" not in json.dumps(error.value.as_dict())


async def test_transient_error_recovers():
    statuses = iter([503, 429, 200])
    async with TSETMCClient(
        settings(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(next(statuses), json={"ok": True})
        ),
    ) as client:
        assert (await client.get_json("a")).payload == {"ok": True}


@pytest.mark.parametrize(
    "exception,kind",
    [
        (httpx.ConnectTimeout, ErrorKind.TIMEOUT),
        (httpx.ReadTimeout, ErrorKind.TIMEOUT),
        (httpx.WriteTimeout, ErrorKind.TIMEOUT),
        (httpx.PoolTimeout, ErrorKind.TIMEOUT),
        (httpx.ConnectError, ErrorKind.NETWORK),
        (httpx.ReadError, ErrorKind.NETWORK),
    ],
)
async def test_transport_retries(exception, kind):
    calls = []

    def handle(request):
        calls.append(request)
        raise exception("sensitive URL must not be logged", request=request)

    async with TSETMCClient(
        settings(max_retries=1), transport=httpx.MockTransport(handle)
    ) as client:
        with pytest.raises(TransportError) as error:
            await client.get_json("a")
    assert len(calls) == 2 and error.value.kind == kind
    assert "sensitive" not in str(error.value.as_dict())


async def test_dns_failure():
    def handle(request):
        try:
            raise socket.gaierror(socket.EAI_NONAME, "DNS failure")
        except socket.gaierror as exc:
            raise httpx.ConnectError("resolve failed", request=request) from exc

    async with TSETMCClient(
        settings(max_retries=0), transport=httpx.MockTransport(handle)
    ) as client:
        with pytest.raises(TransportError) as error:
            await client.get_json("a")
    assert error.value.kind == ErrorKind.DNS


@pytest.mark.parametrize(
    "body,kind",
    [
        (b"not json", ErrorKind.INVALID_JSON),
        (b"{", ErrorKind.INVALID_JSON),
        (b'{"n":NaN}', ErrorKind.INVALID_JSON),
        (b'{"a":1,"a":2}', ErrorKind.INVALID_JSON),
        (b"[]", ErrorKind.SCHEMA),
        (b"null", ErrorKind.SCHEMA),
    ],
)
async def test_source_errors_are_not_retried(body, kind):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=body)

    async with TSETMCClient(settings(), transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(SourceDataError) as error:
            await client.get_json("a")
    assert error.value.kind == kind and len(calls) == 1


async def test_total_deadline_and_closure():
    async def handle(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={})

    client = TSETMCClient(settings(total_timeout=0.01), transport=httpx.MockTransport(handle))
    with pytest.raises(TransportError) as error:
        async with client:
            await client.get_json("a")
    assert error.value.kind == ErrorKind.TIMEOUT and client.is_closed


async def test_cancellation_is_not_retried_and_closes():
    called = asyncio.Event()
    calls = []

    async def handle(request):
        calls.append(request)
        called.set()
        await asyncio.Event().wait()

    client = TSETMCClient(settings(), transport=httpx.MockTransport(handle))

    async def request():
        async with client:
            await client.get_json("a")

    task = asyncio.create_task(request())
    await called.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.is_closed and len(calls) == 1


async def test_pacing_concurrent_requests():
    starts = []

    def handle(request):
        starts.append(time.monotonic())
        return httpx.Response(200, json={})

    async with TSETMCClient(
        Settings(pacing_seconds=0.01), transport=httpx.MockTransport(handle)
    ) as client:
        await asyncio.gather(client.get_json("a"), client.get_json("b"), client.get_json("c"))
    assert all(b - a >= 0.009 for a, b in zip(starts, starts[1:], strict=False))


async def test_jitter_exponential_and_retry_after(monkeypatch):
    monkeypatch.setattr("tsetmc_marketdata.providers.http_client.random.random", lambda: 0.5)
    async with TSETMCClient(Settings(backoff_seconds=1, max_backoff_seconds=5)) as client:
        assert client._retry_delay(1, None) == 1.5
        assert client._retry_delay(2, None) == 3
        assert client._retry_delay(5, None) == 5
        assert client._retry_delay(1, httpx.Response(429, headers={"Retry-After": "4"})) == 4
        assert client._retry_delay(1, httpx.Response(429, headers={"Retry-After": "100"})) is None
        future = format_datetime(datetime.now(UTC) + timedelta(seconds=4), usegmt=True)
        assert (
            2 <= client._retry_delay(1, httpx.Response(429, headers={"Retry-After": future})) <= 4
        )


async def test_long_retry_after_stops():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "1000"})

    async with TSETMCClient(settings(), transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(TransportError):
            await client.get_json("a")
    assert len(calls) == 1


async def test_endpoint_services(history_payload, current_payload, instrument_payload):
    def handle(request):
        path = request.url.path
        payload = (
            instrument_payload
            if "GetInstrumentInfo" in path
            else current_payload
            if "GetClosingPriceInfo" in path
            else {"closingPriceDaily": history_payload["closingPriceDaily"][0]}
            if "GetClosingPriceDaily/" in path
            else history_payload
        )
        # Our fixtures contain Decimal. Encoding the saved source is an exact round trip.
        from tsetmc_marketdata.jsonio import diagnostic_default

        return httpx.Response(200, text=json.dumps(payload, default=diagnostic_default))

    async with TSETMCClient(settings(), transport=httpx.MockTransport(handle)) as client:
        history, _ = await fetch_history(client, PILOT_INS_CODE)
        current, _ = await fetch_current(client, PILOT_INS_CODE)
        instrument, _ = await fetch_instrument(client, PILOT_INS_CODE)
        daily, _ = await fetch_daily(client, PILOT_INS_CODE, history.records[-1].trading_date)
    assert len(history.records) == 2 and current.received_at is not None
    assert instrument.symbol == "فولاد" and daily.trade_count == 1234


async def test_invalid_instrument_and_path():
    async with TSETMCClient(
        settings(), transport=httpx.MockTransport(lambda r: httpx.Response(200))
    ) as client:
        with pytest.raises(ValueError):
            await fetch_history(client, "../123")
        with pytest.raises(ValueError):
            await client.get_json("https://other.test/secret")
        with pytest.raises(ValueError):
            await fetch_history(client, PILOT_INS_CODE, source_limit=-1)


def test_environment_configuration(monkeypatch):
    monkeypatch.setenv("TSETMC_READ_TIMEOUT", "8")
    monkeypatch.setenv("TSETMC_MAX_RETRIES", "0")
    assert Settings.from_env().read_timeout == 8 and Settings.from_env().max_retries == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"base_url": "https://user:secret@example.com/api/"},
        {"base_url": "https://example.com/?key=secret"},
        {"base_url": "file:///local/"},
        {"read_timeout": 0},
        {"total_timeout": -1},
        {"max_retries": 6},
        {"pacing_seconds": float("nan")},
    ],
)
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        replace(Settings(), **kwargs)
