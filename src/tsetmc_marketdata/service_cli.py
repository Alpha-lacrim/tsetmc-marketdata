"""Milestone 3A opt-in service, private evidence inspection and operator review commands."""

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa

from tsetmc_marketdata.collection.budget import BudgetSource
from tsetmc_marketdata.collection.service import CollectionService
from tsetmc_marketdata.collection.service_config import load_service_config
from tsetmc_marketdata.config import PILOT_INS_CODE, require_pilot, validate_ins_code
from tsetmc_marketdata.providers.http_client import TSETMCClient
from tsetmc_marketdata.storage import schema_v1 as t
from tsetmc_marketdata.storage import schema_v3a as s
from tsetmc_marketdata.storage.config import DatabaseSettings
from tsetmc_marketdata.storage.database import Database
from tsetmc_marketdata.storage.health import health_report
from tsetmc_marketdata.storage.repository import Repository
from tsetmc_marketdata.storage.reviews import review_daily
from tsetmc_marketdata.storage.serialization import json_safe
from tsetmc_marketdata.utils.dates import parse_source_date

COMMANDS = {
    "run-collector",
    "validate-collector-config",
    "collector-health",
    "review-daily",
    "inspect-collection-evidence",
}


def configure(subparsers: Any) -> None:
    for name in sorted(COMMANDS):
        command = subparsers.add_parser(name)
        command.add_argument("--report", type=Path)
        if name in {"run-collector", "validate-collector-config"}:
            command.add_argument("--config", type=Path, required=True)
            if name == "run-collector":
                command.add_argument("--activate", action="store_true")
                command.add_argument("--evidence-dir", type=Path)
            continue
        command.add_argument("--ins-code", default=PILOT_INS_CODE)
        if name == "collector-health":
            command.add_argument("--include-prices", action="store_true")
            command.add_argument("--stale-after", type=float, default=180)
        elif name == "review-daily":
            command.add_argument("--date", required=True)
            command.add_argument("--action", choices=("confirm", "revoke"), required=True)
            command.add_argument("--expected-hash", required=True)
            command.add_argument("--actor", required=True)
            command.add_argument("--reason", required=True)
            command.add_argument("--review-id", type=UUID)
            command.add_argument("--observation-id", type=int, action="append", default=[])
            command.add_argument("--session-end")
            command.add_argument("--session-evidence")
            command.add_argument("--grace-seconds", type=int, default=3600)
        else:
            command.add_argument(
                "--kind",
                choices=("revisions", "quarantine", "reviews", "observations"),
                required=True,
            )
            command.add_argument("--date")
            command.add_argument("--limit", type=int, default=20)
            command.add_argument("--private-details", action="store_true")


async def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    config = None
    if args.command in {"run-collector", "validate-collector-config"}:
        config = load_service_config(args.config)
        if args.command == "validate-collector-config":
            return {
                "valid": True,
                "enabled": config.enabled,
                "logical_request_budget": config.request_budget,
                "jobs": [j.key for j in config.jobs],
                "session_inference": "no_builtin_calendar",
            }, 0
        require_pilot(config.ins_code)
        if not args.activate or not config.enabled:
            raise ValueError("explicit --activate and enabled=true configuration are required")
        if config.expected_instrument_id != "IRO1FOLD0001":
            raise ValueError("live pilot configuration requires the verified instrument identifier")
    else:
        validate_ins_code(args.ins_code)
    db = Database(DatabaseSettings.from_env())
    try:
        if args.command == "collector-health":
            async with db.read() as conn:
                return await health_report(
                    conn,
                    args.ins_code,
                    datetime.now(UTC),
                    include_prices=args.include_prices,
                    stale_after=args.stale_after,
                ), 0
        if args.command == "inspect-collection-evidence":
            if not 1 <= args.limit <= 100:
                raise ValueError("inspection limit must be 1..100")
            table = {
                "revisions": t.revisions,
                "quarantine": t.quarantine,
                "reviews": s.reviews,
                "observations": t.observations,
            }[args.kind]
            query = sa.select(table).where(table.c.ins_code == args.ins_code)
            if args.date:
                if args.kind == "observations":
                    raise ValueError("observation requests may span dates; omit --date")
                query = query.where(table.c.trading_date == parse_source_date(args.date))
            query = query.order_by(*[c.desc() for c in table.primary_key.columns]).limit(args.limit)
            async with db.read() as conn:
                rows = (await conn.execute(query)).mappings().all()
            hidden = {"raw_body", "raw_row", "old_state", "new_state"}
            return {
                "ins_code": args.ins_code,
                "kind": args.kind,
                "rows": json_safe(
                    [
                        {key: value for key, value in row.items() if key not in hidden}
                        if not args.private_details
                        else {key: value for key, value in row.items() if key != "raw_body"}
                        for row in rows
                    ]
                ),
            }, 0
        if args.command == "review-daily":
            require_pilot(args.ins_code)
            if len(args.observation_id) not in {0, 2}:
                raise ValueError("supply exactly two observation IDs for confirmation")
            async with db.owner(args.ins_code) as conn:
                return await review_daily(
                    Repository(conn, args.ins_code),
                    review_id=args.review_id or uuid4(),
                    day=parse_source_date(args.date),
                    expected_hash=args.expected_hash,
                    action=args.action,
                    actor=args.actor,
                    reason=args.reason,
                    now=datetime.now(UTC),
                    first_observation_id=args.observation_id[0] if args.observation_id else None,
                    second_observation_id=args.observation_id[1] if args.observation_id else None,
                    session_end=datetime.fromisoformat(args.session_end)
                    if args.session_end
                    else None,
                    session_evidence=args.session_evidence,
                    grace_seconds=args.grace_seconds,
                ), 0
        assert config is not None
        directory = None
        if args.evidence_dir:
            requested = args.evidence_dir.resolve()
            if not any(
                requested.is_relative_to((Path.cwd() / name).resolve())
                for name in (".local", "output")
            ):
                raise ValueError("private qualification evidence must stay under .local or output")
            directory = requested / str(uuid4())
        settings = config.http_settings()
        async with db.owner(config.ins_code) as conn, TSETMCClient(settings) as http:
            source = BudgetSource(http, config.ins_code, config.request_budget, directory)
            result = await CollectionService(
                Repository(conn, config.ins_code), source, config
            ).run()
            if directory:
                result["private_evidence"] = str(directory.relative_to(Path.cwd()))
            return result, 1 if result["state"] == "failed" else 0
    finally:
        await db.aclose()
