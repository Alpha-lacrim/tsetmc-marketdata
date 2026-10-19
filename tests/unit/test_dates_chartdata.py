import json
from dataclasses import replace
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest

from tsetmc_marketdata.adapters.chartdata import ChartData, to_chartdata
from tsetmc_marketdata.config import PILOT_INS_CODE as CODE
from tsetmc_marketdata.parsing import parse_daily, parse_history
from tsetmc_marketdata.utils.dates import (
    TEHRAN,
    calendar_gaps,
    daily_unix_seconds,
    gregorian_to_jalali,
    jalali_to_gregorian,
    parse_source_date,
    parse_source_time,
    source_instant,
)


@pytest.mark.parametrize(
    "gregorian,jalali",
    [
        (date(2024, 3, 20), "1403-01-01"),
        (date(2025, 3, 20), "1403-12-30"),
        (date(2025, 3, 21), "1404-01-01"),
        (date(2026, 3, 21), "1405-01-01"),
    ],
)
def test_calendar_roundtrip(gregorian, jalali):
    assert gregorian_to_jalali(gregorian) == jalali
    assert jalali_to_gregorian(jalali) == gregorian


def test_tehran_clock_and_utc_daily_label():
    day = date(2026, 8, 4)
    assert daily_unix_seconds(day) == 1785801600
    assert datetime.fromtimestamp(daily_unix_seconds(day), UTC) == datetime(2026, 8, 4, tzinfo=UTC)
    assert datetime(2026, 8, 4, tzinfo=UTC).astimezone(TEHRAN).hour == 3
    assert source_instant(day, time(9)) == datetime(2026, 8, 4, 5, 30, tzinfo=UTC)
    assert datetime.fromtimestamp(1785814200, UTC) == datetime(2026, 8, 4, 3, 30, tzinfo=UTC)


def test_historical_tehran_dst():
    assert source_instant(date(2021, 7, 1), time(9)) == datetime(2021, 7, 1, 4, 30, tzinfo=UTC)
    with pytest.raises(ValueError, match="ambiguous|nonexistent"):
        source_instant(date(2021, 3, 22), time(0, 30))


@pytest.mark.parametrize("value", [20260230, 20261301, "2026-01-01", "2026010", True, 20260101.0])
def test_invalid_source_dates(value):
    with pytest.raises(ValueError):
        parse_source_date(value)


@pytest.mark.parametrize("value", [240000, 126099, "no", True])
def test_invalid_source_clock(value):
    with pytest.raises(ValueError):
        parse_source_time(value)


def test_source_clock_leading_zero():
    assert parse_source_time(93005) == time(9, 30, 5)


def test_year_boundary_gaps_do_not_create_candles():
    days = [date(2026, 1, 2), date(2025, 12, 31), date(2026, 1, 2)]
    assert calendar_gaps(days) == [(date(2026, 1, 1), date(2026, 1, 1), 1)]


def test_chart_exact_mapping_sorted(history_payload):
    records = parse_history(history_payload, CODE).records
    chart = to_chartdata(list(reversed(records)))
    assert chart.to_dict() == {
        "a": [1767139200, 1774051200],
        "b": [995.0, 1010.25],
        "c": [998.0, 1020.25],
        "d": [1010.0, 1040.75],
        "e": [980.0, 1005.0],
        "f": [2345, 1234],
        "g": [345678901.0, 7000000123.0],
        "h": [340000000001.0, 7154000125700.25],
    }
    assert all(len(x) == 2 for x in chart.to_dict().values())
    payload = json.loads(chart.to_json())
    assert all(isinstance(n, (int, float)) for col in payload.values() for n in col)
    assert "i" not in payload
    assert json.loads(chart.to_json(legacy_sample=True))["i"] is None


def test_empty_chart():
    assert to_chartdata([]).to_dict() == {k: [] for k in "abcdefgh"}
    assert to_chartdata([]).to_dict(legacy_sample=True) == {
        **{k: [] for k in "abcdefgh"},
        "i": None,
    }


def test_boundary_unknown_activity(daily_raw):
    daily_raw.update(zTotTran=None, qTotTran5J=None, qTotCap=None)
    record = parse_daily(daily_raw, CODE)
    chart = to_chartdata([record])
    assert (
        record.trade_count is None and record.traded_volume is None and record.traded_value is None
    )
    assert chart.f == (0,) and chart.g == (0.0,) and chart.h == (0.0,)


def test_missing_ohlc_not_fabricated(daily_raw):
    daily_raw["pClosing"] = None
    with pytest.raises(ValueError, match="unavailable official close"):
        to_chartdata([parse_daily(daily_raw, CODE)])


def test_adapter_duplicate_policies(daily_raw):
    record = parse_daily(daily_raw, CODE)
    with pytest.raises(ValueError, match="duplicate"):
        to_chartdata([record, record])
    assert len(to_chartdata([record, record], duplicates="identical").a) == 1
    conflict = replace(record, traded_value=Decimal(1))
    with pytest.raises(ValueError, match="duplicate"):
        to_chartdata([record, conflict], duplicates="identical")


def test_mixed_instruments_rejected(daily_raw):
    record = parse_daily(daily_raw, CODE)
    with pytest.raises(ValueError, match="single instrument"):
        to_chartdata([record, replace(record, ins_code="123")])


@pytest.mark.parametrize("count", [2**63, -1])
def test_int64_count_boundary(daily_raw, count):
    daily_raw["zTotTran"] = count
    with pytest.raises(ValueError if count > 0 else Exception):
        to_chartdata([parse_daily(daily_raw, CODE)])


@pytest.mark.parametrize("number", ["1e400", "1e-400"])
def test_float64_out_of_range_rejected(daily_raw, number):
    daily_raw["qTotCap"] = number
    with pytest.raises(ValueError, match="float64"):
        to_chartdata([parse_daily(daily_raw, CODE)])


def test_float64_precision_boundary_is_explicit(daily_raw):
    daily_raw["qTotCap"] = "9007199254740993"
    record = parse_daily(daily_raw, CODE)
    assert record.traded_value == Decimal("9007199254740993")
    assert to_chartdata([record]).h == (9007199254740992.0,)


def test_output_length_validation():
    with pytest.raises(ValueError, match="equal lengths"):
        ChartData((), (1.0,), (), (), (), (), (), ())


def test_output_type_validation():
    with pytest.raises(ValueError, match="int64"):
        ChartData((True,), (1.0,), (1.0,), (1.0,), (1.0,), (1,), (1.0,), (1.0,))
    with pytest.raises(ValueError, match="finite"):
        ChartData((1,), (float("nan"),), (1.0,), (1.0,), (1.0,), (1,), (1.0,), (1.0,))


def test_output_chronology_validation():
    with pytest.raises(ValueError, match="chronological"):
        ChartData((2, 1), *((1.0, 1.0),) * 4, (1, 1), (1.0, 1.0), (1.0, 1.0))
