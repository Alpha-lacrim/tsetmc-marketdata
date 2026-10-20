"""Exact local tsetmc.v1 encoding/validation. Contains no transport or credentials."""

import hashlib
import json
from datetime import date, datetime, time
from decimal import Decimal
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from tsetmc_marketdata.models.daily import validate_measurements
from tsetmc_marketdata.storage.serialization import canonical_hash

MAX_INT64 = 2**63 - 1
POSITIONS = {
    "source_position",
    "state_version",
    "financial_revision",
    "local_snapshot_id",
    "local_observation_id",
    "local_revision_id",
    "local_decision_id",
    "stored_state_version",
}
UNITS = {
    "profile": "tsetmc_equity_irr_shares_v1",
    "price_currency": "IRR",
    "value_currency": "IRR",
    "volume_unit": "share",
    "confidence": "unverified",
    "evidence_ref": None,
}


def encode(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf8")


def sha(value: Any) -> str:
    return hashlib.sha256(encode(value)).hexdigest()


def record_sha(record: dict[str, Any]) -> str:
    return sha({k: record[k] for k in ("kind", "event_type", "observation")})


def identity(code: str, source_id: str | None) -> dict[str, Any]:
    symbol = "TSETMC:" + code
    return {
        "provider": "tsetmc",
        "ins_code": code,
        "provider_symbol": code,
        "canonical_symbol": symbol,
        "instrument_id": str(uuid5(NAMESPACE_URL, "marketdata:instrument:" + symbol)),
        "source_instrument_id": source_id,
    }


def instant(value: datetime | None) -> str | None:
    if value is None:
        return None
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError("publication instant must be aware UTC")
    return value.isoformat().replace("+00:00", "Z")


@lru_cache
def schema() -> dict[str, Any]:
    resource = files("tsetmc_marketdata").joinpath("data/tsetmc.v1.schema.json")
    body = (
        resource.read_text(encoding="utf8")
        if resource.is_file()
        else (
            Path(__file__).resolve().parents[3] / "docs/contracts/milestone3b/schema.json"
        ).read_text(encoding="utf8")
    )
    result: dict[str, Any] = json.loads(body)
    return result


def financial_hash(o: dict[str, Any], measurements: dict[str, Any] | None = None) -> str:
    m = measurements if measurements is not None else o["measurements"]
    state = {
        "ins_code": o["ins_code"],
        **m,
        "trade_count": int(m["trade_count"]) if m["trade_count"] is not None else None,
    }
    if "trading_date" in o:
        state["trading_date"] = o["trading_date"]
    else:
        state.update(
            instrument_state=o["instrument_state"],
            instrument_state_title=o["instrument_state_title"],
        )
    return canonical_hash(state)


@lru_cache
def validator(definition: str) -> Draft202012Validator:
    document = schema()
    return Draft202012Validator(
        {"$defs": document["$defs"], "$ref": "#/$defs/" + definition},
        format_checker=FormatChecker(),
    )


def validate(value: dict[str, Any], definition: str) -> None:
    try:
        validator(definition).validate(value)
    except ValidationError:
        raise ValueError("publication wire schema is invalid; values withheld") from None

    def walk(item: Any) -> None:
        if isinstance(item, list):
            for child in item:
                walk(child)
        if not isinstance(item, dict):
            return
        for key, child in item.items():
            if child is not None:
                if key in {
                    "received_at",
                    "captured_at",
                    "expires_at",
                    "reviewed_at",
                    "discovered_at",
                    "source_reported_at",
                    "server_ingested_at",
                    "valid_until",
                    "last_successful_http_at",
                    "last_database_commit_at",
                    "accepted_source_at",
                    "last_financial_change_at",
                }:
                    instant(datetime.fromisoformat(child))
                if key in {"trading_date", "source_date", "from_date", "through_date"}:
                    date.fromisoformat(child)
                if key == "source_time":
                    time.fromisoformat(child)
            if key in POSITIONS and child is not None and not 0 < int(child) <= MAX_INT64:
                raise ValueError("publication int64 overflow")
            if key in {"protocol_version", "session_generation", "ownership_generation"}:
                if type(child) is not int:
                    raise ValueError("publication generation/version requires a strict integer")
            walk(child)
        if item.get("provider") == "tsetmc":
            expected = identity(item["ins_code"], item["source_instrument_id"])
            if any(item[k] != v for k, v in expected.items()):
                raise ValueError("publication identity mismatch")
        if "measurements" in item:
            if financial_hash(item) != item["financial_hash"]:
                raise ValueError("publication financial hash mismatch")
            m = item["measurements"]
            validate_measurements(
                {
                    k: Decimal(v) if v is not None else None
                    for k, v in m.items()
                    if k != "trade_count"
                },
                int(m["trade_count"]) if m["trade_count"] is not None else None,
            )
        if "revision_evidence" in item and item["revision_evidence"]:
            r = item["revision_evidence"]
            if int(r["financial_revision"]) < 2 or any(
                financial_hash(item, r[p + "_measurements"]) != r[p + "_financial_hash"]
                for p in ("old", "new")
            ):
                raise ValueError("publication revision evidence mismatch")
            if r["old_financial_hash"] == r["new_financial_hash"]:
                raise ValueError("financial revision must change financial state")
            if "financial_hash" in item and r["new_financial_hash"] != item["financial_hash"]:
                raise ValueError("publication revision does not prove current state")
            if item.get("financial_revision", r["financial_revision"]) != r["financial_revision"]:
                raise ValueError("publication revision number mismatch")
        if "local_finalization" in item and "review" in item:
            review = item["review"]
            if review and review["reviewed_financial_hash"] != item["financial_hash"]:
                raise ValueError("publication review hash mismatch")
            if item["local_finalization"] == "operator_finalized" and (
                not review
                or review["action"] != "confirm"
                or len(set(review["evidence_observation_ids"])) != 2
            ):
                raise ValueError("publication lacks valid local confirmation")
        if item.get("observation_semantics") == "polled_snapshot":
            if (
                item["accepted_decision"] == "explicit_same_time_correction"
                and not item["correction_reason_sha256"]
            ):
                raise ValueError("publication correction evidence missing")
            if item["source_date"] and item["source_time"] and item["source_reported_at"]:
                local = datetime.combine(
                    date.fromisoformat(item["source_date"]),
                    time.fromisoformat(item["source_time"]),
                    ZoneInfo("Asia/Tehran"),
                )
                if local != datetime.fromisoformat(item["source_reported_at"]):
                    raise ValueError("publication source clock mismatch")
        if "expires_at" in item:
            ttl = (
                datetime.fromisoformat(item["expires_at"])
                - datetime.fromisoformat(item["captured_at"])
            ).total_seconds()
            if not 0 < ttl <= 120:
                raise ValueError("publication status TTL invalid")
        if "coverage_rows" in item:
            days = [r["trading_date"] for r in item["coverage_rows"]]
            if len(set(days)) != len(days) or not all(
                item["from_date"] <= d <= item["through_date"] for d in days
            ):
                raise ValueError("publication coverage date mismatch")
        if "records" in item and "session_id" in item:
            seen = set()
            for record in item["records"]:
                if record["observation"]["instrument_id"] != item["instrument_id"]:
                    raise ValueError("publication batch instrument mismatch")
                expected_id = str(
                    uuid5(
                        UUID(item["source_epoch"]), item["stream"] + ":" + record["source_position"]
                    )
                )
                if record["observation_id"] != expected_id or expected_id in seen:
                    raise ValueError("publication observation identity mismatch")
                seen.add(expected_id)
                if (
                    record["kind"] == "current"
                    and record["observation"]["state_version"] != record["source_position"]
                ):
                    raise ValueError("current state version must match its stream position")
                if (
                    record["event_type"] == "daily.corrected"
                    and not record["observation"]["revision_evidence"]
                ):
                    raise ValueError("daily correction requires revision evidence")
                if (
                    record["kind"] == "current"
                    and record["observation"]["accepted_decision"] == "repeated_state"
                ):
                    if (
                        record["event_type"] not in {"current.seed", "current.resnapshot"}
                        or record["observation"]["financial_change"]
                    ):
                        raise ValueError("receipt-only poll cannot publish current update")

    walk(value)


def decode(body: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = dict(items)
        if len(result) != len(items):
            raise ValueError("duplicate publication JSON key")
        return result

    def reject(_: str) -> Any:
        raise ValueError("publication JSON numbers must be integers")

    try:
        value = json.loads(body, object_pairs_hook=pairs, parse_float=reject, parse_constant=reject)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("invalid publication JSON; values withheld") from None
    if not isinstance(value, dict):
        raise ValueError("publication object required")
    return value
