"""Bounded source decorator, with optional private exact-response qualification evidence."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tsetmc_marketdata.collection.source import Source
from tsetmc_marketdata.errors import TSETMCError
from tsetmc_marketdata.parsing import parse_current
from tsetmc_marketdata.providers.http_client import JSONResponse
from tsetmc_marketdata.storage.config import StorageError
from tsetmc_marketdata.storage.serialization import canonical_hash, financial_state, json_safe


class RequestBudgetError(StorageError):
    category = "request_budget_exhausted"


class BudgetSource:
    def __init__(self, source: Source, ins_code: str, limit: int, directory: Path | None = None):
        self.source, self.ins_code, self.limit = source, ins_code, limit
        self.requests = 0
        self.directory = directory
        if directory is not None and directory.exists() and any(directory.iterdir()):
            raise ValueError("qualification evidence directory must be new or empty")
        self.events: list[dict[str, Any]] = []

    async def record(self, event: dict[str, Any], body: bytes | None = None) -> None:
        self.events.append(event)
        if self.directory is None:
            return

        def write() -> None:
            assert self.directory is not None
            self.directory.mkdir(parents=True, exist_ok=True)
            if body is not None:
                with (self.directory / f"response-{self.requests:04d}.json").open("xb") as output:
                    output.write(body)
            with (self.directory / "events.jsonl").open("a", encoding="utf8") as output:
                output.write(json.dumps(json_safe(event), sort_keys=True) + "\n")

        await asyncio.to_thread(write)

    async def get_json(self, path: str) -> JSONResponse:
        allowed = (
            f"Instrument/GetInstrumentInfo/{self.ins_code}",
            f"ClosingPrice/GetClosingPriceInfo/{self.ins_code}",
        )
        if path not in allowed and not any(
            path.startswith(prefix)
            for prefix in (
                f"ClosingPrice/GetClosingPriceDailyList/{self.ins_code}/",
                f"ClosingPrice/GetClosingPriceDaily/{self.ins_code}/",
            )
        ):
            raise ValueError("source path is outside the configured instrument scope")
        if self.requests >= self.limit:
            raise RequestBudgetError("logical request budget exhausted")
        self.requests += 1
        start = datetime.now(UTC)
        try:
            response = await self.source.get_json(path)
        except TSETMCError as exc:
            await self.record(
                {
                    "kind": "http_failure",
                    "path": path,
                    "requested_at": start,
                    "finished_at": datetime.now(UTC),
                    **exc.as_dict(),
                }
            )
            raise
        event: dict[str, Any] = {
            "kind": "http_response",
            "path": path,
            "requested_at": response.attempted_at or start,
            "received_at": response.received_at,
            "status": response.status_code,
            "latency_seconds": (datetime.now(UTC) - start).total_seconds(),
            "response_file": f"response-{self.requests:04d}.json",
        }
        if "GetClosingPriceInfo/" in path:
            try:
                record = parse_current(
                    response.payload, self.ins_code, received_at=response.received_at
                )
            except TSETMCError as exc:
                event["source_parse_error"] = exc.as_dict()
            else:
                event.update(
                    financial_state=financial_state(record),
                    financial_hash=canonical_hash(financial_state(record)),
                    source_date=record.source_date,
                    source_time=record.source_time,
                    source_reported_at=record.source_reported_at,
                    original_clocks={
                        k: record.raw.get(k)
                        for k in ("dEven", "hEven", "lastHEven", "finalLastDate")
                    },
                    source_to_receipt_seconds=(
                        response.received_at - record.source_reported_at
                    ).total_seconds()
                    if record.source_reported_at
                    else None,
                )
        await self.record(event, response.raw_body)
        return response
