"""Instrument-owned durable slots; committed collection runs are the recovery authority."""

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from tsetmc_marketdata.collection.service_config import ScheduledJob, ServiceConfig
from tsetmc_marketdata.collection.sessions import SessionDecision
from tsetmc_marketdata.storage import schema_v1 as t
from tsetmc_marketdata.storage import schema_v3a as s
from tsetmc_marketdata.storage.queries import pending_dates
from tsetmc_marketdata.storage.repository import Repository
from tsetmc_marketdata.storage.serialization import canonical_hash, json_safe


class ScheduleStore:
    def __init__(self, repository: Repository, config: ServiceConfig, service_id: UUID) -> None:
        self.repo, self.config, self.service_id = repository, config, service_id

    def scope(self, job: ScheduledJob) -> Any:
        return sa.and_(
            s.schedules.c.ins_code == self.repo.ins_code, s.schedules.c.schedule_key == job.key
        )

    async def initialize(self, now: datetime) -> bool:
        async with self.repo.atomic():
            await self.repo.conn.execute(
                t.runs.update()
                .where(t.runs.c.ins_code == self.repo.ins_code, t.runs.c.status == "running")
                .values(status="interrupted", ended_at=now, failure_category="owner_lost")
            )
            pid, backend_start = (
                await self.repo.conn.execute(
                    sa.text(
                        "SELECT pid,backend_start FROM pg_stat_activity WHERE pid=pg_backend_pid()"
                    )
                )
            ).one()
            prior_runtime = await self.repo.conn.scalar(
                sa.select(s.runtime.c.service_id).where(s.runtime.c.ins_code == self.repo.ins_code)
            )
            for job in self.config.jobs:
                digest = canonical_hash(asdict(job))
                prior = (
                    (await self.repo.conn.execute(sa.select(s.schedules).where(self.scope(job))))
                    .mappings()
                    .one_or_none()
                )
                if prior and prior["spec_hash"] != digest:
                    raise ValueError("schedule specification changed; use a new schedule key")
                await self.repo.conn.execute(
                    insert(s.schedules)
                    .values(
                        ins_code=self.repo.ins_code,
                        schedule_key=job.key,
                        job=job.job,
                        spec_hash=digest,
                        next_due=job.first_due,
                    )
                    .on_conflict_do_nothing()
                )
            await self.repo.conn.execute(
                insert(s.runtime)
                .values(
                    ins_code=self.repo.ins_code,
                    service_id=self.service_id,
                    state="running",
                    owner_backend_pid=pid,
                    owner_backend_start=backend_start,
                    started_at=now,
                    heartbeat_at=now,
                    config_hash=canonical_hash(asdict(self.config)),
                    session_expectation="UNKNOWN",
                    session_confidence="unqualified",
                    session_provenance=[],
                    session_valid_until=now,
                )
                .on_conflict_do_update(
                    index_elements=[s.runtime.c.ins_code],
                    set_={
                        "service_id": self.service_id,
                        "state": "running",
                        "started_at": now,
                        "owner_backend_pid": pid,
                        "owner_backend_start": backend_start,
                        "heartbeat_at": now,
                        "ended_at": None,
                        "stop_reason": None,
                        "failure_category": None,
                        "config_hash": canonical_hash(asdict(self.config)),
                        "session_expectation": "UNKNOWN",
                        "session_confidence": "unqualified",
                        "session_provenance": [],
                        "session_valid_until": now,
                    },
                )
            )
            self.repo.publication_status = True
        return prior_runtime is not None

    async def rows(self) -> dict[str, dict[str, Any]]:
        async with self.repo.atomic():
            result = (
                (
                    await self.repo.conn.execute(
                        sa.select(s.schedules).where(s.schedules.c.ins_code == self.repo.ins_code)
                    )
                )
                .mappings()
                .all()
            )
            return {row["schedule_key"]: dict(row) for row in result}

    async def prepare(
        self, job: ScheduledJob, now: datetime, session: SessionDecision
    ) -> dict[str, Any]:
        async with self.repo.atomic():
            row = (
                (
                    await self.repo.conn.execute(
                        sa.select(s.schedules).where(self.scope(job)).with_for_update()
                    )
                )
                .mappings()
                .one()
            )
            if row["active_run_id"] is not None:
                return dict(row)
            missed = max(0, int((now - row["next_due"]).total_seconds() // job.interval))
            slot = row["next_due"] + timedelta(seconds=missed * job.interval)
            run_id = uuid5(
                NAMESPACE_URL,
                f"tsetmc:{self.repo.ins_code}:{job.key}:{row['spec_hash']}:{slot.isoformat()}",
            )
            dates = (
                await pending_dates(self.repo.conn, self.repo.ins_code, 5)
                if (job.job == "reconcile-history")
                else []
            )
            parameters = {
                "source_limit": job.source_limit if job.job == "refresh-history" else 0,
                "dates": [d.isoformat() for d in dates],
                "context": {
                    "schedule_key": job.key,
                    "slot": slot.isoformat(),
                    "spec_hash": row["spec_hash"],
                    **json_safe(asdict(session)),
                    "operating_provenance": job.provenance,
                },
            }
            values = {
                "active_slot": slot,
                "active_run_id": run_id,
                "active_parameters": parameters,
                "next_due": now + timedelta(seconds=job.interval),
                "coalesced_slots": row["coalesced_slots"] + missed,
            }
            await self.repo.conn.execute(
                s.schedules.update().where(self.scope(job)).values(**values)
            )
            return {**dict(row), **values}

    async def complete(self, job: ScheduledJob, row: dict[str, Any], now: datetime) -> None:
        async with self.repo.atomic():
            run = (
                await self.repo.conn.execute(
                    sa.select(t.runs.c.status).where(
                        t.runs.c.run_id == row["active_run_id"],
                        t.runs.c.ins_code == self.repo.ins_code,
                    )
                )
            ).scalar_one_or_none()
            no_pending = job.job == "reconcile-history" and not row["active_parameters"]["dates"]
            if run not in {"success", "partial"} and not no_pending:
                raise ValueError("schedule cannot advance before a committed collection run")
            await self.repo.conn.execute(
                s.schedules.update()
                .where(self.scope(job))
                .values(
                    next_due=max(
                        row["active_slot"] + timedelta(seconds=job.interval),
                        now + timedelta(seconds=job.interval),
                    ),
                    last_completed_slot=row["active_slot"],
                    last_committed_at=now,
                    active_slot=None,
                    active_run_id=None,
                    active_parameters=None,
                    failure_category=None,
                    failure_count=0,
                )
            )

    async def retry(self, job: ScheduledJob, now: datetime, category: str) -> int:
        async with self.repo.atomic():
            count = await self.repo.conn.scalar(
                s.schedules.update()
                .where(self.scope(job))
                .values(
                    failure_category=category,
                    failure_count=s.schedules.c.failure_count + 1,
                    next_due=now + timedelta(seconds=min(300, max(job.interval, 30) * 2)),
                )
                .returning(s.schedules.c.failure_count)
            )
            assert count is not None
            return int(count)

    async def heartbeat(
        self,
        now: datetime,
        decision: SessionDecision,
        *,
        state: str = "running",
        reason: str | None = None,
        failure: str | None = None,
        operation: str = "waiting",
    ) -> None:
        boundaries = [v for e in self.config.sessions for v in (e.start, e.end) if v > now]
        valid_until = min([self.config.end, *boundaries])
        async with self.repo.atomic():
            change = await self.repo.conn.scalar(
                sa.select(sa.func.max(t.snapshots.c.received_at)).where(
                    t.snapshots.c.ins_code == self.repo.ins_code,
                    t.snapshots.c.is_state_change.is_(True),
                )
            )
            values = dict(
                state=state,
                heartbeat_at=now,
                ended_at=now if state != "running" else None,
                session_expectation=decision.expectation.value,
                session_confidence=decision.confidence,
                session_provenance=list(decision.provenance),
                session_valid_until=valid_until,
                failure_category=failure,
                stop_reason=reason,
                operating_state=operation if state == "running" else state,
            )
            if change is not None:
                values["last_financial_change_at"] = change
            self.repo.publication_status = True
            await self.repo.conn.execute(
                s.runtime.update()
                .where(
                    s.runtime.c.ins_code == self.repo.ins_code,
                    s.runtime.c.service_id == self.service_id,
                )
                .values(**values)
            )
