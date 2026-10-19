"""Company Go ChartData contract. g is volume; h is traded monetary value."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from tsetmc_marketdata.models.daily import DailyRecord
from tsetmc_marketdata.utils.dates import daily_unix_seconds

INT64_MAX = 2**63 - 1


@dataclass(frozen=True)
class ChartData:
    a: tuple[int, ...]
    b: tuple[float, ...]
    c: tuple[float, ...]
    d: tuple[float, ...]
    e: tuple[float, ...]
    f: tuple[int, ...]
    g: tuple[float, ...]
    h: tuple[float, ...]

    def __post_init__(self) -> None:
        columns = (self.a, self.b, self.c, self.d, self.e, self.f, self.g, self.h)
        if len({len(column) for column in columns}) != 1:
            raise ValueError("ChartData arrays must have equal lengths")
        for value in self.a + self.f:
            if type(value) is not int or not -(2**63) <= value <= INT64_MAX:
                raise ValueError("ChartData a and f require int64 values")
        for column in (self.b, self.c, self.d, self.e, self.g, self.h):
            if any(
                type(value) is not float or not math.isfinite(value) or value < 0
                for value in column
            ):
                raise ValueError(
                    "ChartData prices, volume and value require finite nonnegative float64"
                )
        if any(value < 0 for value in self.f):
            raise ValueError("ChartData count must be nonnegative")
        if any(a >= b for a, b in zip(self.a, self.a[1:], strict=False)):
            raise ValueError("ChartData timestamps must be strictly chronological")
        if any(high < low for high, low in zip(self.d, self.e, strict=True)):
            raise ValueError("ChartData high is lower than low")

    def to_dict(self, *, legacy_sample: bool = False) -> dict[str, list[int] | list[float] | None]:
        result: dict[str, list[int] | list[float] | None] = {
            "a": list(self.a),
            "b": list(self.b),
            "c": list(self.c),
            "d": list(self.d),
            "e": list(self.e),
            "f": list(self.f),
            "g": list(self.g),
            "h": list(self.h),
        }
        if legacy_sample:
            result["i"] = None
        return result

    def to_json(self, *, legacy_sample: bool = False) -> str:
        return json.dumps(
            self.to_dict(legacy_sample=legacy_sample), allow_nan=False, separators=(",", ":")
        )


def _float64(value: Decimal | None, field: str, *, placeholder: bool = False) -> float:
    if value is None:
        if placeholder:
            return 0.0
        raise ValueError(f"cannot export candle with unavailable {field}")
    result = float(value)
    if not math.isfinite(result) or (result == 0 and value != 0):
        raise ValueError(f"{field} is outside representable float64 range")
    return result


def to_chartdata(
    records: Sequence[DailyRecord], *, duplicates: Literal["error", "identical"] = "error"
) -> ChartData:
    if duplicates not in {"error", "identical"}:
        raise ValueError("unsupported duplicate policy")
    if len({r.ins_code for r in records}) > 1:
        raise ValueError("ChartData must represent a single instrument")
    ordered: list[DailyRecord] = []
    for record in sorted(records, key=lambda r: r.trading_date):
        if ordered and ordered[-1].trading_date == record.trading_date:
            if duplicates == "identical" and ordered[-1].table_columns() == record.table_columns():
                continue
            raise ValueError(f"duplicate trading date: {record.trading_date}")
        ordered.append(record)
    return ChartData(
        a=tuple(daily_unix_seconds(r.trading_date) for r in ordered),
        b=tuple(_float64(r.opening_price, "opening price") for r in ordered),
        c=tuple(_float64(r.official_close, "official close") for r in ordered),
        d=tuple(_float64(r.high, "high") for r in ordered),
        e=tuple(_float64(r.low, "low") for r in ordered),
        f=tuple(0 if r.trade_count is None else r.trade_count for r in ordered),
        g=tuple(_float64(r.traded_volume, "volume", placeholder=True) for r in ordered),
        h=tuple(_float64(r.traded_value, "value", placeholder=True) for r in ordered),
    )
