"""Only metadata needed to qualify the pilot; full source metadata is retained."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Instrument:
    ins_code: str
    symbol: str
    company_name: str
    instrument_id: str | None
    isin: str | None
    raw: dict[str, Any]
