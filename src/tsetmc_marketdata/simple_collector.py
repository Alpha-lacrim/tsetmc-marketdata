"""Native TSETMC collector -> company HTTP API. No source PostgreSQL installation."""

import argparse
import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from tsetmc_marketdata.config import PILOT_INS_CODE, Settings
from tsetmc_marketdata.errors import ErrorKind, SourceDataError, TSETMCError
from tsetmc_marketdata.providers.closing_prices import fetch_current, fetch_history
from tsetmc_marketdata.providers.http_client import TSETMCClient
from tsetmc_marketdata.providers.instruments import fetch_instrument
from tsetmc_marketdata.simple_delivery import PendingUpload, single_instance
from tsetmc_marketdata.utils.dates import daily_unix_seconds


async def collect_history(client: TSETMCClient) -> list[dict[str, Any]]:
    history, response = await fetch_history(client, PILOT_INS_CODE)
    if history.has_errors:
        raise SourceDataError(
            ErrorKind.INVALID_RECORD,
            "source history contains malformed/conflicting rows; upload stopped",
        )
    return [
        dict(
            market="tsetmc",
            symbol=r.ins_code,
            interval="1d",
            time=daily_unix_seconds(r.trading_date),
            received_at=response.received_at,
            open=r.opening_price,
            close=r.official_close,
            high=r.high,
            low=r.low,
            last=r.last_traded_price,
            official_close=r.official_close,
            count=r.trade_count,
            volume=r.traded_volume,
            value=r.traded_value,
            status="unknown",
            metadata={
                "raw": r.raw,
                "finality": "unverified",
                "timestamp_semantics": "Gregorian trading date labeled at UTC midnight",
            },
        )
        for r in history.records
    ]


async def collect_current(client: TSETMCClient) -> list[dict[str, Any]]:
    current, response = await fetch_current(client, PILOT_INS_CODE)
    if current.last_traded_price is None and current.official_close is None:
        return []
    return [
        dict(
            market="tsetmc",
            symbol=current.ins_code,
            interval="quote",
            time=0,
            received_at=response.received_at,
            event_at=current.source_reported_at,
            last=current.last_traded_price,
            official_close=current.official_close,
            count=current.trade_count,
            volume=current.traded_volume,
            value=current.traded_value,
            status="unknown",
            metadata={
                "raw": current.raw,
                "diagnostics": current.diagnostics,
                "source_date": str(current.source_date) if current.source_date else None,
                "source_time": str(current.source_time) if current.source_time else None,
            },
        )
    ]


async def run(args: argparse.Namespace) -> None:
    headers = (
        {"Authorization": "Bearer " + os.environ["SIMPLE_UPLOAD_TOKEN"]}
        if os.getenv("SIMPLE_UPLOAD_TOKEN")
        else {}
    )
    async with (
        TSETMCClient(Settings.from_env()) as source,
        httpx.AsyncClient(timeout=30, headers=headers, trust_env=False) as http,
    ):
        # Identity qualification is shared with the existing collector.
        instrument, _ = await fetch_instrument(source, PILOT_INS_CODE)
        print(f"Collecting {instrument.symbol} ({PILOT_INS_CODE})", flush=True)

        async def loop(kind: str, seconds: float) -> None:
            pending = PendingUpload(args.api_url, args.state_dir / (kind + ".json"), http)
            while True:
                await pending.drain()
                try:
                    rows = await (
                        collect_history(source) if kind == "history" else collect_current(source)
                    )
                    for offset in range(0, len(rows), 500):
                        pending.stage(rows[offset : offset + 500])
                        await pending.drain()
                    print(
                        f"{kind}: delivered {len(rows)} records at {datetime.now(UTC).isoformat()}",
                        flush=True,
                    )
                except TSETMCError as error:
                    if args.once:
                        raise
                    print(
                        f"{kind}: provider failure ({type(error).__name__}); retrying", flush=True
                    )
                if args.once:
                    return
                await asyncio.sleep(seconds)

        async with asyncio.TaskGroup() as group:
            group.create_task(loop("history", args.history_seconds))
            group.create_task(loop("latest", args.poll_seconds))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("COMPANY_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--state-dir", type=Path, default=Path(".local/simple-tsetmc"))
    parser.add_argument("--poll-seconds", type=float, default=15)
    parser.add_argument("--history-seconds", type=float, default=3600)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not 5 <= args.poll_seconds <= 86400 or not 60 <= args.history_seconds <= 86400:
        parser.error("poll-seconds must be 5..86400; history-seconds must be 60..86400")
    with single_instance(args.state_dir):
        try:
            asyncio.run(run(args))
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
