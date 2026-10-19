"""Explicit local operations; secrets stay in ignored .local files and child environments.

Run from the repository root. This helper only addresses the named TSETMC Compose
project. It never removes a volume or overwrites an existing backup/database.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.engine import URL

from tsetmc_marketdata.storage.config import DatabaseSettings
from tsetmc_marketdata.storage.database import Database, make_engine, verify_schema

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".local/database.json"
ENV = ROOT / ".local/postgres.env"
CONTAINER = "tsetmc-m2-local-postgres-1"


def private_settings() -> dict[str, str]:
    values: dict[str, str] = json.loads(PRIVATE.read_text(encoding="utf8"))
    for key in ("owner", "collector"):
        DatabaseSettings(values[key]).validated_url()
    return values


def initialize(port: int) -> None:
    if PRIVATE.exists() or ENV.exists():
        raise ValueError("private configuration already exists; preserve it rather than overwrite")
    if not 1024 <= port <= 65535:
        raise ValueError("port must be 1024..65535; inspect Docker resources and listeners first")
    owner, collector = secrets.token_urlsafe(36), secrets.token_urlsafe(36)
    PRIVATE.parent.mkdir(exist_ok=True)
    values = {}
    for key, user, password in (
        ("owner", "tsetmc_owner", owner),
        ("collector", "tsetmc_collector", collector),
    ):
        values[key] = URL.create(
            "postgresql+asyncpg",
            username=user,
            password=password,
            host="127.0.0.1",
            port=port,
            database="tsetmc_marketdata",
        ).render_as_string(hide_password=False)
    PRIVATE.write_text(json.dumps(values), encoding="utf8")
    ENV.write_text(
        f"TSETMC_PG_PASSWORD={owner}\nTSETMC_COLLECTOR_PASSWORD={collector}\nTSETMC_PG_PORT={port}\n",
        encoding="utf8",
    )
    if os.name != "nt":
        PRIVATE.chmod(0o600)
        ENV.chmod(0o600)
    print("Created ignored local credentials; restrict access to .local and retain them securely.")


def docker(command: list[str], *, input_bytes: bytes | None = None) -> bytes:
    inspected = (
        subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                '{{index .Config.Labels "com.docker.compose.project"}}',
                CONTAINER,
            ],
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .strip()
    )
    if inspected != "tsetmc-m2-local":
        raise ValueError("container does not belong to the independent TSETMC project")
    result = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, *command],
        input=input_bytes,
        capture_output=True,
    )
    if result.returncode:
        raise ValueError("TSETMC database operation failed; sensitive stderr withheld")
    return result.stdout


def backup(path: Path) -> None:
    path = path.resolve()
    private_root = (ROOT / ".local").resolve()
    if not path.is_relative_to(private_root):
        raise ValueError("database backups must remain inside ignored .local")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(
            docker(
                [
                    "pg_dump",
                    "-U",
                    "tsetmc_owner",
                    "-d",
                    "tsetmc_marketdata",
                    "--format=custom",
                    "--no-owner",
                    "--no-acl",
                ]
            )
        )
    print(json.dumps({"backup": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size}))


async def restore_check(path: Path, expected_revision: str | None = None) -> dict[str, Any]:
    # Restore into a newly generated test DB only, never over the collector's persistent DB.
    name = "tsetmc_test_" + uuid4().hex
    settings = DatabaseSettings(private_settings()["owner"])
    admin = make_engine(settings).execution_options(isolation_level="AUTOCOMMIT")
    created = False
    try:
        async with admin.connect() as conn:
            await conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
            created = True
        body = await asyncio.to_thread(path.read_bytes)
        await asyncio.to_thread(
            docker,
            [
                "pg_restore",
                "-U",
                "tsetmc_owner",
                "-d",
                name,
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
            ],
            input_bytes=body,
        )
        url = settings.validated_url().set(database=name).render_as_string(hide_password=False)
        db = Database(DatabaseSettings(url))
        try:
            async with db.engine.connect() as conn:
                await conn.execute(sa.text("SET TRANSACTION READ ONLY"))
                if expected_revision is None:
                    result = await verify_schema(conn)
                else:
                    if expected_revision not in {"0002_instrument_links", "0003_scheduling"}:
                        raise ValueError("unsupported historical backup schema")
                    revision = await conn.scalar(sa.text("SELECT version_num FROM alembic_version"))
                    if revision != expected_revision:
                        raise ValueError("restored schema differs from expected backup schema")
                    result = {"database": name, "schema_revision": revision}
                result["daily_records"] = await conn.scalar(
                    sa.text("SELECT count(*) FROM daily_records")
                )
                result["current_snapshots"] = await conn.scalar(
                    sa.text("SELECT count(*) FROM current_snapshots")
                )
                result["source_observations"] = await conn.scalar(
                    sa.text("SELECT count(*) FROM source_observations")
                )
                rows = (
                    await conn.execute(
                        sa.text(
                            "SELECT ins_code,trading_date,financial_hash,revision,"
                            "finalization_state "
                            "FROM daily_records ORDER BY ins_code,trading_date"
                        )
                    )
                ).all()
                result["daily_state_sha256"] = hashlib.sha256(
                    "\n".join(map(str, rows)).encode()
                ).hexdigest()
                bodies = await conn.stream(
                    sa.text(
                        "SELECT raw_body,raw_sha256 FROM source_observations "
                        "WHERE raw_body IS NOT NULL"
                    )
                )
                checked = 0
                async for body, digest in bodies:
                    if hashlib.sha256(body).hexdigest() != digest:
                        raise ValueError("restored raw evidence hash differs")
                    checked += 1
                result["raw_hashes_verified"] = checked
                return result
        finally:
            await db.aclose()
    finally:
        if created:
            async with admin.connect() as conn:
                await conn.execute(sa.text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    initialize_parser = commands.add_parser("init")
    initialize_parser.add_argument("--port", type=int, default=5542)
    commands.add_parser("start")
    commands.add_parser("migrate")
    for name in ("run", "test"):
        commands.add_parser(name).add_argument("arguments", nargs=argparse.REMAINDER)
    backup_parser = commands.add_parser("backup")
    backup_parser.add_argument("--output", type=Path)
    restore_parser = commands.add_parser("restore-check")
    restore_parser.add_argument("input", type=Path)
    restore_parser.add_argument("--expected-revision")
    args = parser.parse_args()
    try:
        if args.command == "init":
            initialize(args.port)
            return 0
        if args.command == "start":
            return subprocess.call(
                [
                    "docker",
                    "compose",
                    "--env-file",
                    str(ENV),
                    "-f",
                    "compose.tsetmc.yaml",
                    "up",
                    "-d",
                    "--wait",
                    "postgres",
                ],
                cwd=ROOT,
            )
        if args.command == "backup":
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            backup(args.output or ROOT / f".local/backups/{stamp}.dump")
            return 0
        if args.command == "restore-check":
            print(
                json.dumps(
                    asyncio.run(restore_check(args.input, args.expected_revision)), sort_keys=True
                )
            )
            return 0
        values = private_settings()
        env = dict(os.environ)
        if args.command == "migrate":
            env["TSETMC_MIGRATION_URL"] = values["owner"]
            child = ["alembic", "upgrade", "head"]
        else:
            arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
            if args.command == "test":
                env["TSETMC_TEST_ADMIN_URL"] = values["owner"]
                env["TSETMC_TEST_DOCKER_CONTAINER"] = CONTAINER
                child = ["pytest", *arguments]
            else:
                env["TSETMC_DATABASE_URL"] = values["collector"]
                child = ["python", "-m", "tsetmc_marketdata.cli", *arguments]
        return subprocess.call(["uv", "run", "--offline", *child], env=env, cwd=ROOT)
    except (ValueError, OSError, sa.exc.SQLAlchemyError, subprocess.SubprocessError) as exc:
        print(
            json.dumps(
                {
                    "error": type(exc).__name__,
                    "message": "Local operation failed; no credentials displayed",
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
