"""Explicit foreground service. One instrument owner, durable coalesced jobs, no auto-start."""

import asyncio
from collections.abc import Callable
from datetime import date
from typing import Any
from uuid import uuid4

import sqlalchemy as sa

from tsetmc_marketdata.collection.budget import BudgetSource, RequestBudgetError
from tsetmc_marketdata.collection.jobs import Collector
from tsetmc_marketdata.collection.scheduler import Clock, SystemClock
from tsetmc_marketdata.collection.service_config import ScheduledJob, ServiceConfig
from tsetmc_marketdata.collection.sessions import Expectation, aware, session_expectation
from tsetmc_marketdata.errors import ErrorKind, TSETMCError
from tsetmc_marketdata.storage.config import StorageError
from tsetmc_marketdata.storage.repository import Repository
from tsetmc_marketdata.storage.scheduling import ScheduleStore


def eligible(job: ScheduledJob, expectation: Expectation) -> bool:
    if job.eligibility == "OPERATOR_WINDOW":
        # Explicit approval permits investigation during unknown periods, never overrides closure.
        return (
            expectation != Expectation.NOT_EXPECTED
            if job.job == "observe-current"
            else (expectation != Expectation.EXPECTED)
        )
    return job.eligibility == expectation.value


class CollectionService:
    def __init__(
        self,
        repo: Repository,
        source: BudgetSource,
        config: ServiceConfig,
        *,
        clock: Clock | None = None,
        kind: str = "live_http",
        fault: Callable[[str], None] | None = None,
    ) -> None:
        if repo.ins_code != config.ins_code:
            raise ValueError("service/repository instrument mismatch")
        self.repo, self.source, self.config = repo, source, config
        self.clock, self.fault = clock or SystemClock(), fault
        self.store = ScheduleStore(repo, config, uuid4())
        self.collector = Collector(
            repo,
            source,
            kind=kind,
            active=kind == "live_http",
            expected_instrument_id=config.expected_instrument_id,
            metadata_ttl=config.metadata_ttl,
            clock=self.clock,
        )

    async def run(self) -> dict[str, Any]:
        cfg, clock = self.config, self.clock
        if not cfg.enabled:
            raise ValueError("collector is disabled; explicit operator activation is required")
        start = aware(clock.now())
        if not cfg.start <= start < cfg.end:
            raise ValueError("collector must start inside its explicit operating window")
        started_mono = clock.monotonic()
        monotonic_end = started_mono + (cfg.end - start).total_seconds()
        recovered = await self.store.initialize(start)
        current_not_before = started_mono + (30 if recovered else 0)
        completed = 0
        reason, failure = "window_ended", None
        state = "stopped"
        try:
            while aware(clock.now()) < cfg.end and clock.monotonic() < monotonic_end:
                now = aware(clock.now())
                decision = session_expectation(now, cfg.ins_code, cfg.sessions)
                await self.store.heartbeat(now, decision)
                if self.source.requests >= cfg.request_budget:
                    reason = "request_budget_exhausted"
                    break
                if completed >= cfg.max_jobs:
                    reason = "job_budget_exhausted"
                    break
                rows = await self.store.rows()
                current_active = any(
                    j.job == "observe-current" and eligible(j, decision.expectation)
                    for j in cfg.jobs
                )
                ready = [
                    j
                    for j in cfg.jobs
                    if rows[j.key]["next_due"] <= now
                    and eligible(j, decision.expectation)
                    and not (j.job == "audit-history" and current_active)
                    and (j.job != "observe-current" or clock.monotonic() >= current_not_before)
                ]
                # Current work wins each turn. At most one maintenance job runs before rechecking.
                ready.sort(
                    key=lambda j: (j.job != "observe-current", rows[j.key]["next_due"], j.key)
                )
                if not ready:
                    remaining = min(
                        (cfg.end - now).total_seconds(), monotonic_end - clock.monotonic()
                    )
                    await clock.sleep(min(5, max(0, remaining)))
                    continue
                job = ready[0]
                row = await self.store.prepare(job, now, decision)
                await self.store.heartbeat(now, decision, operation=job.job)
                params = row["active_parameters"]
                self.repo.run_context = params["context"]
                before_events, before_requests = len(self.source.events), self.source.requests
                try:
                    remaining = min(
                        (cfg.end - aware(clock.now())).total_seconds(),
                        monotonic_end - clock.monotonic(),
                    )
                    timeout = cfg.job_timeout
                    if job.job != "observe-current" and current_active:
                        timeout = min(
                            timeout, min(j.interval for j in cfg.jobs if j.job == "observe-current")
                        )
                    async with asyncio.timeout(min(timeout, max(0, remaining))):
                        if job.job == "reconcile-history" and not params["dates"]:
                            result = {"status": "no_pending_daily_quarantine", "source_requests": 0}
                        else:
                            result = await self.collector.run(
                                job.job,
                                run_id=row["active_run_id"],
                                source_limit=params["source_limit"],
                                dates=[date.fromisoformat(d) for d in params["dates"]] or None,
                            )
                        if self.fault:
                            self.fault("after_job_commit")
                        await self.store.complete(job, row, aware(clock.now()))
                    await self.source.record(
                        {
                            "kind": "committed_job",
                            "job": job.job,
                            "result": result,
                            "schedule_key": job.key,
                            "slot": row["active_slot"],
                            "completed_at": aware(clock.now()),
                            "session": decision.expectation,
                            "requests_for_job": self.source.requests - before_requests,
                            "receipt_to_schedule_commit_seconds": (
                                aware(clock.now()) - self.source.events[-1]["received_at"]
                            ).total_seconds()
                            if len(self.source.events) > before_events
                            and self.source.events[-1].get("received_at")
                            else None,
                        }
                    )
                    completed += 1
                    failure = None
                    if job.job == "observe-current":
                        current_not_before = clock.monotonic() + job.interval
                except (TSETMCError, RequestBudgetError, TimeoutError) as exc:
                    failure = (
                        exc.kind.value
                        if isinstance(exc, TSETMCError)
                        else exc.category
                        if isinstance(exc, StorageError)
                        else "job_timeout"
                    )
                    failures = await self.store.retry(job, aware(clock.now()), failure)
                    if isinstance(exc, RequestBudgetError):
                        reason = "request_budget_exhausted"
                        break
                    if (isinstance(exc, TSETMCError) and exc.kind == ErrorKind.ACCESS_DENIED) or (
                        failures >= cfg.max_failures
                    ):
                        state, reason = "failed", "source_failure_limit"
                        break
                    # A source outage defers this durable slot; other due work remains bounded.
                    await clock.sleep(
                        min(5, max(0, (cfg.end - aware(clock.now())).total_seconds()))
                    )
        except asyncio.CancelledError:
            reason = "cancelled"
            raise
        except BaseException as exc:
            state, reason = "failed", "collector_failure"
            failure = (
                "postgres_failure"
                if isinstance(exc, (sa.exc.SQLAlchemyError, StorageError))
                else ("collector_failure")
            )
            raise
        finally:
            self.repo.run_context = {}
            decision = session_expectation(aware(clock.now()), cfg.ins_code, cfg.sessions)
            try:
                await self.store.heartbeat(
                    aware(clock.now()), decision, state=state, reason=reason, failure=failure
                )
            except (sa.exc.SQLAlchemyError, StorageError):
                # An unavailable DB cannot record shutdown. The absent advisory owner reveals it.
                pass
        return {
            "state": state,
            "stop_reason": reason,
            "completed_jobs": completed,
            "logical_requests": self.source.requests,
            "session_expectation": decision.expectation,
            "full_session_qualified": False,
        }
