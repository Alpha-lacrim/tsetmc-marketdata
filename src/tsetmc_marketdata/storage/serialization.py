"""Canonical hashes exclude transport clocks, float conversion and JSON key ordering."""

import hashlib
import json
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from tsetmc_marketdata.models.current import CurrentPrice
from tsetmc_marketdata.models.daily import DailyRecord
from tsetmc_marketdata.storage.schema_v1 import MEASUREMENTS


def decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return decimal_text(value)
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_safe(item) for item in value]
    return value


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        json_safe(value), sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def financial_state(record: DailyRecord | CurrentPrice) -> dict[str, Any]:
    result = {name: json_safe(getattr(record, name)) for name in MEASUREMENTS}
    result["ins_code"] = record.ins_code
    if isinstance(record, DailyRecord):
        result["trading_date"] = record.trading_date.isoformat()
    else:
        result.update(
            instrument_state=record.instrument_state,
            instrument_state_title=record.instrument_state_title,
        )
    return result


def numeric_values(record: DailyRecord | CurrentPrice) -> dict[str, Decimal | None]:
    result = {}
    for name in MEASUREMENTS:
        value = getattr(record, name)
        number = Decimal(value) if value is not None else None
        if number is not None and (
            number.adjusted() >= 131072 or int(number.as_tuple().exponent) < -16383
        ):
            raise ValueError("source number exceeds PostgreSQL NUMERIC limits")
        result[name] = number
    return result


def daily_from_row(row: Any) -> DailyRecord:
    values = {name: row[name] for name in MEASUREMENTS}
    values["trade_count"] = int(row["trade_count"]) if row["trade_count"] is not None else None
    return DailyRecord(
        ins_code=row["ins_code"], trading_date=row["trading_date"], raw=row["raw_row"], **values
    )
