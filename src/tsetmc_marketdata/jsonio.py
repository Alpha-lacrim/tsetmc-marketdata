"""Lossless source decoding; Decimal is never constructed through binary float."""

from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any


def _constant(value: str) -> None:
    raise ValueError(f"nonfinite JSON number: {value}")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def loads_source(body: bytes | str) -> Any:
    return json.loads(body, parse_float=Decimal, parse_constant=_constant, object_pairs_hook=_pairs)


def diagnostic_default(value: object) -> str:
    """Exact decimals as strings in diagnostic/model JSON, never in ChartData."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    raise TypeError(f"cannot encode {type(value).__name__}")
