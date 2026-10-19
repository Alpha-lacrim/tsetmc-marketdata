"""Pure source parsers. A malformed row cannot destroy other historical dates."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from tsetmc_marketdata.config import PILOT_INS_CODE, validate_ins_code
from tsetmc_marketdata.errors import ErrorKind, RecordError, SourceDataError
from tsetmc_marketdata.models.current import CurrentPrice
from tsetmc_marketdata.models.daily import DailyRecord
from tsetmc_marketdata.models.instrument import Instrument
from tsetmc_marketdata.utils.dates import parse_source_date, parse_source_time, source_instant

MEASUREMENTS = {
    "traded_volume": "qTotTran5J",
    "traded_value": "qTotCap",
    "previous_close": "priceYesterday",
    "opening_price": "priceFirst",
    "last_traded_price": "pDrCotVal",
    "high": "priceMax",
    "low": "priceMin",
    "official_close": "pClosing",
}
KNOWN_DAILY_FIELDS = {
    *MEASUREMENTS.values(),
    "dEven",
    "hEven",
    "insCode",
    "zTotTran",
    "priceChange",
    "last",
    "id",
    "iClose",
    "yClose",
}


def decimal_field(raw: dict[str, Any], key: str) -> Decimal | None:
    value = raw.get(key)
    if value is None:
        return None
    # Reject binary floats: use loads_source() at the JSON boundary.
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise RecordError(f"{key} must be a source number, numeric string, or null")
    if (
        isinstance(value, str)
        and re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", value) is None
    ):
        raise RecordError(f"{key} is not an unabbreviated number")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise RecordError(f"{key} is not numeric") from exc
    if not number.is_finite() or number < 0:
        raise RecordError(f"{key} must be finite and nonnegative")
    return number


def count_field(raw: dict[str, Any]) -> int | None:
    value = decimal_field(raw, "zTotTran")
    if value is None:
        return None
    if value != value.to_integral_value():
        raise RecordError("zTotTran must be an integer")
    return int(value)


def identity(raw: dict[str, Any], expected: str, *, allow_placeholder: bool) -> None:
    validate_ins_code(expected)
    value = raw.get("insCode")
    # Published current-price examples use '0'; bind those to the requested endpoint.
    if allow_placeholder and value in (None, "0", 0):
        return
    if isinstance(value, bool) or not isinstance(value, (str, int)) or str(value) != expected:
        raise RecordError("source insCode does not match requested instrument")


def envelope(payload: object, key: str) -> Any:
    if not isinstance(payload, dict) or key not in payload:
        raise SourceDataError(ErrorKind.SCHEMA, f"expected {key} envelope")
    return payload[key]


def parse_daily(raw: object, ins_code: str) -> DailyRecord:
    if not isinstance(raw, dict):
        raise RecordError("daily row must be an object")
    identity(raw, ins_code, allow_placeholder=False)
    try:
        trading_date = parse_source_date(raw.get("dEven"))
    except ValueError as exc:
        raise RecordError("invalid Gregorian dEven") from exc
    if not any(key in raw for key in MEASUREMENTS.values()):
        raise RecordError("daily row contains no recognized measurements")
    values = {name: decimal_field(raw, key) for name, key in MEASUREMENTS.items()}
    return DailyRecord(
        ins_code=ins_code,
        trading_date=trading_date,
        trade_count=count_field(raw),
        raw=copy.deepcopy(raw),
        **values,
    )


@dataclass(frozen=True)
class RecordDiagnostic:
    index: int
    code: str
    message: str
    raw: Any
    severity: str = "error"


@dataclass(frozen=True)
class HistoryResult:
    records: tuple[DailyRecord, ...]
    diagnostics: tuple[RecordDiagnostic, ...]
    raw_payload: dict[str, Any]

    @property
    def has_errors(self) -> bool:
        return any(d.severity == "error" for d in self.diagnostics)


def parse_history(payload: object, ins_code: str) -> HistoryResult:
    validate_ins_code(ins_code)
    rows = envelope(payload, "closingPriceDaily")
    if not isinstance(rows, list):
        raise SourceDataError(
            ErrorKind.SCHEMA, "closingPriceDaily must be an array (empty is valid)"
        )
    groups: dict[date, list[tuple[int, DailyRecord]]] = {}
    diagnostics: list[RecordDiagnostic] = []
    for index, raw in enumerate(rows):
        try:
            record = parse_daily(raw, ins_code)
        except (RecordError, ValueError) as exc:
            diagnostics.append(
                RecordDiagnostic(index, "malformed_record", str(exc), copy.deepcopy(raw))
            )
            continue
        groups.setdefault(record.trading_date, []).append((index, record))
        unknown = sorted(set(raw) - KNOWN_DAILY_FIELDS)
        if unknown:
            diagnostics.append(
                RecordDiagnostic(
                    index,
                    "additional_fields",
                    "unrecognized fields preserved: " + ", ".join(unknown),
                    None,
                    "info",
                )
            )
    records: list[DailyRecord] = []
    for day in sorted(groups):
        members = groups[day]
        first = members[0][1]
        if len(members) == 1:
            records.append(first)
        elif all(r.table_columns() == first.table_columns() for _, r in members):
            records.append(first)
            for index, record in members[1:]:
                diagnostics.append(
                    RecordDiagnostic(
                        index,
                        "duplicate_identical",
                        f"duplicate measurements for {day}; kept first",
                        record.raw,
                        "warning",
                    )
                )
        else:
            for index, record in members:
                diagnostics.append(
                    RecordDiagnostic(
                        index,
                        "duplicate_conflict",
                        f"conflicting measurements for {day}; quarantined entire date",
                        record.raw,
                    )
                )
    assert isinstance(payload, dict)
    return HistoryResult(tuple(records), tuple(diagnostics), copy.deepcopy(payload))


def parse_targeted_daily(payload: object, ins_code: str, expected_date: date) -> DailyRecord:
    record = parse_daily(envelope(payload, "closingPriceDaily"), ins_code)
    if record.trading_date != expected_date:
        raise RecordError("targeted daily response date does not match requested date")
    return record


def _optional_text(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is not None and not isinstance(value, str):
        raise RecordError(f"{key} must be a string or null")
    return value


def parse_current(payload: object, ins_code: str, *, received_at: datetime | None) -> CurrentPrice:
    raw = envelope(payload, "closingPriceInfo")
    if raw is None:
        raise SourceDataError(ErrorKind.NOT_FOUND, "current-price instrument response is null")
    if not isinstance(raw, dict) or not any(k in raw for k in MEASUREMENTS.values()):
        raise SourceDataError(ErrorKind.SCHEMA, "closingPriceInfo must contain price measurements")
    identity(raw, ins_code, allow_placeholder=True)
    diagnostics: list[str] = []
    if raw.get("insCode") in (None, "0", 0):
        diagnostics.append("identity bound to requested endpoint; source insCode absent/zero")
    day = None
    clock = None
    reported_at = None
    if raw.get("dEven") not in (None, 0, "0"):
        try:
            day = parse_source_date(raw["dEven"])
        except ValueError as exc:
            raise RecordError("invalid current dEven") from exc
    if raw.get("hEven") not in (None, 0, "0"):
        try:
            clock = parse_source_time(raw["hEven"])
        except ValueError as exc:
            raise RecordError("invalid current hEven") from exc
    if day is not None and clock is not None:
        try:
            reported_at = source_instant(day, clock)
        except ValueError:
            diagnostics.append("ambiguous/nonexistent source clock; source instant unavailable")
    state = raw.get("instrumentState")
    if state is None:
        state = {}
    if not isinstance(state, dict):
        raise RecordError("instrumentState must be an object or null")
    identity(state, ins_code, allow_placeholder=True)
    values = {name: decimal_field(raw, key) for name, key in MEASUREMENTS.items()}
    count = count_field(raw)
    return CurrentPrice(
        ins_code=ins_code,
        trade_count=count,
        **values,
        instrument_state=_optional_text(state, "cEtaval"),
        instrument_state_title=_optional_text(state, "cEtavalTitle"),
        source_date=day,
        source_time=clock,
        source_reported_at=reported_at,
        received_at=received_at,
        raw=copy.deepcopy(raw),
        diagnostics=tuple(diagnostics),
    )


def _persian_name(value: str) -> str:
    translated = value.translate(str.maketrans("يك\u200c", "یک "))
    return " ".join(translated.split())


def parse_instrument(payload: object, ins_code: str) -> Instrument:
    raw = envelope(payload, "instrumentInfo")
    if raw is None:
        raise SourceDataError(ErrorKind.NOT_FOUND, "instrument metadata is null")
    if not isinstance(raw, dict):
        raise SourceDataError(ErrorKind.SCHEMA, "instrumentInfo must be an object")
    identity(raw, ins_code, allow_placeholder=False)
    symbol = _optional_text(raw, "lVal18AFC")
    company = _optional_text(raw, "lVal30")
    if not symbol or not company:
        raise RecordError("instrument symbol and company name are required")
    if ins_code == PILOT_INS_CODE:
        if (
            _persian_name(symbol) != "فولاد"
            or _persian_name(company).replace(" ", "") != "فولادمبارکهاصفهان"
        ):
            raise RecordError("pilot metadata does not resolve to فولاد مبارکه اصفهان")
    return Instrument(
        ins_code,
        symbol,
        company,
        _optional_text(raw, "instrumentID"),
        _optional_text(raw, "cIsin"),
        copy.deepcopy(raw),
    )
