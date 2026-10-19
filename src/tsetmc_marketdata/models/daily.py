"""Daily source records. Prices are exactly as supplied; no adjustment is applied."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import Any

from tsetmc_marketdata.config import validate_ins_code
from tsetmc_marketdata.errors import RecordError


@dataclass(frozen=True)
class PriceChange:
    absolute: Decimal | None
    percent: Decimal | None


def validate_measurements(values: dict[str, Decimal | None], trade_count: int | None) -> None:
    if trade_count is not None and (type(trade_count) is not int or trade_count < 0):
        raise RecordError("zTotTran must be a nonnegative integer or null")
    for name, value in values.items():
        if value is not None and (
            not isinstance(value, Decimal) or not value.is_finite() or value < 0
        ):
            raise RecordError(f"{name} must be a finite nonnegative Decimal or null")
    high, low = values["high"], values["low"]
    if high is not None and low is not None:
        if high < low:
            raise RecordError("priceMax is lower than priceMin")
        if low > 0 and trade_count != 0 and values["traded_volume"] != 0:
            for name in ("opening_price", "last_traded_price"):
                value = values[name]
                if value is not None and not low <= value <= high:
                    raise RecordError(f"{name} is outside the executed trading range")
    # The official close is not constrained to the executed-trade range.


def price_change(price: Decimal | None, previous: Decimal | None) -> PriceChange:
    if price is None or previous is None:
        return PriceChange(None, None)
    # Enough precision for exact subtraction even for unusually large fractional prices.
    precision = max(
        50,
        max(price.adjusted(), previous.adjusted(), 0)
        - min(int(price.as_tuple().exponent), int(previous.as_tuple().exponent), 0)
        + 10,
    )
    with localcontext() as context:
        context.prec = precision
        absolute = price - previous
        percent = None if previous == 0 else absolute / previous * 100
    return PriceChange(absolute, percent)


@dataclass(frozen=True, kw_only=True)
class DailyRecord:
    ins_code: str
    trading_date: date
    trade_count: int | None
    traded_volume: Decimal | None
    traded_value: Decimal | None
    previous_close: Decimal | None
    opening_price: Decimal | None
    last_traded_price: Decimal | None
    high: Decimal | None
    low: Decimal | None
    official_close: Decimal | None
    raw: dict[str, Any]

    def __post_init__(self) -> None:
        validate_ins_code(self.ins_code)
        if not isinstance(self.trading_date, date) or isinstance(self.trading_date, datetime):
            raise RecordError("trading_date must be a Gregorian date")
        validate_measurements(
            {
                name: getattr(self, name)
                for name in (
                    "traded_volume",
                    "traded_value",
                    "previous_close",
                    "opening_price",
                    "last_traded_price",
                    "high",
                    "low",
                    "official_close",
                )
            },
            self.trade_count,
        )

    @property
    def last_trade_change(self) -> PriceChange:
        return price_change(self.last_traded_price, self.previous_close)

    @property
    def closing_change(self) -> PriceChange:
        return price_change(self.official_close, self.previous_close)

    def table_columns(self) -> dict[str, date | int | Decimal | None]:
        """All 14 historical columns without abbreviations or fabricated values."""
        return {
            "trading_date": self.trading_date,
            "trade_count": self.trade_count,
            "traded_volume": self.traded_volume,
            "traded_value": self.traded_value,
            "previous_close": self.previous_close,
            "opening_price": self.opening_price,
            "last_traded_price": self.last_traded_price,
            "last_trade_absolute_change": self.last_trade_change.absolute,
            "last_trade_percent_change": self.last_trade_change.percent,
            "high": self.high,
            "low": self.low,
            "official_close": self.official_close,
            "closing_absolute_change": self.closing_change.absolute,
            "closing_percent_change": self.closing_change.percent,
        }
