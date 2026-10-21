"""Source-only transactional publication. No HTTP, tokens or company connections."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from tsetmc_marketdata.models.current import CurrentPrice
from tsetmc_marketdata.storage import schema_v1 as t
from tsetmc_marketdata.storage import schema_v3a as s
from tsetmc_marketdata.storage import schema_v3b1 as p
from tsetmc_marketdata.storage.config import StorageError
from tsetmc_marketdata.storage.database import fence
from tsetmc_marketdata.storage.ordering import choose_latest
from tsetmc_marketdata.storage.publication_wire import (
    UNITS,
    decode,
    encode,
    identity,
    instant,
    record_sha,
    sha,
    validate,
)
from tsetmc_marketdata.storage.serialization import decimal_text

if TYPE_CHECKING:
    from tsetmc_marketdata.storage.repository import Repository


class PublicationError(StorageError):
    category = "source_publication_failure"


class CapacityError(PublicationError):
    category = "source_outbox_capacity"


class RecoveryFence(PublicationError):
    category = "source_sync_recovery_fenced"


class SourceOutbox:
    """All mutations require an explicit Repository.atomic and its session fence.

    Staging/receipt/ACK methods are LOCAL SIMULATION primitives. A future worker
    needs its own coordinator/instrument fences and trusted network receipt path.
    """

    def __init__(self, repo: Repository) -> None:
        self.repo, self.conn, self.code = repo, repo.conn, repo.ins_code
        self.dataset: dict[str, Any] | None = None
        self.clocks: dict[str, dict[str, Any]] = {}
        self.sources: dict[int, dict[str, Any]] = {}
        self.pinned: set[int] = set()
        self.snapshot_ids: dict[int, int] = {}
        self.created_bytes = 0
        self.created_rows = 0

    def scope(self, table: sa.Table, stream: str | None = None) -> Any:
        assert self.dataset is not None
        parts = [
            table.c.ins_code == self.code,
            table.c.source_epoch == self.dataset["source_epoch"],
        ]
        if stream is not None:
            parts.append(table.c.stream == stream)
        return sa.and_(*parts)

    async def load(self, *, required: bool = True) -> bool:
        await fence(self.conn, self.code)
        value = (
            (
                await self.conn.execute(
                    sa.select(p.datasets).where(p.datasets.c.ins_code == self.code)
                )
            )
            .mappings()
            .one_or_none()
        )
        self.dataset = dict(value) if value else None
        if not value or not value["enabled"]:
            if required:
                raise PublicationError("local source publication is disabled")
            return False
        return True

    async def lock_clocks(self) -> None:
        rows = (
            (
                await self.conn.execute(
                    sa.select(p.clocks)
                    .where(self.scope(p.clocks))
                    .order_by(p.clocks.c.stream)
                    .with_for_update()
                )
            )
            .mappings()
            .all()
        )
        if {r["stream"] for r in rows} != set(p.STREAMS):
            raise PublicationError("source stream clocks are incomplete")
        self.clocks = {r["stream"]: dict(r) for r in rows}

    async def configure(
        self,
        *,
        source_epoch: UUID,
        installation_id: UUID,
        destination_id: UUID,
        producer_id: UUID,
        ownership_generation: int = 1,
        max_rows: int = 1_000_000,
        max_bytes: int = 1_073_741_824,
    ) -> None:
        """Administrator-only immutable local binding; creates NO enabled stream."""
        await fence(self.conn, self.code)
        if type(ownership_generation) is not int or not 0 < ownership_generation < 2**63:
            raise ValueError("invalid ownership generation")
        if max_rows < 1 or max_bytes < 1:
            raise ValueError("positive publication budgets required")
        values = dict(
            ins_code=self.code,
            source_epoch=source_epoch,
            installation_id=installation_id,
            destination_id=destination_id,
            producer_id=producer_id,
            ownership_generation=ownership_generation,
        )
        prior = (
            (
                await self.conn.execute(
                    sa.select(p.datasets).where(p.datasets.c.ins_code == self.code)
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior:
            if any(prior[k] != v for k, v in values.items()):
                raise RecoveryFence("dataset binding already exists; no implicit epoch rotation")
            return
        await self.conn.execute(p.datasets.insert().values(**values))
        for stream in p.STREAMS:
            await self.conn.execute(
                p.clocks.insert().values(
                    ins_code=self.code,
                    source_epoch=source_epoch,
                    stream=stream,
                    max_rows=max_rows,
                    max_bytes=max_bytes,
                )
            )

    async def source(self, observation_id: int, snapshot_id: int | None = None) -> dict[str, Any]:
        if observation_id not in self.sources:
            row = (
                (
                    await self.conn.execute(
                        sa.select(
                            t.observations.c.observation_id,
                            t.observations.c.raw_sha256,
                            t.observations.c.endpoint,
                            t.observations.c.received_at,
                        ).where(
                            t.observations.c.ins_code == self.code,
                            t.observations.c.observation_id == observation_id,
                        )
                    )
                )
                .mappings()
                .one()
            )
            # Retain only a relative public endpoint, never a configured host/query/header.
            endpoint = row["endpoint"]
            if not endpoint.startswith(("ClosingPrice/", "Instrument/")) or any(
                c in endpoint for c in "?#\\\r\n"
            ):
                raise PublicationError("source endpoint is not a safe relative path")
            if not row["raw_sha256"]:
                raise PublicationError("accepted source lacks evidence hash")
            self.sources[observation_id] = {
                "local_observation_id": str(observation_id),
                "raw_sha256": row["raw_sha256"],
                "endpoint": endpoint,
                "received_at": instant(row["received_at"]),
            }
        if snapshot_id is not None:
            self.snapshot_ids[observation_id] = snapshot_id
        return self.sources[observation_id]

    async def protect(self, value: Any) -> None:
        if isinstance(value, list):
            for child in value:
                await self.protect(child)
        if not isinstance(value, dict):
            return
        if "local_observation_id" in value and "raw_sha256" in value:
            observation_id = int(value["local_observation_id"])
            if observation_id not in self.pinned:
                assert self.dataset is not None
                await self.conn.execute(
                    insert(p.evidence)
                    .values(
                        ins_code=self.code,
                        source_epoch=self.dataset["source_epoch"],
                        local_observation_id=observation_id,
                        snapshot_id=self.snapshot_ids.get(observation_id),
                    )
                    .on_conflict_do_nothing()
                )
                self.pinned.add(observation_id)
        for child in value.values():
            await self.protect(child)

    async def base_identity(self) -> dict[str, Any]:
        source_id = await self.conn.scalar(
            sa.select(t.instruments.c.instrument_id).where(t.instruments.c.ins_code == self.code)
        )
        return identity(self.code, source_id)

    @staticmethod
    def measurements(row: Any) -> dict[str, str | None]:
        return {
            k: (
                None
                if row[k] is None
                else str(int(row[k]))
                if k == "trade_count"
                else decimal_text(row[k])
            )
            for k in t.MEASUREMENTS
        }

    async def revision(self, row: Any) -> dict[str, Any]:
        def values(state: dict[str, Any]) -> dict[str, Any]:
            return {k: str(state[k]) if state[k] is not None else None for k in t.MEASUREMENTS}

        return {
            "local_revision_id": str(row["revision_id"]),
            "financial_revision": str(row["revision"]),
            "old_financial_hash": row["old_hash"],
            "new_financial_hash": row["new_hash"],
            "old_measurements": values(row["old_state"]),
            "new_measurements": values(row["new_state"]),
            "old_source": await self.source(row["old_observation_id"]),
            "new_source": await self.source(row["new_observation_id"]),
            "discovered_at": instant(row["discovered_at"]),
        }

    async def daily_state(self, row: Any, now: datetime) -> dict[str, Any]:
        day = row["trading_date"]
        action = "confirm" if row["finalization_state"] == "operator_finalized" else "revoke"
        review_id = self.repo.publication_reviews.get(day)
        if review_id is None:
            published = await self.conn.scalar(
                sa.select(p.heads.c.observation).where(
                    self.scope(p.heads), p.heads.c.trading_date == day
                )
            )
            if (
                published
                and published["financial_hash"] == row["financial_hash"]
                and published["review"]
                and published["review"]["action"] == action
            ):
                review_id = UUID(published["review"]["review_id"])
        review_filter = [
            s.reviews.c.ins_code == self.code,
            s.reviews.c.trading_date == day,
            s.reviews.c.financial_hash == row["financial_hash"],
            s.reviews.c.action == action,
        ]
        if review_id is not None:
            review_filter.append(s.reviews.c.review_id == review_id)
        review = (
            (
                await self.conn.execute(
                    sa.select(s.reviews)
                    .where(
                        *review_filter,
                    )
                    .order_by(s.reviews.c.reviewed_at.desc(), s.reviews.c.review_id.desc())
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        summary = None
        if review:
            ids = (
                [
                    str(review[k])
                    for k in ("first_observation_id", "second_observation_id")
                    if review[k] is not None
                ]
                if review["action"] == "confirm"
                else []
            )
            for evidence_id in ids:
                await self.source(int(evidence_id))
            summary = {
                "review_id": str(review["review_id"]),
                "action": review["action"],
                "policy": "operator_review_v1",
                "reviewed_financial_hash": review["financial_hash"],
                "reviewed_at": instant(review["reviewed_at"]),
                "evidence_observation_ids": ids,
                "policy_evidence_sha256": sha(
                    {
                        k: str(review[k])
                        for k in (
                            "session_end",
                            "session_evidence",
                            "grace_seconds",
                            "first_observation_id",
                            "second_observation_id",
                        )
                    }
                ),
            }
        count = await self.conn.scalar(
            sa.select(sa.func.count())
            .select_from(t.quarantine)
            .where(
                t.quarantine.c.ins_code == self.code,
                t.quarantine.c.trading_date == day,
                t.quarantine.c.record_kind == "daily",
                t.quarantine.c.status == "open",
            )
        )
        decision = (
            (
                await self.conn.execute(
                    sa.select(t.decisions)
                    .where(t.decisions.c.ins_code == self.code, t.decisions.c.trading_date == day)
                    .order_by(t.decisions.c.decision_id.desc())
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        rev = (
            (
                await self.conn.execute(
                    sa.select(t.revisions).where(
                        t.revisions.c.ins_code == self.code,
                        t.revisions.c.trading_date == day,
                        t.revisions.c.revision == row["revision"],
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        raw = row["raw_row"]
        return {
            **await self.base_identity(),
            "trading_date": day.isoformat(),
            "measurements": self.measurements(row),
            "units": dict(UNITS),
            "delivery_status": "unknown",
            "financial_revision": str(row["revision"]),
            "state_version": "1",
            "financial_hash": row["financial_hash"],
            "source_fields": {
                k: str(raw[k]) if raw.get(k) is not None else None
                for k in ("dEven", "hEven", "lastHEven", "finalLastDate")
            },
            "source": await self.source(row["observation_id"]),
            "acceptance": row["acceptance"],
            "upstream_finality": "unverified",
            "local_finalization": row["finalization_state"],
            "publication_state": "provisional"
            if day >= now.astimezone(ZoneInfo("Asia/Tehran")).date()
            else "unverified_history",
            "reconciliation": {
                "status": "unresolved_conflict"
                if count
                else "accepted_repair"
                if decision and decision["accepted"] and row["revision"] > 1
                else "agrees"
                if row["acceptance"] == "reconciled"
                else "not_checked",
                "local_decision_id": str(decision["decision_id"]) if decision else None,
                "open_quarantine_count": count,
            },
            "review": summary,
            "revision_evidence": await self.revision(rev) if rev else None,
        }

    @staticmethod
    def daily_semantic(o: dict[str, Any]) -> str:
        # Raw-only verification/provenance and repeated reconciliation IDs are not public changes.
        return sha(
            {
                k: o[k]
                for k in (
                    "financial_hash",
                    "financial_revision",
                    "acceptance",
                    "local_finalization",
                    "review",
                )
            }
            | {"quality": {k: o["reconciliation"][k] for k in ("status", "open_quarantine_count")}}
        )

    async def append(
        self,
        stream: str,
        kind: str,
        event_type: str,
        observation: dict[str, Any],
        *,
        semantic: str | None = None,
    ) -> dict[str, Any]:
        assert self.dataset is not None
        if observation["ins_code"] != self.code:
            raise PublicationError("publication belongs to another instrument")
        clock = self.clocks[stream]
        position = clock["head"] + 1
        if position >= 2**63:
            raise CapacityError("source position exhausted")
        if kind == "current":
            observation["state_version"] = str(position)
        record: dict[str, Any] = {
            "observation_id": str(uuid5(self.dataset["source_epoch"], f"{stream}:{position}")),
            "source_position": str(position),
            "kind": kind,
            "event_type": event_type,
            "observation": observation,
        }
        definition = {
            "daily": "DailyRecord",
            "daily_revision": "RevisionRecord",
            "current": "CurrentRecord",
            "coverage": "CoverageRecord",
            "status": "StatusRecord",
        }[kind]
        validate(record, definition)
        await self.protect(observation)
        body = encode(record)
        if (
            clock["used_rows"] + 1 > clock["max_rows"]
            or clock["used_bytes"] + len(body) > clock["max_bytes"]
        ):
            raise CapacityError(
                "publication storage budget exhausted; canonical transaction rolled back"
            )
        clock.update(
            head=position,
            used_rows=clock["used_rows"] + 1,
            used_bytes=clock["used_bytes"] + len(body),
        )
        await self.conn.execute(
            p.clocks.update()
            .where(self.scope(p.clocks, stream))
            .values(head=position, used_rows=clock["used_rows"], used_bytes=clock["used_bytes"])
        )
        values = dict(
            ins_code=self.code,
            source_epoch=self.dataset["source_epoch"],
            stream=stream,
            observation_id=UUID(record["observation_id"]),
            record=record,
            record_bytes=body,
            record_sha256=record_sha(record),
        )
        if stream in {"tsetmc_daily", "tsetmc_coverage"}:
            await self.conn.execute(
                p.outbox.insert().values(
                    **values, source_position=position, created_at=datetime.now(UTC)
                )
            )
        else:
            await self.conn.execute(
                insert(p.latest)
                .values(**values, version=position, semantic_sha256=semantic or sha(observation))
                .on_conflict_do_update(
                    index_elements=[
                        p.latest.c.ins_code,
                        p.latest.c.source_epoch,
                        p.latest.c.stream,
                    ],
                    set_={
                        **values,
                        "version": position,
                        "semantic_sha256": semantic or sha(observation),
                    },
                )
            )
        self.created_bytes += len(body)
        self.created_rows += 1
        return record

    async def publish_day(self, row: Any, now: datetime, *, seed: bool = False) -> bool:
        assert self.dataset is not None
        observation = await self.daily_state(row, now)
        where = sa.and_(self.scope(p.heads), p.heads.c.trading_date == row["trading_date"])
        old = (
            (await self.conn.execute(sa.select(p.heads).where(where).with_for_update()))
            .mappings()
            .one_or_none()
        )
        semantic = self.daily_semantic(observation)
        if old and old["semantic_sha256"] == semantic:
            return False
        observation["state_version"] = str(old["state_version"] + 1 if old else 1)
        event = "daily.seed" if seed else "daily.accepted" if not old else "daily.quality_changed"
        if old:
            previous = old["observation"]
            if previous["financial_hash"] != observation["financial_hash"]:
                event = "daily.corrected"
                # One canonical state per date/transaction, without losing any
                # intermediate financial revisions produced inside that transaction.
                revisions = (
                    await self.conn.execute(
                        sa.select(t.revisions)
                        .where(
                            t.revisions.c.ins_code == self.code,
                            t.revisions.c.trading_date == row["trading_date"],
                            t.revisions.c.revision > int(previous["financial_revision"]),
                            t.revisions.c.revision < row["revision"],
                        )
                        .order_by(t.revisions.c.revision)
                    )
                ).mappings()
                for revision in revisions:
                    await self.append(
                        "tsetmc_daily",
                        "daily_revision",
                        "daily.revision_seed",
                        {
                            **await self.base_identity(),
                            "trading_date": row["trading_date"].isoformat(),
                            "seed_id": str(self.dataset["seed_id"]),
                            "revision_evidence": await self.revision(revision),
                        },
                    )
            elif previous["review"] != observation["review"] and observation["review"]:
                event = (
                    "daily.review_confirmed"
                    if observation["review"]["action"] == "confirm"
                    else "daily.review_revoked"
                )
            elif previous["acceptance"] != observation["acceptance"]:
                event = "daily.reconciled"
        await self.append("tsetmc_daily", "daily", event, observation)
        values = dict(
            ins_code=self.code,
            source_epoch=self.dataset["source_epoch"],
            trading_date=row["trading_date"],
            state_version=int(observation["state_version"]),
            semantic_sha256=semantic,
            observation=observation,
        )
        await self.conn.execute(
            insert(p.heads)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[p.heads.c.ins_code, p.heads.c.source_epoch, p.heads.c.trading_date],
                set_=values,
            )
        )
        return True

    async def coverage(self, days: set[date], now: datetime) -> None:
        rows = (
            (
                await self.conn.execute(
                    sa.select(t.coverage, t.daily.c.financial_hash, t.daily.c.finalization_state)
                    .outerjoin(
                        t.daily,
                        sa.and_(
                            t.daily.c.ins_code == t.coverage.c.ins_code,
                            t.daily.c.trading_date == t.coverage.c.trading_date,
                        ),
                    )
                    .where(t.coverage.c.ins_code == self.code, t.coverage.c.trading_date.in_(days))
                    .order_by(t.coverage.c.trading_date)
                )
            )
            .mappings()
            .all()
        )
        for start in range(0, len(rows), 100):
            page = rows[start : start + 100]
            observation = {
                **await self.base_identity(),
                "captured_at": instant(now),
                "from_date": page[0]["trading_date"].isoformat(),
                "through_date": page[-1]["trading_date"].isoformat(),
                "range_scope": "observed_dates_only",
                "archive_completeness": "unproven",
                "missing_calendar_dates": "unknown",
                "coverage_rows": [
                    {
                        "trading_date": r["trading_date"].isoformat(),
                        "state": r["state"],
                        "financial_hash": r["financial_hash"],
                        "local_finalization": r["finalization_state"],
                        "upstream_finality": "unverified",
                    }
                    for r in page
                ],
            }
            await self.append("tsetmc_coverage", "coverage", "coverage.updated", observation)

    async def current(self, *, seed: bool = False, resnapshot: bool = False) -> None:
        row = (
            (
                await self.conn.execute(
                    sa.select(t.snapshots)
                    .join(t.latest, t.latest.c.snapshot_id == t.snapshots.c.snapshot_id)
                    .where(t.latest.c.ins_code == self.code)
                )
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            return
        previous = (
            (
                await self.conn.execute(
                    sa.select(p.latest).where(self.scope(p.latest, "tsetmc_current"))
                )
            )
            .mappings()
            .one_or_none()
        )
        semantic = sha({k: str(row[k]) for k in ("financial_hash", "source_date", "source_time")})
        if previous and previous["semantic_sha256"] == semantic and not resnapshot:
            return
        if row["decision"] == "repeated_state" and not (seed or resnapshot):
            return
        if previous:
            prior = previous["record"]["observation"]
            measurements: dict[str, Any] = {
                key: int(row[key]) if key == "trade_count" and row[key] is not None else row[key]
                for key in t.MEASUREMENTS
            }
            model = CurrentPrice(
                ins_code=self.code,
                **measurements,
                instrument_state=row["instrument_state"],
                instrument_state_title=row["instrument_state_title"],
                source_date=row["source_date"],
                source_time=row["source_time"],
                source_reported_at=row["source_reported_at"],
                received_at=row["received_at"],
                raw={},
            )
            comparison = choose_latest(
                {
                    "source_date": date.fromisoformat(prior["source_date"])
                    if prior["source_date"]
                    else None,
                    "source_time": time.fromisoformat(prior["source_time"])
                    if prior["source_time"]
                    else None,
                    "financial_hash": prior["financial_hash"],
                    "received_at": row["received_at"],
                },
                model,
                row["financial_hash"],
                correction_reason=row["decision_reason"],
            )
            if not comparison.update and (
                prior["financial_hash"] != row["financial_hash"]
                or comparison.code in {"older_session", "older_source_clock"}
            ):
                raise PublicationError(
                    "accepted pointer regresses published source state; review required"
                )
        raw = row["raw_row"]
        observation = {
            **await self.base_identity(),
            "local_snapshot_id": str(row["snapshot_id"]),
            "observation_semantics": "polled_snapshot",
            "new_trade_claimed": False,
            "measurements": self.measurements(row),
            "units": dict(UNITS),
            "delivery_status": "unknown",
            "state_version": "1",
            "financial_hash": row["financial_hash"],
            "source_fields": {
                k: str(raw[k]) if raw.get(k) is not None else None
                for k in ("dEven", "hEven", "lastHEven", "finalLastDate")
            },
            "source": await self.source(row["observation_id"], row["snapshot_id"]),
            "source_date": row["source_date"].isoformat() if row["source_date"] else None,
            "source_time": row["source_time"].isoformat() if row["source_time"] else None,
            "source_reported_at": instant(row["source_reported_at"]),
            "instrument_state": row["instrument_state"],
            "instrument_state_title": row["instrument_state_title"],
            "accepted_decision": row["decision"],
            "financial_change": False if seed or resnapshot else row["is_state_change"],
            "correction_reason_sha256": hashlib.sha256(row["decision_reason"].encode()).hexdigest()
            if row["decision_reason"]
            else None,
        }
        if resnapshot and previous:
            prior = previous["record"]["observation"]
            if (
                (prior["source_date"], prior["source_time"])
                == (observation["source_date"], observation["source_time"])
                and prior["financial_hash"] != observation["financial_hash"]
                and row["decision"] != "explicit_same_time_correction"
            ):
                raise PublicationError("same-clock resnapshot lacks accepted correction evidence")
        await self.append(
            "tsetmc_current",
            "current",
            "current.resnapshot" if resnapshot else "current.seed" if seed else "current.updated",
            observation,
            semantic=semantic,
        )

    async def status(self, now: datetime) -> None:
        runtime = (
            (await self.conn.execute(sa.select(s.runtime).where(s.runtime.c.ins_code == self.code)))
            .mappings()
            .one_or_none()
        )
        http = await self.conn.scalar(
            sa.select(sa.func.max(t.observations.c.received_at)).where(
                t.observations.c.ins_code == self.code,
                t.observations.c.http_status.between(200, 299),
            )
        )
        last_status = (
            (
                await self.conn.execute(
                    sa.select(t.status)
                    .where(t.status.c.ins_code == self.code)
                    .order_by(t.status.c.last_attempt_at.desc())
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        failure = last_status["failure_category"] if last_status else None
        if runtime and runtime["failure_category"]:
            failure = runtime["failure_category"]
        process = runtime["state"] if runtime else "never_started"
        if runtime and process == "running":
            live = await self.conn.scalar(
                sa.text("""SELECT EXISTS(SELECT 1 FROM pg_stat_activity
                WHERE pid=:pid AND backend_start=:started)"""),
                {"pid": runtime["owner_backend_pid"], "started": runtime["owner_backend_start"]},
            )
            if not live:
                process = "interrupted_owner_absent"
        # collection_runs.ended_at is recorded before commit, not an actual PG
        # commit instant. Keep this unknown rather than relabeling that clock.
        current = (
            (
                await self.conn.execute(
                    sa.select(t.snapshots)
                    .join(t.latest, t.latest.c.snapshot_id == t.snapshots.c.snapshot_id)
                    .where(t.latest.c.ins_code == self.code)
                )
            )
            .mappings()
            .one_or_none()
        )
        revision_count = await self.conn.scalar(
            sa.select(sa.func.count())
            .select_from(t.revisions)
            .where(t.revisions.c.ins_code == self.code)
        )
        open_count = await self.conn.scalar(
            sa.select(sa.func.count())
            .select_from(t.quarantine)
            .where(t.quarantine.c.ins_code == self.code, t.quarantine.c.status == "open")
        )
        observation = {
            **await self.base_identity(),
            "captured_at": instant(now),
            "expires_at": instant(now + timedelta(seconds=60)),
            "process_state": process,
            "source_availability": "latest_request_failed"
            if failure
            else "http_observed"
            if http
            else "unknown",
            "last_successful_http_at": instant(http),
            "last_database_commit_at": None,
            "accepted_source_at": instant(current["source_reported_at"]) if current else None,
            "last_financial_change_at": instant(runtime["last_financial_change_at"])
            if runtime
            else None,
            "session": {
                "expectation": runtime["session_expectation"] if runtime else "UNKNOWN",
                "confidence": runtime["session_confidence"] if runtime else "unqualified",
                "provenance_sha256": sha(runtime["session_provenance"])
                if runtime and runtime["session_provenance"]
                else None,
                "valid_until": instant(runtime["session_valid_until"]) if runtime else instant(now),
            },
            "latest_failure_category": failure,
            "open_quarantine_count": open_count,
            "historical_revision_count": revision_count,
        }
        await self.append("tsetmc_status", "status", "status.updated", observation)

    async def flush(self, days: set[date], current: bool, status: bool) -> None:
        if not (days or current or status) or not await self.load(required=False):
            return
        rows = (
            (
                await self.conn.execute(
                    sa.select(t.daily)
                    .where(t.daily.c.ins_code == self.code, t.daily.c.trading_date.in_(days))
                    .order_by(t.daily.c.trading_date)
                    .with_for_update()
                )
            )
            .mappings()
            .all()
        )
        # Canonical rows precede daily-head and lexical stream locks. Same instrument
        # publishers already hold the existing exclusive collector session fence.
        if days:
            await self.conn.execute(
                sa.select(p.heads)
                .where(self.scope(p.heads), p.heads.c.trading_date.in_(days))
                .order_by(p.heads.c.trading_date)
                .with_for_update()
            )
        await self.lock_clocks()
        now = datetime.now(UTC)
        changed: set[date] = set()
        for row in rows:
            if await self.publish_day(row, now):
                changed.add(row["trading_date"])
        # New invalid-only dates have no daily head, but still require coverage.
        changed |= days - {r["trading_date"] for r in rows}
        if changed:
            await self.coverage(changed, now)
        if current:
            await self.current()
        if status or current or changed:
            await self.status(now)

    async def enroll(
        self,
        *,
        seed_id: UUID,
        allow_local_publication: bool = False,
        max_daily_rows: int = 10_000,
        max_bytes: int = 32 * 1024 * 1024,
    ) -> dict[str, Any]:
        """Explicit source-only seed; caller owns the instrument and transaction."""
        if (
            not allow_local_publication
            or not 0 <= max_daily_rows <= 10_000
            or not 0 < max_bytes <= 32 * 1024 * 1024
        ):
            raise ValueError("explicit bounded local-publication consent required")
        await fence(self.conn, self.code)
        self.dataset = dict(
            (
                await self.conn.execute(
                    sa.select(p.datasets)
                    .where(p.datasets.c.ins_code == self.code)
                    .with_for_update()
                )
            )
            .mappings()
            .one()
        )
        if self.dataset["enrolled"]:
            if self.dataset["seed_id"] != seed_id:
                raise RecoveryFence("dataset already enrolled; preserve identity")
            return {"replayed": True, "network_delivery": False}
        rows = (
            (
                await self.conn.execute(
                    sa.select(t.daily)
                    .where(t.daily.c.ins_code == self.code)
                    .order_by(t.daily.c.trading_date)
                    .limit(max_daily_rows + 1)
                    .with_for_update()
                )
            )
            .mappings()
            .all()
        )
        if len(rows) > max_daily_rows:
            raise CapacityError("seed row limit exceeded; nothing enrolled")
        await self.lock_clocks()
        revisions = (
            await self.conn.execute(
                sa.select(t.revisions)
                .where(t.revisions.c.ins_code == self.code)
                .order_by(t.revisions.c.trading_date, t.revisions.c.revision)
            )
        ).mappings()
        for revision in revisions:
            await self.append(
                "tsetmc_daily",
                "daily_revision",
                "daily.revision_seed",
                {
                    **await self.base_identity(),
                    "trading_date": revision["trading_date"].isoformat(),
                    "seed_id": str(seed_id),
                    "revision_evidence": await self.revision(revision),
                },
            )
            if self.created_bytes > max_bytes:
                raise CapacityError("seed byte limit exceeded; nothing enrolled")
        now = datetime.now(UTC)
        for row in rows:
            await self.publish_day(row, now, seed=True)
            if self.created_bytes > max_bytes:
                raise CapacityError("seed byte limit exceeded; nothing enrolled")
        days = set(
            await self.conn.scalars(
                sa.select(t.coverage.c.trading_date).where(t.coverage.c.ins_code == self.code)
            )
        )
        await self.coverage(days, now)
        await self.current(seed=True)
        if self.created_bytes > max_bytes:
            raise CapacityError("seed byte limit exceeded; nothing enrolled")
        await self.conn.execute(
            p.datasets.update()
            .where(p.datasets.c.ins_code == self.code)
            .values(enabled=True, enrolled=True, seed_id=seed_id)
        )
        return {
            "daily_records": len(rows),
            "publication_records": self.created_rows,
            "serialized_bytes": self.created_bytes,
            "network_delivery": False,
            "archive_completeness": "unproven",
        }

    async def stage(
        self,
        stream: str,
        *,
        batch_id: UUID,
        session_id: UUID,
        session_generation: int,
        simulate: bool = False,
        limit: int = 100,
    ) -> bytes:
        if (
            not simulate and not self.conn.info.get("authenticated_delivery")
        ) or not 1 <= limit <= 100:
            raise ValueError("bounded simulation or fenced delivery context required")
        await self.load()
        assert self.dataset is not None
        prior = await self.conn.scalar(
            sa.select(p.batches.c.request_bytes).where(
                p.batches.c.batch_id == batch_id, self.scope(p.batches, stream)
            )
        )
        if prior is not None:
            body = bytes(prior)
            value = decode(body)
            if (
                value["session_id"] != str(session_id)
                or value["session_generation"] != session_generation
            ):
                raise RecoveryFence("staged batch identity is immutable")
            return body
        await self.lock_clocks()
        clock = self.clocks[stream]
        after = clock["acknowledged"]
        if stream in {"tsetmc_daily", "tsetmc_coverage"}:
            selected = list(
                await self.conn.scalars(
                    sa.select(p.outbox.c.record)
                    .where(self.scope(p.outbox, stream), p.outbox.c.source_position > after)
                    .order_by(p.outbox.c.source_position)
                    .limit(limit if stream == "tsetmc_daily" else 1)
                )
            )
            if selected and [int(r["source_position"]) for r in selected] != list(
                range(after + 1, after + len(selected) + 1)
            ):
                raise RecoveryFence("lossless source prefix is missing")
        else:
            head = (
                (await self.conn.execute(sa.select(p.latest).where(self.scope(p.latest, stream))))
                .mappings()
                .one_or_none()
            )
            selected = (
                [head["record"]] if head and head["version"] > head["acknowledged_version"] else []
            )
        if not selected and clock["head"] > after:
            raise RecoveryFence("committed pending source state is missing")
        if not selected:
            raise PublicationError("no committed pending records")
        envelope = {
            "protocol_version": 1,
            "contract_version": "tsetmc.v1",
            "producer_id": str(self.dataset["producer_id"]),
            "session_id": str(session_id),
            "session_generation": session_generation,
            "source_epoch": str(self.dataset["source_epoch"]),
            "batch_id": str(batch_id),
            "instrument_id": identity(self.code, None)["instrument_id"],
            "ownership_generation": self.dataset["ownership_generation"],
            "stream": stream,
            "records": selected,
        }
        while True:
            body = encode(envelope)
            if len(body) <= 512 * 1024:
                break
            if len(envelope["records"]) == 1:
                if len(body) > 2 * 1024 * 1024:
                    raise CapacityError("single publication exceeds hard batch byte limit")
                break
            envelope["records"].pop()
        validate(envelope, "Batch")
        # Staged BYTEA also consumes the conservative retained-evidence budget.
        if (
            clock["used_rows"] + 1 > clock["max_rows"]
            or clock["used_bytes"] + len(body) > clock["max_bytes"]
        ):
            raise CapacityError("staged publication storage budget exhausted")
        await self.conn.execute(
            p.clocks.update()
            .where(self.scope(p.clocks, stream))
            .values(used_rows=clock["used_rows"] + 1, used_bytes=clock["used_bytes"] + len(body))
        )
        through = int(envelope["records"][-1]["source_position"])
        await self.conn.execute(
            p.batches.insert().values(
                destination_id=self.dataset["destination_id"],
                producer_id=self.dataset["producer_id"],
                batch_id=batch_id,
                ins_code=self.code,
                source_epoch=self.dataset["source_epoch"],
                stream=stream,
                request_bytes=body,
                payload_sha256=hashlib.sha256(body).hexdigest(),
                after_position=after,
                through_position=through,
                simulated=simulate,
            )
        )
        return body

    async def batch(self, batch_id: UUID) -> dict[str, Any]:
        await self.load()
        row = (
            (
                await self.conn.execute(
                    sa.select(p.batches)
                    .where(self.scope(p.batches), p.batches.c.batch_id == batch_id)
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            raise PublicationError("batch absent from this instrument/dataset")
        return dict(row)

    async def receive(
        self, batch_id: UUID, receipt: dict[str, Any], *, simulate: bool = False
    ) -> None:
        if not simulate and not self.conn.info.get("authenticated_delivery"):
            raise ValueError("simulation or fenced delivery context required")
        row = await self.batch(batch_id)
        if row["simulated"] != simulate:
            raise PublicationError("cannot mix simulated and authenticated delivery")
        request = decode(bytes(row["request_bytes"]))
        validate(receipt, "Receipt")
        for key in (
            "producer_id",
            "source_epoch",
            "batch_id",
            "instrument_id",
            "ownership_generation",
            "stream",
        ):
            if receipt[key] != request[key]:
                raise PublicationError("receipt batch binding mismatch")
        if (
            receipt["destination_id"] != str(row["destination_id"])
            or receipt["payload_sha256"] != row["payload_sha256"]
        ):
            raise PublicationError("receipt destination/payload mismatch")
        results = {r["observation_id"]: r for r in receipt["records"]}
        if len(results) != len(receipt["records"]) or set(results) != {
            r["observation_id"] for r in request["records"]
        }:
            raise PublicationError("receipt record identities mismatch")
        counts = {k: 0 for k in receipt["counts"]}
        for record in request["records"]:
            result = results[record["observation_id"]]
            if result["source_position"] != record["source_position"] or result[
                "record_sha256"
            ] != record_sha(record):
                raise PublicationError("receipt record hash/position mismatch")
            state = record["observation"]
            if (
                state.get("state_version") is not None
                and result["stored_state_version"] != state["state_version"]
            ):
                raise RecoveryFence("receipt state barrier differs; reconciliation required")
            if (
                state.get("financial_hash") is not None
                and result["stored_financial_hash"] != state["financial_hash"]
            ):
                raise RecoveryFence("receipt financial state differs; reconciliation required")
            counts[result["outcome"]] += 1
        if counts != receipt["counts"]:
            raise PublicationError("receipt outcome counts mismatch")
        if row["receipt"] is not None:
            if row["receipt"] != receipt:
                raise PublicationError("saved receipt is immutable")
            return
        await self.conn.execute(
            p.batches.update()
            .where(self.scope(p.batches), p.batches.c.batch_id == batch_id)
            .values(phase="received", receipt=receipt)
        )

    async def acknowledge(self, batch_id: UUID, *, simulate: bool = False) -> None:
        if not simulate and not self.conn.info.get("authenticated_delivery"):
            raise ValueError("simulation or fenced delivery context required")
        row = await self.batch(batch_id)
        if row["simulated"] != simulate:
            raise PublicationError("cannot mix simulated and authenticated delivery")
        if row["phase"] == "acknowledged":
            return
        if row["phase"] != "received":
            raise PublicationError("durable validated receipt required before ACK")
        await self.lock_clocks()
        stream = row["stream"]
        clock = self.clocks[stream]
        if row["through_position"] > clock["head"]:
            raise RecoveryFence("batch is ahead of durable local head")
        if (
            stream in {"tsetmc_daily", "tsetmc_coverage"}
            and row["after_position"] > clock["acknowledged"]
        ):
            raise RecoveryFence("ACK cannot skip an unconfirmed prefix")
        acknowledged = max(clock["acknowledged"], row["through_position"])
        await self.conn.execute(
            p.clocks.update().where(self.scope(p.clocks, stream)).values(acknowledged=acknowledged)
        )
        if stream in {"tsetmc_current", "tsetmc_status"}:
            record = decode(bytes(row["request_bytes"]))["records"][0]
            head = (
                (
                    await self.conn.execute(
                        sa.select(p.latest).where(self.scope(p.latest, stream)).with_for_update()
                    )
                )
                .mappings()
                .one()
            )
            if head["version"] == row["through_position"] and (
                head["observation_id"] != UUID(record["observation_id"])
                or head["record_sha256"] != record_sha(record)
            ):
                raise RecoveryFence("latest ACK identity mismatch")
            await self.conn.execute(
                p.latest.update()
                .where(self.scope(p.latest, stream))
                .values(
                    acknowledged_version=max(head["acknowledged_version"], row["through_position"])
                )
            )
        await self.conn.execute(
            p.batches.update()
            .where(self.scope(p.batches), p.batches.c.batch_id == batch_id)
            .values(phase="acknowledged")
        )

    async def continuity(self, proof: dict[str, Any]) -> None:
        """Compare externally supplied proof only; anchor storage/auth is Stage 4."""
        await self.load()
        assert self.dataset is not None
        if any(
            str(self.dataset[k]) != proof.get(k)
            for k in ("source_epoch", "installation_id", "destination_id", "producer_id")
        ):
            raise RecoveryFence("continuity binding mismatch")
        await self.lock_clocks()
        for stream, barrier in proof["streams"].items():
            clock = self.clocks[stream]
            if barrier["head"] > clock["head"] or barrier["acknowledged"] > clock["acknowledged"]:
                raise RecoveryFence("restored local state is behind proven continuity evidence")
        for batch_id, digest in proof.get("staged", {}).items():
            try:
                row = await self.batch(UUID(batch_id))
            except PublicationError:
                raise RecoveryFence("restored source lacks proven staged batch") from None
            if row["payload_sha256"] != digest:
                raise RecoveryFence("staged continuity proof mismatch")

    async def health(self) -> dict[str, Any]:
        if not await self.load(required=False):
            return {"enabled": False, "network_delivery": False}
        rows = (
            (await self.conn.execute(sa.select(p.clocks).where(self.scope(p.clocks))))
            .mappings()
            .all()
        )
        return {
            "enabled": True,
            "network_delivery": False,
            "streams": [
                {
                    "stream": r["stream"],
                    "head": r["head"],
                    "acknowledged": r["acknowledged"],
                    "used_rows": r["used_rows"],
                    "used_bytes": r["used_bytes"],
                    "capacity": "critical"
                    if max(r["used_rows"] / r["max_rows"], r["used_bytes"] / r["max_bytes"]) >= 0.85
                    else "warning"
                    if max(r["used_rows"] / r["max_rows"], r["used_bytes"] / r["max_bytes"]) >= 0.7
                    else "ok",
                }
                for r in rows
            ],
        }
