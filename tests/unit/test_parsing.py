from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext

import pytest

from tsetmc_marketdata.config import PILOT_INS_CODE as CODE
from tsetmc_marketdata.errors import ErrorKind, RecordError, SourceDataError
from tsetmc_marketdata.jsonio import loads_source
from tsetmc_marketdata.parsing import (
    parse_current,
    parse_daily,
    parse_history,
    parse_instrument,
    parse_targeted_daily,
)


def test_all_14_columns(daily_raw):
    r = parse_daily(daily_raw, CODE)
    assert r.table_columns() == {
        "trading_date": date(2026, 3, 21),
        "trade_count": 1234,
        "traded_volume": Decimal("7000000123"),
        "traded_value": Decimal("7154000125700.25"),
        "previous_close": Decimal("1000"),
        "opening_price": Decimal("1010.25"),
        "last_traded_price": Decimal("1030.50"),
        "last_trade_absolute_change": Decimal("30.50"),
        "last_trade_percent_change": Decimal("3.05"),
        "high": Decimal("1040.75"),
        "low": Decimal("1005"),
        "official_close": Decimal("1020.25"),
        "closing_absolute_change": Decimal("20.25"),
        "closing_percent_change": Decimal("2.025"),
    }
    assert r.raw["last"] is True
    assert r.last_traded_price != r.official_close


def test_missing_optional_measurements(daily_raw):
    for key in ("priceYesterday", "zTotTran", "qTotTran5J", "qTotCap", "priceFirst"):
        daily_raw.pop(key)
    r = parse_daily(daily_raw, CODE)
    assert r.trade_count is None and r.traded_volume is None and r.traded_value is None
    assert r.opening_price is None
    assert r.last_trade_change.absolute is None and r.closing_change.percent is None


@pytest.mark.parametrize(
    "key,value",
    [
        ("dEven", 20260230),
        ("dEven", "1405/01/01"),
        ("dEven", None),
        ("dEven", True),
        ("insCode", "1"),
        ("insCode", None),
        ("insCode", 46348559193224090.0),
        ("zTotTran", -1),
        ("zTotTran", "1.1"),
        ("qTotTran5J", -1),
        ("qTotCap", "7.01 B"),
        ("pClosing", "NaN"),
        ("pClosing", True),
        ("pClosing", 1020.25),
        ("priceMax", 900),
        ("priceFirst", 2000),
        ("pDrCotVal", 900),
    ],
)
def test_invalid_record_fields(daily_raw, key, value):
    daily_raw[key] = value
    with pytest.raises(RecordError):
        parse_daily(daily_raw, CODE)


@pytest.mark.parametrize(
    "payload", [{}, [], {"closingPriceDaily": None}, {"closingPriceDaily": {}}]
)
def test_unexpected_envelope(payload):
    with pytest.raises(SourceDataError) as error:
        parse_history(payload, CODE)
    assert error.value.kind == ErrorKind.SCHEMA


def test_partial_history_quarantine(history_payload):
    history_payload["closingPriceDaily"].extend([{"dEven": 20260230}, "bad row"])
    result = parse_history(history_payload, CODE)
    assert [r.trading_date for r in result.records] == [date(2025, 12, 31), date(2026, 3, 21)]
    assert result.has_errors
    assert len(result.diagnostics) == 2
    assert result.diagnostics[0].raw == {"dEven": 20260230}


def test_identical_duplicate(history_payload):
    history_payload["closingPriceDaily"].append(deepcopy(history_payload["closingPriceDaily"][0]))
    result = parse_history(history_payload, CODE)
    assert len(result.records) == 2 and not result.has_errors
    assert result.diagnostics[0].code == "duplicate_identical"


def test_conflicting_duplicates_quarantine_entire_day(history_payload):
    other = deepcopy(history_payload["closingPriceDaily"][0])
    other["qTotCap"] += 1
    history_payload["closingPriceDaily"].append(other)
    result = parse_history(history_payload, CODE)
    assert len(result.records) == 1 and result.has_errors
    assert len([d for d in result.diagnostics if d.code == "duplicate_conflict"]) == 2


def test_precise_large_values(daily_raw):
    huge = "1234567890123456789012345678901234567890.12345678901234567890"
    daily_raw.update(
        qTotTran5J=huge,
        qTotCap=huge,
        zTotTran="9007199254740993",
        pClosing=huge,
        priceYesterday="1",
    )
    with localcontext() as context:
        context.prec = 6  # source precision and subtraction must survive caller context
        r = parse_daily(daily_raw, CODE)
        assert str(r.official_close) == huge
        assert r.traded_volume == Decimal(huge) and r.traded_value == Decimal(huge)
        assert r.trade_count == 9007199254740993
        assert (
            str(r.closing_change.absolute)
            == "1234567890123456789012345678901234567889.12345678901234567890"
        )


def test_zero_previous_close(daily_raw):
    daily_raw["priceYesterday"] = 0
    r = parse_daily(daily_raw, CODE)
    assert r.last_trade_change.absolute == Decimal("1030.50")
    assert r.last_trade_change.percent is None and r.closing_change.percent is None


