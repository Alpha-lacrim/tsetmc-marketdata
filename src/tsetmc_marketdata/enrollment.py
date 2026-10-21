"""Explicit bounded enrollment of stored records. Never fetches provider data."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from tsetmc_marketdata.storage.config import DatabaseSettings
from tsetmc_marketdata.storage.database import Database
from tsetmc_marketdata.storage.outbox import SourceOutbox
from tsetmc_marketdata.storage.repository import Repository


async def enroll(path: Path) -> None:
    plan = json.loads(await asyncio.to_thread(path.read_text, encoding="utf8"))
    db = Database(DatabaseSettings.from_env())
    try:
        async with db.owner(plan["ins_code"]) as conn:
            repo = Repository(conn, plan["ins_code"])
            async with repo.atomic():
                box = SourceOutbox(repo)
                await box.configure(
                    source_epoch=UUID(plan["source_epoch"]),
                    installation_id=UUID(plan["installation_id"]),
                    destination_id=UUID(plan["destination_id"]),
                    producer_id=UUID(plan["producer_id"]),
                )
                result = await box.enroll(
                    seed_id=UUID(plan["seed_id"]),
                    allow_local_publication=True,
                    max_daily_rows=10000,
                    max_bytes=32 * 1024 * 1024,
                )
        print(json.dumps(result, default=str))
    finally:
        await db.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--activate", action="store_true", required=True)
    args = parser.parse_args()
    try:
        asyncio.run(enroll(args.binding))
        return 0
    except Exception as error:
        print(json.dumps({"error": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
