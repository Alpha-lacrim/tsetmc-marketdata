"""Extensible instrument configuration; live activation policy belongs at the CLI boundary."""

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from tsetmc_marketdata.config import validate_ins_code


@dataclass(frozen=True)
class InstrumentConfig:
    ins_code: str
    enabled: bool
    instrument_id: str | None = None


def load_instruments(path: Path | None = None) -> dict[str, InstrumentConfig]:
    if path is not None:
        text = path.read_text(encoding="utf8")
    else:
        bundled = files("tsetmc_marketdata").joinpath("data/instruments.json")
        text = (
            bundled.read_text(encoding="utf8")
            if bundled.is_file()
            else (
                Path(__file__).resolve().parents[3] / "config/instruments.example.json"
            ).read_text(encoding="utf8")
        )
    payload = json.loads(text)
    if not isinstance(payload, dict) or not isinstance(payload.get("instruments"), list):
        raise ValueError("instrument config requires an instruments array")
    result: dict[str, InstrumentConfig] = {}
    for row in payload["instruments"]:
        if not isinstance(row, dict) or not isinstance(row.get("enabled"), bool):
            raise ValueError("instrument config requires explicit enabled booleans")
        if not isinstance(row.get("ins_code"), str):
            raise ValueError("ins_code must be a string")
        code = validate_ins_code(row["ins_code"])
        identifier = row.get("instrument_id")
        if identifier is not None and (not isinstance(identifier, str) or not identifier.strip()):
            raise ValueError("instrument_id must be a nonempty string when configured")
        if code in result:
            raise ValueError("duplicate instrument configuration")
        result[code] = InstrumentConfig(code, row["enabled"], identifier)
    return result
