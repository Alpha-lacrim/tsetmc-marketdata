"""An HTTP observation is not a completed candle or evidence of a new trade."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from tsetmc_marketdata.config import validate_ins_code
from tsetmc_marketdata.errors import RecordError
from tsetmc_marketdata.models.daily import PriceChange, price_change, validate_measurements


@dataclass(frozen=True, kw_only=True)
class CurrentPrice:
    ins_code: str
    last_traded_price: Decimal | None
    official_close: Decimal | None
    previous_close: Decimal | None
    opening_price: Decimal | None
    high: Decimal | None
    low: Decimal | None
    trade_count: int | None
    traded_volume: Decimal | None
    traded_value: Decimal | None
    instrument_state: str | None
    instrument_state_title: str | None
    source_date: date | None
    source_time: time | None
    source_reported_at: datetime | None
    received_at: datetime | None
    raw: dict[str, Any]
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_ins_code(self.ins_code)
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
        for name in ("received_at", "source_reported_at"):
            value = getattr(self, name)
            if value is not None and (
                value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
            ):
                raise RecordError(f"{name} must be timezone-aware UTC")

    @property
    def last_trade_change(self) -> PriceChange:
        return price_change(self.last_traded_price, self.previous_close)

    @property
    def closing_change(self) -> PriceChange:
        return price_change(self.official_close, self.previous_close)
