"""Opt-in bounded HTTPS delivery. No provider connection or company database credentials."""

import argparse
import asyncio
import hashlib
import json
import os
import re
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import sqlalchemy as sa

from tsetmc_marketdata.config import validate_ins_code
from tsetmc_marketdata.storage import schema_v3b1 as p
from tsetmc_marketdata.storage.config import DatabaseSettings, OwnershipError
from tsetmc_marketdata.storage.database import Database
from tsetmc_marketdata.storage.outbox import RecoveryFence, SourceOutbox
from tsetmc_marketdata.storage.publication_wire import decode, encode, identity, validate
from tsetmc_marketdata.storage.repository import Repository


class DeliveryError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.retryable = retryable


@dataclass(frozen=True)
class DeliveryConfig:
    endpoint: str
    ins_code: str
    producer_id: UUID
    destination_id: UUID
    session_id: UUID
    session_generation: int
    token_file: Path
    anchor_file: Path
    ca_file: Path | None = None

    @classmethod
    def load(cls, path: Path) -> "DeliveryConfig":
        raw = decode(path.read_bytes())
        values: dict[str, Any] = {
            k: UUID(v) if k.endswith("_id") else Path(v) if k.endswith("_file") and v else v
            for k, v in raw.items()
        }
        config = cls(**values)
        parsed = urlsplit(config.endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("verified HTTPS origin required")
        validate_ins_code(config.ins_code)
        if type(config.session_generation) is not int or config.session_generation < 1:
            raise ValueError("positive session generation required")
        if not config.anchor_file.is_absolute() or not config.token_file.is_absolute():
            raise ValueError("private token and external anchor paths must be absolute")
        return config


class Worker:
    def __init__(self, db: Database, config: DeliveryConfig):
        self.db, self.config = db, config
        self.owner_token = uuid4()
        self.state: dict[str, Any] = {}
        self.anchor: dict[str, Any] = {}
        context = ssl.create_default_context(cafile=str(config.ca_file) if config.ca_file else None)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.http = httpx.AsyncClient(
            base_url=config.endpoint,
            verify=context,
            trust_env=False,
            follow_redirects=False,
            timeout=20,
            limits=httpx.Limits(max_connections=1),
        )
        self.last_request = 0.0

    async def request(
        self, method: str, path: str, raw: bytes | None = None
    ) -> dict[str, Any] | None:
        token = self.config.token_file.read_text().strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}\.[A-Za-z0-9_-]{43,128}", token):
            raise DeliveryError("invalid_token_file")
        delay = max(0, 0.65 - (asyncio.get_running_loop().time() - self.last_request))
        await asyncio.sleep(delay)
        self.last_request = asyncio.get_running_loop().time()
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        if raw is not None:
            headers["X-Payload-SHA256"] = hashlib.sha256(raw).hexdigest()
        try:
            async with (
                asyncio.timeout(25),
                self.http.stream(
                    method, "/api/ingest/v1" + path, content=raw, headers=headers
                ) as response,
            ):
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 4194304:
                        raise DeliveryError("response_limit")
                if response.status_code == 404 and method == "GET":
                    return None
                if response.status_code != 200:
                    raise DeliveryError(
                        "http_" + str(response.status_code),
                        retryable=response.status_code in {429, 502, 503, 504},
                    )
                return decode(bytes(body))
        except (httpx.HTTPError, TimeoutError, OSError):
            raise DeliveryError("transport_unavailable", retryable=True) from None

    async def fence(self, conn: Any) -> None:
        row = (
            (
                await conn.execute(
                    sa.text("SELECT * FROM sync_delivery_state WHERE producer_id=:id FOR UPDATE"),
                    {"id": self.config.producer_id},
                )
            )
            .mappings()
            .one()
        )
        live = await conn.scalar(
            sa.text(
                "SELECT EXISTS(SELECT FROM pg_locks WHERE pid=:pid AND "
                "locktype='advisory' AND classid=81484 AND objid=:key AND granted)"
            ),
            {"pid": row["backend_pid"], "key": self.lock_key},
        )
        if row["owner_token"] != self.owner_token or not live:
            raise RecoveryFence("delivery coordinator lost")

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[SourceOutbox]:
        # Collector ownership is held only during short local transactions, never HTTPS.
        async with self.db.owner(self.config.ins_code) as conn:
            repo = Repository(conn, self.config.ins_code)
            async with repo.atomic():
                await self.fence(conn)
                conn.info["authenticated_delivery"] = True
                box = SourceOutbox(repo)
                await box.load()
                assert box.dataset is not None
                if (box.dataset["producer_id"], box.dataset["destination_id"]) != (
                    self.config.producer_id,
                    self.config.destination_id,
                ):
                    raise RecoveryFence("configured dataset binding mismatch")
                yield box
                await self.fence(conn)

    async def save_state(self) -> None:
        async with self.transaction() as box:
            await box.conn.execute(
                sa.text(
                    "UPDATE sync_delivery_state SET state=CAST(:state AS jsonb) WHERE "
                    "producer_id=:id"
                ),
                {"state": json.dumps(self.state), "id": self.config.producer_id},
            )

    async def checkpoint(self) -> None:
        async with self.transaction() as box:
            assert box.dataset is not None
            await box.lock_clocks()
            batches = (
                (
                    await box.conn.execute(
                        sa.select(p.batches).where(box.scope(p.batches)).limit(10001)
                    )
                )
                .mappings()
                .all()
            )
            if len(batches) > 10000 or any(r["simulated"] for r in batches):
                raise RecoveryFence(
                    "batch audit bound or simulated history requires administrator review"
                )
            proof: dict[str, Any] = {
                k: str(box.dataset[k])
                for k in ("source_epoch", "installation_id", "destination_id", "producer_id")
            }
            proof["streams"] = {
                s: {"head": r["head"], "acknowledged": r["acknowledged"]}
                for s, r in box.clocks.items()
            }
            proof["staged"] = {str(r["batch_id"]): r["payload_sha256"] for r in batches}
            if self.anchor:
                await box.continuity(self.anchor)
            elif batches:
                raise RecoveryFence("missing external anchor for existing delivery history")
        target = self.config.anchor_file
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".pending")
        with temporary.open("wb") as file:
            file.write(encode(proof))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, target)
        self.anchor = proof

    async def session(self) -> None:
        async with self.transaction() as box:
            assert box.dataset is not None
            expected = [
                dict(
                    instrument_id=identity(self.config.ins_code, None)["instrument_id"],
                    provider="tsetmc",
                    stream=s,
                    source_epoch=str(box.dataset["source_epoch"]),
                    ownership_generation=box.dataset["ownership_generation"],
                )
                for s in p.STREAMS
            ]
        if self.state.get("streams", expected) != expected:
            raise RecoveryFence("saved producer manifest differs from dataset")
        self.state["streams"] = expected
        await self.save_state()
        request = {
            "protocol_version": 1,
            "session_id": self.state["session_id"],
            "session_generation": self.state["session_generation"],
        }
        try:
            result = await self.request("POST", "/session/renew", encode(request))
            assert result is not None
            if (
                result["producer_id"] != str(self.config.producer_id)
                or result["session_id"] != request["session_id"]
                or result["session_generation"] != request["session_generation"]
            ):
                raise RecoveryFence("unexpected session identity")
            actual = [{k: r[k] for k in expected[0]} for r in result["streams"]]
            if sorted(actual, key=lambda r: r["stream"]) != sorted(
                expected, key=lambda r: r["stream"]
            ):
                raise RecoveryFence("unexpected producer manifest")
            self.state["streams"] = expected
            await self.save_state()
        except DeliveryError as error:
            if str(error) != "http_409":
                raise
            recovery = self.state.setdefault(
                "recovery",
                dict(
                    protocol_version=1,
                    recovery_id=str(uuid4()),
                    previous_session_id=request["session_id"],
                    previous_session_generation=request["session_generation"],
                    streams=self.state["streams"],
                ),
            )
            await self.save_state()
            recovered = await self.request("POST", "/session/recover", encode(recovery))
            if (
                not recovered
                or recovered.get("producer_id") != str(self.config.producer_id)
                or recovered.get("recovery_id") != recovery["recovery_id"]
                or recovered.get("state") != "committed"
                or recovered.get("previous_session_id") != request["session_id"]
                or recovered.get("previous_session_generation") != request["session_generation"]
                or recovered.get("session_generation") != request["session_generation"] + 1
                or sorted(recovered.get("streams", []), key=lambda r: r["stream"])
                != sorted(expected, key=lambda r: r["stream"])
            ):
                raise RecoveryFence("invalid session recovery") from None
            self.state.update(
                session_id=recovered["session_id"],
                session_generation=recovered["session_generation"],
            )
            self.state.pop("recovery")
            await self.save_state()

    async def rebind(self, raw: bytes) -> tuple[UUID, bytes]:
        """A missing old receipt allows a new envelope, never rewritten observations."""
        old = decode(raw)
        batch_id = uuid4()
        value = {
            **old,
            "batch_id": str(batch_id),
            "session_id": self.state["session_id"],
            "session_generation": self.state["session_generation"],
        }
        validate(value, "Batch")
        payload = encode(value)
        async with self.transaction() as box:
            previous = await box.batch(UUID(old["batch_id"]))
            if previous["phase"] != "staged":
                raise RecoveryFence("committed batch cannot be re-enveloped")
            await box.lock_clocks()
            clock = box.clocks[old["stream"]]
            if (
                clock["used_rows"] + 1 > clock["max_rows"]
                or clock["used_bytes"] + len(payload) > clock["max_bytes"]
            ):
                raise RecoveryFence("delivery storage capacity exhausted")
            await box.conn.execute(
                p.batches.insert().values(
                    destination_id=self.config.destination_id,
                    producer_id=self.config.producer_id,
                    batch_id=batch_id,
                    ins_code=self.config.ins_code,
                    source_epoch=UUID(old["source_epoch"]),
                    stream=old["stream"],
                    request_bytes=payload,
                    payload_sha256=hashlib.sha256(payload).hexdigest(),
                    after_position=previous["after_position"],
                    through_position=previous["through_position"],
                    simulated=False,
                )
            )
            await box.conn.execute(
                p.clocks.update()
                .where(box.scope(p.clocks, old["stream"]))
                .values(
                    used_rows=clock["used_rows"] + 1, used_bytes=clock["used_bytes"] + len(payload)
                )
            )
            self.state.setdefault("replacements", {})[old["batch_id"]] = str(batch_id)
            await box.conn.execute(
                sa.text(
                    "UPDATE sync_delivery_state SET state=CAST(:state AS jsonb) "
                    "WHERE producer_id=:id"
                ),
                {"state": json.dumps(self.state), "id": self.config.producer_id},
            )
        await self.checkpoint()
        return batch_id, payload

    async def deliver(self, stream: str) -> bool:
        async with self.transaction() as box:
            pending = (
                (
                    await box.conn.execute(
                        sa.select(p.batches)
                        .where(
                            box.scope(p.batches, stream),
                            p.batches.c.phase != "acknowledged",
                            p.batches.c.batch_id.not_in(
                                [UUID(k) for k in self.state.get("replacements", {})]
                            ),
                        )
                        .order_by(p.batches.c.after_position)
                        .limit(1)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if pending:
                batch_id, raw, phase = (
                    pending["batch_id"],
                    bytes(pending["request_bytes"]),
                    pending["phase"],
                )
                if pending["simulated"]:
                    raise RecoveryFence("simulated pending batch")
            else:
                await box.lock_clocks()
                if box.clocks[stream]["head"] == box.clocks[stream]["acknowledged"]:
                    return False
                batch_id = uuid4()
                raw = await box.stage(
                    stream,
                    batch_id=batch_id,
                    session_id=UUID(self.state["session_id"]),
                    session_generation=self.state["session_generation"],
                )
                phase = "staged"
        await self.checkpoint()
        receipt = await self.request("GET", "/tsetmc/receipts/" + str(batch_id))
        if receipt is None:
            envelope = decode(raw)
            if (envelope["session_id"], envelope["session_generation"]) != (
                self.state["session_id"],
                self.state["session_generation"],
            ):
                batch_id, raw = await self.rebind(raw)
            receipt = await self.request("POST", "/tsetmc/batches", raw)
        if receipt is None:
            raise DeliveryError("missing_receipt")
        if phase == "staged":
            async with self.transaction() as box:
                await box.receive(batch_id, receipt)
        else:
            async with self.transaction() as box:
                saved = await box.batch(batch_id)
                if saved["receipt"] != receipt:
                    raise RecoveryFence("company receipt diverged")
        async with self.transaction() as box:
            await box.acknowledge(batch_id)
        await self.checkpoint()
        return True

    async def run(self, *, seconds: int = 60, drain: bool = True) -> int:
        if not 1 <= seconds <= 86400:
            raise ValueError("delivery requires a bounded 1..86400 second window")
        self.lock_key = (
            int.from_bytes(
                hashlib.sha256(str(self.config.producer_id).encode()).digest()[:4], "big"
            )
            & 0x7FFFFFFF
        )
        self.anchor = (
            decode(self.config.anchor_file.read_bytes()) if self.config.anchor_file.exists() else {}
        )
        delivered = 0
        try:
            async with self.db.engine.connect() as owner:
                acquired = await owner.scalar(
                    sa.text("SELECT pg_try_advisory_lock(81484,:key)"), {"key": self.lock_key}
                )
                if not acquired:
                    raise RecoveryFence("producer already owned")
                pid = await owner.scalar(sa.text("SELECT pg_backend_pid()"))
                await owner.commit()
                try:
                    async with owner.begin():
                        await owner.execute(
                            sa.text("""INSERT INTO
                              sync_delivery_state(producer_id,destination_id,owner_token,backend_pid)
                          VALUES(:p,:d,:o,:pid) ON CONFLICT(producer_id) DO UPDATE SET
                            owner_token=EXCLUDED.owner_token,backend_pid=EXCLUDED.backend_pid"""),
                            {
                                "p": self.config.producer_id,
                                "d": self.config.destination_id,
                                "o": self.owner_token,
                                "pid": pid,
                            },
                        )
                        row = (
                            (
                                await owner.execute(
                                    sa.text(
                                        "SELECT * FROM sync_delivery_state WHERE producer_id=:p"
                                    ),
                                    {"p": self.config.producer_id},
                                )
                            )
                            .mappings()
                            .one()
                        )
                        if row["destination_id"] != self.config.destination_id:
                            raise RecoveryFence("coordinator destination mismatch")
                        self.state = row["state"] or dict(
                            session_id=str(self.config.session_id),
                            session_generation=self.config.session_generation,
                        )
                    await self.checkpoint()
                    # Existing ACKs are never trusted after a destination restore without receipts.
                    for batch_id in self.anchor["staged"]:
                        receipt = await self.request("GET", "/tsetmc/receipts/" + batch_id)
                        if receipt is None:
                            async with self.transaction() as box:
                                saved = await box.batch(UUID(batch_id))
                                if saved["phase"] != "staged":
                                    raise RecoveryFence("company lost previously committed receipt")
                        elif receipt.get("payload_sha256") != self.anchor["staged"][
                            batch_id
                        ] or receipt.get("destination_id") != str(self.config.destination_id):
                            raise RecoveryFence("company continuity mismatch")
                    deadline = asyncio.get_running_loop().time() + seconds
                    backoff = 2
                    while asyncio.get_running_loop().time() < deadline:
                        try:
                            await self.session()
                            progress = False
                            for stream in (
                                "tsetmc_current",
                                "tsetmc_daily",
                                "tsetmc_coverage",
                                "tsetmc_status",
                            ):
                                progress |= await self.deliver(stream)
                            delivered += int(progress)
                            backoff = 2
                            if not progress:
                                if drain:
                                    break
                                await asyncio.sleep(
                                    min(5, max(0, deadline - asyncio.get_running_loop().time()))
                                )
                        except OwnershipError:
                            await asyncio.sleep(
                                min(2, max(0, deadline - asyncio.get_running_loop().time()))
                            )
                        except DeliveryError as error:
                            if not error.retryable:
                                raise
                            await asyncio.sleep(
                                min(backoff, max(0, deadline - asyncio.get_running_loop().time()))
                            )
                            backoff = min(backoff * 2, 30)
                finally:
                    if not owner.invalidated:
                        await owner.execute(
                            sa.text("SELECT pg_advisory_unlock(81484,:key)"), {"key": self.lock_key}
                        )
                        await owner.commit()
        finally:
            await self.http.aclose()
        return delivered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--drain", action="store_true", help="exit when current backlog is empty")
    parser.add_argument("--activate", action="store_true", required=True)
    args = parser.parse_args()

    async def run() -> None:
        db = Database(DatabaseSettings.from_env())
        try:
            count = await Worker(db, DeliveryConfig.load(args.config)).run(
                seconds=args.seconds, drain=args.drain
            )
            print(json.dumps({"delivery_rounds": count}))
        finally:
            await db.aclose()

    try:
        asyncio.run(run())
        return 0
    except Exception as error:
        # Database/HTTP exception text can contain private connection details.
        print(json.dumps({"error": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
