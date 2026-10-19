"""Bounded source probes, local database jobs and explicitly activated manual polling."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from tsetmc_marketdata import db_cli
from tsetmc_marketdata.adapters.chartdata import to_chartdata
from tsetmc_marketdata.config import PILOT_INS_CODE, Settings, require_pilot
from tsetmc_marketdata.errors import ErrorKind, SourceDataError, TSETMCError
from tsetmc_marketdata.jsonio import diagnostic_default, loads_source
from tsetmc_marketdata.parsing import (
    HistoryResult,
    parse_current,
    parse_history,
    parse_instrument,
    parse_targeted_daily,
)
from tsetmc_marketdata.providers.http_client import JSONResponse, TSETMCClient
from tsetmc_marketdata.storage.config import StorageError
from tsetmc_marketdata.utils.dates import calendar_gaps, parse_source_date


def _json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=True, indent=2, default=diagnostic_default, allow_nan=False
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


def _summary(history: HistoryResult) -> dict[str, Any]:
    records = history.records
    days = [r.trading_date for r in records]
    return {
        "valid_records": len(records),
        "source_records": len(history.raw_payload["closingPriceDaily"]),
        "earliest": days[0] if days else None,
        "latest": days[-1] if days else None,
        "sample_14_columns": records[-1].table_columns() if records else None,
        "calendar_gaps_first_20": calendar_gaps(days)[:20],
        "calendar_gaps_meaning": "unobserved calendar dates; session status unknown",
        "diagnostics": [asdict(d) for d in history.diagnostics],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in (
        "probe-history",
        "probe-daily",
        "probe-current",
        "probe-instrument",
        "export-chartdata",
        "inspect-fields",
    ):
        command = sub.add_parser(name)
        command.add_argument("--ins-code", default=PILOT_INS_CODE)
        command.add_argument("--input", type=Path, help="saved source JSON; makes no HTTP request")
        command.add_argument("--base-url", help="overrides TSETMC_BASE_URL")
        command.add_argument("--timeout", type=float, help="total request deadline in seconds")
        command.add_argument("--retries", type=int, help="0..5 retries; 403 is never retried")
        command.add_argument("--pacing", type=float, help="minimum seconds between request starts")
        command.add_argument(
            "--source-limit",
            type=int,
            default=0,
            help="raw history parameter; observed 0=available history and n=latest n rows",
        )
        command.add_argument(
            "--raw-output", type=Path, help="save exact successful source body + receipt sidecar"
        )
        command.add_argument(
            "--report", type=Path, help="save structured success/error diagnostics"
        )
        if name == "export-chartdata":
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--legacy-sample", action="store_true", help="append i:null")
            command.add_argument(
                "--allow-partial",
                action="store_true",
                help="explicitly export valid dates when other rows are quarantined",
            )
        if name == "probe-daily":
            command.add_argument("--date", required=True, help="Gregorian YYYYMMDD")
        if name == "inspect-fields":
            command.add_argument(
                "--kind", choices=("history", "current", "instrument"), default="history"
            )
    db_cli.configure(sub)
    return parser


async def _payload(args: argparse.Namespace) -> tuple[dict[str, Any], datetime | None]:
    response: JSONResponse | None = None
    if args.input:
        body = args.input.read_bytes()
        try:
            payload = loads_source(body)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise SourceDataError(
                ErrorKind.INVALID_JSON, "saved input is not valid source JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise SourceDataError(
                ErrorKind.SCHEMA, "saved input must be a source JSON object envelope"
            )
    else:
        settings = Settings.from_env()
        overrides = {
            name: value
            for name, value in {
                "base_url": args.base_url,
                "total_timeout": args.timeout,
                "max_retries": args.retries,
                "pacing_seconds": args.pacing,
            }.items()
            if value is not None
        }
        settings = replace(settings, **overrides)
        kind = args.kind if args.command == "inspect-fields" else args.command
        if kind in {"probe-current", "current"}:
            path = f"ClosingPrice/GetClosingPriceInfo/{args.ins_code}"
        elif kind in {"probe-instrument", "instrument"}:
            path = f"Instrument/GetInstrumentInfo/{args.ins_code}"
        elif kind == "probe-daily":
            day = parse_source_date(args.date)
            path = f"ClosingPrice/GetClosingPriceDaily/{args.ins_code}/{day:%Y%m%d}"
        else:
            if not 0 <= args.source_limit <= 100000:
                raise ValueError("source-limit must be between 0 and 100000")
            path = f"ClosingPrice/GetClosingPriceDailyList/{args.ins_code}/{args.source_limit}"
        async with TSETMCClient(settings) as client:
            response = await client.get_json(path)
        payload, body = response.payload, response.raw_body
    if args.raw_output:
        args.raw_output.parent.mkdir(parents=True, exist_ok=True)
        args.raw_output.write_bytes(body)
        _write(
            args.raw_output.with_suffix(args.raw_output.suffix + ".metadata.json"),
            _json(
                {
                    "provenance": "live_http" if response else "copied_offline_input",
                    "received_at": response.received_at if response else None,
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "path": response.path if response else None,
                }
            ),
        )
    # A saved JSON file has no receipt instant unless supplied through an evidence manifest.
    return payload, response.received_at if response else None


async def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.command in db_cli.COMMANDS:
        return await db_cli.run(args)
    require_pilot(args.ins_code)
    payload, receipt = await _payload(args)
    if args.command == "inspect-fields":
        key = {
            "history": "closingPriceDaily",
            "current": "closingPriceInfo",
            "instrument": "instrumentInfo",
        }[args.kind]
        value = payload.get(key)
        if key not in payload or not isinstance(value, list if args.kind == "history" else dict):
            raise SourceDataError(ErrorKind.SCHEMA, f"unexpected {key} envelope")
        rows = value if isinstance(value, list) else [value]
        fields: dict[str, set[str]] = {}
        for row in rows:
            if isinstance(row, dict):
                for name, item in row.items():
                    fields.setdefault(name, set()).add(type(item).__name__)
        return {
            "envelope_keys": sorted(payload),
            "expected_envelope": key,
            "rows": len(rows),
            "fields": {k: sorted(v) for k, v in sorted(fields.items())},
        }, 0
    if args.command == "probe-current":
        current = parse_current(payload, args.ins_code, received_at=receipt)
        result = asdict(current)
        result.update(
            last_trade_change=asdict(current.last_trade_change),
            closing_change=asdict(current.closing_change),
        )
        return result, 0
    if args.command == "probe-instrument":
        return asdict(parse_instrument(payload, args.ins_code)), 0
    if args.command == "probe-daily":
        record = parse_targeted_daily(payload, args.ins_code, parse_source_date(args.date))
        return {"table_14_columns": record.table_columns(), "raw": record.raw}, 0
    history = parse_history(payload, args.ins_code)
    summary = _summary(history)
    if args.command == "export-chartdata":
        if history.has_errors and not args.allow_partial:
            summary["error"] = (
                "quarantined records; review diagnostics or explicitly use --allow-partial"
            )
            return summary, 2
        chart = to_chartdata(history.records)
        _write(args.output, chart.to_json(legacy_sample=args.legacy_sample))
        summary["output"] = str(args.output)
        summary["unknown_activity_zero_placeholders"] = {
            "f": sum(r.trade_count is None for r in history.records),
            "g": sum(r.traded_volume is None for r in history.records),
            "h": sum(r.traded_value is None for r in history.records),
        }
        return summary, 0
    return summary, 2 if history.has_errors else 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result, code = asyncio.run(run(args))
    except TSETMCError as exc:
        result, code = exc.as_dict(), 1
    except StorageError as exc:
        result, code = {"error": exc.category, "message": str(exc)}, 1
    except sa.exc.SQLAlchemyError:
        result, code = (
            {
                "error": "postgres_write_failure",
                "message": "PostgreSQL operation failed; inspect durable collection status",
            },
            1,
        )
    except ValueError as exc:
        result, code = {"error": "invalid_input", "message": str(exc)}, 1
    except OSError as exc:
        result, code = {"error": "invalid_input_or_io", "message": type(exc).__name__}, 1
    except KeyboardInterrupt:
        result, code = {"error": "cancelled"}, 130
    result["reported_at"] = datetime.now(UTC)
    rendered = _json(result)
    if args.report:
        try:
            _write(args.report, rendered)
        except OSError:
            print('{"error":"cannot_write_report"}', file=sys.stderr)
            return 1
    print(rendered, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
