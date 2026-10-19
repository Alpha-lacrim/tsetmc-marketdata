"""Source protocol and explicitly private offline capture replay; one real HTTP implementation."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from tsetmc_marketdata.jsonio import loads_source
from tsetmc_marketdata.providers.http_client import JSONResponse


class Source(Protocol):
    async def get_json(self, path: str) -> JSONResponse: ...


class CaptureReplay:
    """A manifest-backed offline reader, never an HTTP transport or freshness claim."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf8"))
        self.entries = {
            item["path"]: (item, directory / (item["name"] + ".json"))
            for item in manifest
            if item.get("status") == 200
        }
        for sidecar in directory.glob("*.metadata.json"):
            item = json.loads(sidecar.read_text(encoding="utf8"))
            if item.get("status") == 200:
                self.entries[item["path"]] = (
                    item,
                    directory / sidecar.name.replace(".metadata", ""),
                )

    async def get_json(self, path: str) -> JSONResponse:
        if path not in self.entries:
            raise ValueError("requested path is absent from the supplied private capture manifest")
        item, body_path = self.entries[path]
        body = body_path.read_bytes()
        if hashlib.sha256(body).hexdigest() != item["sha256"]:
            raise ValueError("capture hash does not match its original manifest")
        receipt = datetime.fromisoformat(item["received_at"])
        if receipt.tzinfo is None or receipt.utcoffset() != UTC.utcoffset(receipt):
            raise ValueError("capture manifest must contain an aware UTC receipt instant")
        payload = loads_source(body)
        if not isinstance(payload, dict):
            raise ValueError("capture must contain a source JSON object envelope")
        return JSONResponse(payload, body, receipt, 200, path)
