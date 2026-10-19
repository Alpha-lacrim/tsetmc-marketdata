"""Offline policy tests; source data here is explicitly synthetic."""

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest

from tsetmc_marketdata.collection.instruments import load_instruments
from tsetmc_marketdata.collection.scheduler import PollPolicy, poll
from tsetmc_marketdata.collection.source import CaptureReplay
from tsetmc_marketdata.config import Settings
from tsetmc_marketdata.errors import ErrorKind, TransportError
from tsetmc_marketdata.parsing import parse_current, parse_daily
from tsetmc_marketdata.storage.config import DatabaseSettings
from tsetmc_marketdata.storage.ordering import choose_latest
from tsetmc_marketdata.storage.serialization import (
    canonical_hash,
    decimal_text,
    financial_state,
    numeric_values,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("123456789012345678901234567890.1234567890", "123456789012345678901234567890.123456789"),
        ("1.000", "1"),
        ("0.00100", "0.001"),
        ("1E+31", "10000000000000000000000000000000"),
        ("-0.000", "0"),
    ],
)
def test_decimal_serialization_never_uses_context_rounding(text, expected):
    assert decimal_text(Decimal(text)) == expected


def test_canonical_financial_hash(daily_raw):
    record = parse_daily(daily_raw, daily_raw["insCode"])
    assert canonical_hash({"a": Decimal("1.00"), "b": 2}) == canonical_hash(
        {"b": 2, "a": Decimal("1")}
    )
    assert canonical_hash(financial_state(record)) == canonical_hash(
        financial_state(replace(record, raw={"irrelevant": True}))
    )
    assert canonical_hash(financial_state(record)) != canonical_hash(
        financial_state(replace(record, ins_code="900000000000000001"))
    )
    assert numeric_values(record)["traded_value"] == record.traded_value
    with pytest.raises(ValueError, match="NUMERIC"):
        numeric_values(replace(record, traded_value=Decimal("1e131072")))


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://tsetmc_owner:secret@example.com/tsetmc_marketdata",
        "postgresql+asyncpg://tsetmc_owner:secret@localhost/unrelated",
        "postgresql+asyncpg://postgres:secret@localhost/tsetmc_marketdata",
        "sqlite://",
        "not-a-url-containing-secret",
    ],
)
def test_database_isolation_guard_and_safe_repr(url):
    config = DatabaseSettings(url)
    assert "secret" not in repr(config)
    with pytest.raises(ValueError) as error:
        config.validated_url()
    assert "secret" not in str(error.value)


