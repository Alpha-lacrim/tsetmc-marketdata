"""Regression tests against genuine 2026-10-19 captures, with no HTTP calls."""

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tsetmc_marketdata.adapters.chartdata import to_chartdata
from tsetmc_marketdata.config import PILOT_INS_CODE as CODE
from tsetmc_marketdata.errors import RecordError
from tsetmc_marketdata.jsonio import loads_source
from tsetmc_marketdata.parsing import (
    parse_current,
    parse_daily,
    parse_history,
    parse_instrument,
    parse_targeted_daily,
)

CAPTURES = Path(__file__).parents[2] / "docs/evidence/qualification"
_REQUIRED_CAPTURES = (
    "manifest.json",
    "instrument.json",
    "history-0.json",
    "history-1.json",
    "history-2.json",
    "daily.json",
    "daily-anomaly.json",
    "current.json",
)
pytestmark = [
    pytest.mark.private_capture,
    pytest.mark.skipif(
        not all((CAPTURES / name).is_file() for name in _REQUIRED_CAPTURES),
        reason="private genuine captures are not distributed; see docs/publication-audit.md",
    ),
]


def load(name):
    return loads_source((CAPTURES / f"{name}.json").read_bytes())


def test_captured_body_hashes_and_aware_provenance():
    for item in json.loads((CAPTURES / "manifest.json").read_text()):
        assert item["status"] == 200
        body = (CAPTURES / (item["name"] + ".json")).read_bytes()
        assert hashlib.sha256(body).hexdigest() == item["sha256"]
        assert datetime.fromisoformat(item["received_at"]).tzinfo == UTC


def test_captured_instrument_identity():
    instrument = parse_instrument(load("instrument"), CODE)
    assert instrument.symbol == "فولاد" and instrument.instrument_id == "IRO1FOLD0001"
    assert instrument.isin == "IRO1FOLD0009"


def test_full_captured_history_quarantines_one_row_only():
    payload = load("history-0")
    history = parse_history(payload, CODE)
    assert len(payload["closingPriceDaily"]) == 4661
    assert len(history.records) == 4660
    assert history.records[0].trading_date == date(2007, 3, 11)
    assert history.records[-1].trading_date == date(2026, 10, 18)
    assert len(history.diagnostics) == 1
    assert history.diagnostics[0].raw["dEven"] == 20250729
    assert history.diagnostics[0].raw["priceFirst"] == 0
    assert len(to_chartdata(history.records).a) == 4660


def test_captured_limit_and_latest_targeted_semantics():
    rows = load("history-0")["closingPriceDaily"]
    assert load("history-1")["closingPriceDaily"] == rows[:1]
    assert load("history-2")["closingPriceDaily"] == rows[:2]
    assert load("daily")["closingPriceDaily"] == rows[0]


def test_captured_targeted_endpoint_disagrees_with_list_open():
    listed = next(r for r in load("history-0")["closingPriceDaily"] if r["dEven"] == 20250729)
    targeted = load("daily-anomaly")["closingPriceDaily"]
    assert listed["priceFirst"] == 0 and targeted["priceFirst"] == 2956
    assert {k: v for k, v in listed.items() if k != "priceFirst"} == {
        k: v for k, v in targeted.items() if k != "priceFirst"
    }
    with pytest.raises(RecordError):
        parse_daily(listed, CODE)
    assert parse_targeted_daily(
        {"closingPriceDaily": targeted}, CODE, date(2025, 7, 29)
    ).opening_price == Decimal(2956)


def test_captured_official_close_outside_positive_range():
    rows = load("history-0")["closingPriceDaily"]
    outside = [
        r
        for r in rows
        if r["zTotTran"] > 0
        and r["qTotTran5J"] > 0
        and r["priceMin"] > 0
        and not r["priceMin"] <= r["pClosing"] <= r["priceMax"]
    ]
    assert len(outside) == 285
    record = parse_daily(outside[0], CODE)
    assert record.official_close == Decimal(3891) and record.low == record.high == Decimal(3904)


def test_captured_current_receipt_is_separate_from_source_clock():
    manifest = json.loads((CAPTURES / "manifest.json").read_text())
    receipt = datetime.fromisoformat(
        next(r["received_at"] for r in manifest if r["name"] == "current")
    )
    record = parse_current(load("current"), CODE, received_at=receipt)
    assert record.last_traded_price == Decimal(4450) and record.official_close == Decimal(4420)
    assert record.source_reported_at == datetime(2026, 10, 19, 8, 28, 3, tzinfo=UTC)
    assert record.received_at == receipt and record.received_at > record.source_reported_at
    assert record.ins_code == CODE and record.raw["insCode"] == "0"
