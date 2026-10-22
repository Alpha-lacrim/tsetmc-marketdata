"""Durable single-batch retry file. No source database or company database credentials."""

import asyncio
import hashlib
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx


def json_value(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError("unsupported upload value")


@contextmanager
def single_instance(directory: Path) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "collector.lock").open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def sync_directory(path: Path) -> None:
    if sys.platform != "win32":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


class PendingUpload:
    def __init__(self, endpoint: str, path: Path, client: httpx.AsyncClient):
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("API URL must be an HTTP(S) origin, e.g. http://server:8000")
        self.endpoint, self.path, self.client = endpoint.rstrip("/"), path, client

    def stage(self, observations: list[dict[str, Any]]) -> None:
        if self.path.exists():
            raise RuntimeError("flush pending upload before collecting another batch")
        raw = json.dumps(
            {"batch_id": str(uuid4()), "observations": observations},
            default=json_value,
            allow_nan=False,
            separators=(",", ":"),
        )
        if len(raw.encode()) > 16 * 1024 * 1024:
            raise ValueError("upload exceeds 16 MiB; reduce batch size")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump({"endpoint": self.endpoint, "payload": raw}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)
        sync_directory(self.path.parent)

    async def flush(self) -> None:
        if not self.path.exists():
            return
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        if saved["endpoint"] != self.endpoint:
            raise ValueError("pending upload belongs to another API URL; preserve and review it")
        raw = saved["payload"].encode()
        batch = json.loads(raw)
        response = await self.client.post(
            self.endpoint + "/api/ingest", content=raw, headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        receipt = response.json()
        if (
            receipt.get("batch_id") != batch["batch_id"]
            or receipt.get("sha256") != hashlib.sha256(raw).hexdigest()
            or type(receipt.get("accepted")) is not int
            or receipt.get("accepted") != len(batch["observations"])
        ):
            raise ValueError("API receipt does not match durable upload; pending file retained")
        self.path.unlink()
        sync_directory(self.path.parent)

    async def drain(self) -> None:
        while self.path.exists():
            delay = 30.0
            try:
                await self.flush()
            except httpx.HTTPStatusError as error:
                if error.response.status_code not in {408, 429, 500, 502, 503, 504}:
                    raise ValueError(
                        f"API rejected upload ({error.response.status_code}); file retained"
                    ) from None
                try:
                    delay = max(delay, float(error.response.headers.get("retry-after", "30")))
                except ValueError:
                    pass
            except httpx.TransportError:
                pass
            if self.path.exists():
                print("API unavailable; pending upload preserved, retrying.", flush=True)
                await asyncio.sleep(min(delay, 3600))