def test_database_config_explicit(monkeypatch):
    monkeypatch.delenv("TSETMC_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="required"):
        DatabaseSettings.from_env()
    settings = DatabaseSettings("postgresql+asyncpg://tsetmc_owner:p@127.0.0.1/tsetmc_test_abcd")
    assert settings.validated_url().database == "tsetmc_test_abcd"


def test_extensible_configuration(tmp_path):
    path = tmp_path / "instruments.json"
    rows = [{"ins_code": str(900000000000000001 + i), "enabled": True} for i in range(2)]
    path.write_text(json.dumps({"instruments": rows}))
    assert len(load_instruments(path)) == 2
    rows.append(rows[0])
    path.write_text(json.dumps({"instruments": rows}))
    with pytest.raises(ValueError, match="duplicate"):
        load_instruments(path)
    rows[0] = {"ins_code": 900000000000000001, "enabled": True}
    path.write_text(json.dumps({"instruments": rows}))
    with pytest.raises(ValueError, match="string"):
        load_instruments(path)


def test_configurable_request_concurrency(monkeypatch):
    monkeypatch.setenv("TSETMC_MAX_CONNECTIONS", "7")
    monkeypatch.setenv("TSETMC_PACING_SECONDS", "2.5")
    assert Settings.from_env().max_connections == 7
    assert Settings.from_env().pacing_seconds == 2.5
    with pytest.raises(ValueError):
        Settings(max_connections=0)


def test_current_ordering_unknown_precision_and_source_position(current_payload):
    now = datetime(2026, 3, 21, 10, tzinfo=UTC)
    record = parse_current(current_payload, "46348559193224090", received_at=now)
    digest = canonical_hash(financial_state(record))
    old = {
        "source_date": record.source_date,
        "source_time": None,
        "financial_hash": digest,
        "received_at": now,
    }
    assert choose_latest(old, record, digest).code == "same_state_more_precise_position"
    assert not choose_latest(old, record, "different").update
    old["source_time"] = time(12, 30, 45)
    assert choose_latest(old, replace(record, source_date=date(2026, 3, 22)), digest).update
    assert not choose_latest(old, replace(record, source_date=date(2026, 3, 20)), digest).update
    assert not choose_latest(old, record, "different", correction_reason=" ").update
    assert choose_latest(old, record, "different", correction_reason="reviewed").update


class FakeClock:
    def __init__(self):
        self.instant = datetime(2026, 3, 21, 4, tzinfo=UTC)
        self.delays = []

    def now(self):
        return self.instant

    async def sleep(self, seconds):
        self.delays.append(seconds)
        self.instant += timedelta(seconds=seconds)


async def test_scheduler_manual_window_unknown_market_and_restart():
    clock = FakeClock()
    calls = 0

    async def job():
        nonlocal calls
        calls += 1
        clock.instant += timedelta(seconds=10)  # A slow request is not overlapped.
        return {"instrument_state": "unknown"}

    result = await poll(job, PollPolicy(clock.now() + timedelta(seconds=100)), clock=clock)
    assert calls == 3 and result["observations"] == 3
    assert result["market_session_claimed"] is False and clock.delays == [30, 30, 10]
    result = await poll(job, PollPolicy(clock.now()), clock=clock)
    assert result["observations"] == 0


@pytest.mark.parametrize(
    "kind",
    [
        ErrorKind.ACCESS_DENIED,
        ErrorKind.RATE_LIMIT,
        ErrorKind.TIMEOUT,
        ErrorKind.SERVER,
        ErrorKind.DNS,
        ErrorKind.NETWORK,
    ],
)
async def test_scheduler_retry_decisions(kind):
    clock = FakeClock()
    calls = 0

    async def job():
        nonlocal calls
        calls += 1
        raise TransportError(kind, "synthetic failure")

    result = await poll(job, PollPolicy(clock.now() + timedelta(hours=1)), clock=clock)
    assert result["failure_category"] == kind.value
    assert calls == (1 if kind == ErrorKind.ACCESS_DENIED else 3)
    assert clock.delays == ([] if calls == 1 else [60, 120])


async def test_scheduler_cancellation_is_not_retried():
    async def job():
        raise asyncio.CancelledError()

    clock = FakeClock()
    with pytest.raises(asyncio.CancelledError):
        await poll(job, PollPolicy(clock.now() + timedelta(hours=1)), clock=clock)
    assert clock.delays == []


@pytest.mark.parametrize("seconds", [0, 1, 29, 3601])
def test_polling_policy_bounds(seconds):
    with pytest.raises(ValueError):
        PollPolicy(datetime.now(UTC), seconds)


async def test_private_capture_replay_verifies_original_evidence(tmp_path):
    body = b'{"publicSyntheticExample":1.000}'
    path = "Synthetic/Only"
    (tmp_path / "example.json").write_bytes(body)
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            [
                {
                    "name": "example",
                    "path": path,
                    "status": 200,
                    "received_at": "2026-01-01T00:00:00+00:00",
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
            ]
        )
    )
    replay = CaptureReplay(tmp_path)
    response = await replay.get_json(path)
    assert response.raw_body == body and response.payload["publicSyntheticExample"] == Decimal("1")
    (tmp_path / "example.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="hash"):
        await replay.get_json(path)
