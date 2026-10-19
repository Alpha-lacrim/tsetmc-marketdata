"""Explicit, bounded source qualification; not a collector. Run after uv sync.

Uses the project client. Exact response bodies and sanitized diagnostics are saved.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from tsetmc_marketdata.config import PILOT_INS_CODE, Settings
from tsetmc_marketdata.errors import TSETMCError
from tsetmc_marketdata.parsing import parse_history
from tsetmc_marketdata.providers.http_client import TSETMCClient
from tsetmc_marketdata.utils.dates import parse_source_date


async def qualify(output: Path, fallback_date: str | None = None) -> None:
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=True)
    paths = {
        "instrument": f"Instrument/GetInstrumentInfo/{PILOT_INS_CODE}",
        "history-0": f"ClosingPrice/GetClosingPriceDailyList/{PILOT_INS_CODE}/0",
        "history-1": f"ClosingPrice/GetClosingPriceDailyList/{PILOT_INS_CODE}/1",
        "history-2": f"ClosingPrice/GetClosingPriceDailyList/{PILOT_INS_CODE}/2",
        "current": f"ClosingPrice/GetClosingPriceInfo/{PILOT_INS_CODE}",
    }
    results: list[dict[str, object]] = []
    async with TSETMCClient(Settings(max_retries=0, read_timeout=12)) as client:
        for name, path in list(paths.items()):
            try:
                response = await client.get_json(path)
                body_path = output / f"{name}.json"
                body_path.write_bytes(response.raw_body)
                result: dict[str, object] = {
                    "name": name,
                    "path": path,
                    "status": response.status_code,
                    "received_at": response.received_at.isoformat(),
                    "sha256": hashlib.sha256(response.raw_body).hexdigest(),
                    "bytes": len(response.raw_body),
                    "keys": list(response.payload),
                }
                if name.startswith("history"):
                    rows = response.payload.get("closingPriceDaily")
                    if isinstance(rows, list):
                        result["record_count"] = len(rows)
                        parsed = parse_history(response.payload, PILOT_INS_CODE)
                        dates = [r.trading_date for r in parsed.records]
                        result["validation_errors"] = sum(
                            d.severity == "error" for d in parsed.diagnostics
                        )
                        result["dates"] = (
                            [d.isoformat() for d in dates]
                            if len(dates) < 4
                            else [min(dates).isoformat(), max(dates).isoformat()]
                        )
                        if name == "history-0" and dates:
                            paths["daily"] = (
                                f"ClosingPrice/GetClosingPriceDaily/{PILOT_INS_CODE}/{max(dates):%Y%m%d}"
                            )
            except TSETMCError as exc:
                result = {
                    "name": name,
                    "path": path,
                    "reported_at": datetime.now(UTC).isoformat(),
                    **exc.as_dict(),
                }
            results.append(result)
            print(json.dumps(result, ensure_ascii=True), flush=True)
        # A supplied date probes the route even when history is inaccessible.
        if "daily" not in paths and fallback_date is not None:
            day = parse_source_date(fallback_date)
            paths["daily"] = f"ClosingPrice/GetClosingPriceDaily/{PILOT_INS_CODE}/{day:%Y%m%d}"
        if "daily" in paths:
            path = paths["daily"]
            try:
                response = await client.get_json(path)
                (output / "daily.json").write_bytes(response.raw_body)
                results.append(
                    {
                        "name": "daily",
                        "path": path,
                        "status": response.status_code,
                        "received_at": response.received_at.isoformat(),
                        "sha256": hashlib.sha256(response.raw_body).hexdigest(),
                        "keys": list(response.payload),
                    }
                )
            except TSETMCError as exc:
                results.append(
                    {
                        "name": "daily",
                        "path": path,
                        "reported_at": datetime.now(UTC).isoformat(),
                        **exc.as_dict(),
                    }
                )
    (output / "manifest.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--date", help="YYYYMMDD fallback targeted date; not a claim a session exists"
    )
    args = parser.parse_args()
    if args.date is not None:
        parse_source_date(args.date)
    asyncio.run(qualify(args.output, args.date))