def test_official_close_may_be_outside_trade_range(daily_raw):
    daily_raw["pClosing"] = 990
    assert parse_daily(daily_raw, CODE).official_close == Decimal(990)


def test_zero_activity_preserved(daily_raw):
    daily_raw.update(
        zTotTran=0, qTotTran5J=0, qTotCap=0, priceMin=0, priceMax=0, priceFirst=0, pDrCotVal=0
    )
    r = parse_daily(daily_raw, CODE)
    assert r.trade_count == 0 and r.traded_volume == 0


def test_schema_additions_preserved(history_payload):
    history_payload["closingPriceDaily"][0]["futureField"] = {"extra": 12}
    r = parse_history(history_payload, CODE)
    assert not r.has_errors
    assert r.records[-1].raw["futureField"] == {"extra": 12}
    assert r.diagnostics[0].code == "additional_fields"
    history_payload["closingPriceDaily"][0]["futureField"]["extra"] = 0
    assert r.records[-1].raw["futureField"]["extra"] == 12


def test_renamed_prices_not_invented(daily_raw):
    daily_raw["newClosing"] = daily_raw.pop("pClosing")
    assert parse_daily(daily_raw, CODE).official_close is None


def test_empty_history():
    result = parse_history({"closingPriceDaily": []}, CODE)
    assert result.records == () and not result.has_errors


def test_targeted_reconciliation(daily_raw):
    payload = {"closingPriceDaily": daily_raw}
    assert parse_targeted_daily(payload, CODE, date(2026, 3, 21)).trade_count == 1234
    with pytest.raises(RecordError):
        parse_targeted_daily(payload, CODE, date(2026, 3, 20))


def test_current_price(current_payload):
    receipt = datetime(2026, 3, 21, 9, 1, tzinfo=UTC)
    r = parse_current(current_payload, CODE, received_at=receipt)
    assert r.last_traded_price == Decimal("1030.50")
    assert r.official_close == Decimal("1020.25") and r.previous_close == Decimal(1000)
    assert r.source_reported_at == datetime(2026, 3, 21, 9, 0, 45, tzinfo=UTC)
    assert r.received_at == receipt
    assert r.instrument_state == "A " and r.instrument_state_title == "مجاز"
    assert r.trade_count == 1234 and r.traded_volume == Decimal(7000000123)
    assert r.traded_value == Decimal("7154000125700.25")
    assert r.raw["last"] is True and r.diagnostics
    assert r.last_trade_change.percent == Decimal("3.05")


def test_repeated_http_observation_does_not_change_source_time(current_payload):
    a = parse_current(current_payload, CODE, received_at=datetime(2026, 3, 21, 9, 1, tzinfo=UTC))
    b = parse_current(current_payload, CODE, received_at=datetime(2026, 3, 21, 9, 2, tzinfo=UTC))
    assert a.source_reported_at == b.source_reported_at and a.received_at != b.received_at


def test_missing_current_last_never_uses_previous(current_payload):
    current_payload["closingPriceInfo"].pop("pDrCotVal")
    r = parse_current(current_payload, CODE, received_at=None)
    assert r.last_traded_price is None and r.previous_close == Decimal(1000)
    assert r.received_at is None


def test_current_identity_mismatch(current_payload):
    current_payload["closingPriceInfo"]["insCode"] = "99"
    with pytest.raises(RecordError):
        parse_current(current_payload, CODE, received_at=None)


def test_current_zero_clock_is_unknown(current_payload):
    current_payload["closingPriceInfo"].update(dEven=0, hEven=0)
    r = parse_current(current_payload, CODE, received_at=None)
    assert r.source_date is None and r.source_time is None and r.source_reported_at is None


def test_current_rejects_naive_receipt(current_payload):
    with pytest.raises(RecordError):
        parse_current(current_payload, CODE, received_at=datetime(2026, 1, 1))


def test_instrument_identity(instrument_payload):
    r = parse_instrument(instrument_payload, CODE)
    assert r.ins_code == CODE and r.symbol == "فولاد"
    instrument_payload["instrumentInfo"]["lVal30"] = "فولاد مباركه اصفهان"
    assert parse_instrument(instrument_payload, CODE).company_name
    instrument_payload["instrumentInfo"]["lVal18AFC"] = "OTHER"
    with pytest.raises(RecordError):
        parse_instrument(instrument_payload, CODE)


@pytest.mark.parametrize(
    "parser,key", [(parse_instrument, "instrumentInfo"), (parse_current, "closingPriceInfo")]
)
def test_not_found(parser, key):
    kwargs = {"received_at": None} if parser is parse_current else {}
    with pytest.raises(SourceDataError) as error:
        parser({key: None}, CODE, **kwargs)
    assert error.value.kind == ErrorKind.NOT_FOUND


@pytest.mark.parametrize("body", ['{"x":NaN}', '{"x":1,"x":2}', "bad"])
def test_lossless_decoder_rejects_invalid_json(body):
    with pytest.raises(ValueError):
        loads_source(body)


def test_lossless_json_numeric_values():
    p = loads_source('{"price":0.10000000000000000001,"n":9007199254740993}')
    assert p["price"] == Decimal("0.10000000000000000001") and p["n"] == 9007199254740993
