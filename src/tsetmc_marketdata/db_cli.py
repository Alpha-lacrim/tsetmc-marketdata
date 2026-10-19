"""Milestone 2 CLI extension; original Milestone 1 commands remain independent."""

import argparse
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from tsetmc_marketdata.adapters.chartdata import to_chartdata
from tsetmc_marketdata.collection.instruments import load_instruments
from tsetmc_marketdata.collection.jobs import Collector
from tsetmc_marketdata.collection.scheduler import PollPolicy, poll
from tsetmc_marketdata.collection.source import CaptureReplay, Source
from tsetmc_marketdata.config import PILOT_INS_CODE, Settings, require_pilot, validate_ins_code
from tsetmc_marketdata.providers.http_client import TSETMCClient
from tsetmc_marketdata.storage.config import DatabaseSettings
from tsetmc_marketdata.storage.database import Database, verify_schema
from tsetmc_marketdata.storage.queries import collection_report, pending_dates, read_daily, retain
from tsetmc_marketdata.storage.repository import Repository
from tsetmc_marketdata.utils.dates import parse_source_date

COMMANDS = {
    "db-status",
    "collection-status",
    "backfill-history",
    "refresh-history",
    "audit-history",
    "reconcile-history",
    "observe-current",
    "export-db-chartdata",
    "poll-current",
    "retention",
}


def configure(subparsers: Any) -> None:
    for name in sorted(COMMANDS):
        command = subparsers.add_parser(name)
        command.add_argument("--ins-code", default=PILOT_INS_CODE)
        command.add_argument("--report", type=Path)
        if name in {"db-status", "collection-status"}:
            continue
        if name == "export-db-chartdata":
            command.add_argument("--output", type=Path, required=True)
            command.add_argument(
                "--selection", choices=("finalized", "accepted-unverified"), default="finalized"
            )
            command.add_argument("--legacy-sample", action="store_true")
            continue
        if name == "retention":
            command.add_argument(
                "--apply", action="store_true", help="default is a read-only dry run"
            )
            continue
        command.add_argument(
            "--capture-dir", type=Path, help="private manifest-backed offline replay"
        )
        command.add_argument(
            "--run-id", type=UUID, help="idempotent run replay after lost acknowledgment"
        )
        command.add_argument("--dry-run", action="store_true")
        command.add_argument(
            "--instrument-config", type=Path, help="extensible instrument configuration JSON"
        )
        if name == "refresh-history":
            command.add_argument("--source-limit", type=int, default=20)
        if name == "reconcile-history":
            command.add_argument(
                "--date", help="single Gregorian YYYYMMDD; otherwise pending quarantine"
            )
            command.add_argument("--limit", type=int, default=10)
        if name == "observe-current":
            command.add_argument("--same-time-correction-reason")
        if name == "poll-current":
            command.add_argument(
                "--until", required=True, help="explicit aware ISO manual window end"
            )
            command.add_argument("--interval", type=float, default=30)


async def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    validate_ins_code(args.ins_code)
    if args.command not in {"db-status", "collection-status", "export-db-chartdata", "retention"}:
        require_pilot(args.ins_code)
    db = Database(DatabaseSettings.from_env())
    try:
        if args.command in {"db-status", "collection-status", "export-db-chartdata"}:
            async with db.read() as conn:
                if args.command == "db-status":
                    return await verify_schema(conn), 0
                if args.command == "collection-status":
                    return await collection_report(conn, args.ins_code), 0
                records, details = await read_daily(conn, args.ins_code, selection=args.selection)
                chart = to_chartdata(records)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    chart.to_json(legacy_sample=args.legacy_sample) + "\n", encoding="utf8"
                )
                return {
                    **details,
                    "output": str(args.output),
                    "unknown_activity_zero_placeholders": {
                        "f": sum(r.trade_count is None for r in records),
                        "g": sum(r.traded_volume is None for r in records),
                        "h": sum(r.traded_value is None for r in records),
                    },
                }, 0
        dry_read = getattr(args, "dry_run", False) or (
            args.command == "retention" and not args.apply
        )
        async with db.read() if dry_read else db.owner(args.ins_code) as conn:
            if args.command == "retention":
                if dry_read:
                    return await retain(conn, args.ins_code), 0
                async with conn.begin():
                    return await retain(conn, args.ins_code, apply=True), 0
            # Authorization is at the live CLI boundary, not in generic storage/collector logic.
            require_pilot(args.ins_code)
            instruments = load_instruments(args.instrument_config)
            configured = instruments.get(args.ins_code)
            if configured is None or not configured.enabled:
                raise ValueError("requested instrument is not enabled in instrument config")
            async with AsyncExitStack() as stack:
                source: Source
                if args.capture_dir:
                    source = CaptureReplay(args.capture_dir)
                else:
                    source = await stack.enter_async_context(TSETMCClient(Settings.from_env()))
                repository = Repository(conn, args.ins_code)
                collector = Collector(
                    repository,
                    source,
                    kind="captured_replay" if args.capture_dir else "live_http",
                    active=not bool(args.capture_dir),
                    expected_instrument_id=configured.instrument_id,
                )
                dates = None
                if args.command == "reconcile-history":
                    dates = (
                        [parse_source_date(args.date)]
                        if args.date
                        else await pending_dates(conn, args.ins_code, args.limit)
                    )
                    if not dry_read and conn.in_transaction():
                        await conn.commit()
                    if not dates:
                        return {"status": "no_pending_daily_quarantine", "source_requests": 0}, 0
                if args.command == "poll-current":
                    if args.run_id or args.dry_run or args.capture_dir:
                        raise ValueError(
                            "polling requires live manual operation, without replay/run-id/dry-run"
                        )
                    until = (
                        datetime.fromisoformat(args.until).astimezone(UTC)
                        if (datetime.fromisoformat(args.until).tzinfo is not None)
                        else None
                    )
                    if until is None or not timedelta(0) < until - datetime.now(UTC) <= timedelta(
                        days=1
                    ):
                        raise ValueError(
                            "polling requires an explicit future aware window, at most one day"
                        )
                    result = await poll(
                        lambda: collector.run("observe-current"), PollPolicy(until, args.interval)
                    )
                    return result, 0 if result["status"] == "manual_window_ended" else 1
                result = await collector.run(
                    args.command,
                    source_limit=getattr(args, "source_limit", 0),
                    dates=dates,
                    run_id=args.run_id,
                    correction_reason=getattr(args, "same_time_correction_reason", None),
                    dry_run=args.dry_run,
                )
                return result, 2 if result.get("status") == "partial" else 0
    finally:
        await db.aclose()
