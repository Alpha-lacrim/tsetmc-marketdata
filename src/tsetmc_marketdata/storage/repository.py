"""Instrument-scoped transactional ingestion, revisions and explicit reconciliation."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from tsetmc_marketdata.config import validate_ins_code
from tsetmc_marketdata.errors import SourceDataError
from tsetmc_marketdata.models.current import CurrentPrice
from tsetmc_marketdata.models.daily import DailyRecord
from tsetmc_marketdata.models.instrument import Instrument
from tsetmc_marketdata.parsing import HistoryResult, parse_daily
from tsetmc_marketdata.providers.http_client import JSONResponse
from tsetmc_marketdata.storage import schema_v1 as t
from tsetmc_marketdata.storage.database import fence
from tsetmc_marketdata.storage.ordering import choose_latest
from tsetmc_marketdata.storage.serialization import (
    canonical_hash,
    daily_from_row,
    financial_state,
    json_safe,
    numeric_values,
)
from tsetmc_marketdata.utils.dates import parse_source_date


def utcnow() -> datetime:
    return datetime.now(UTC)


def source_field(raw: dict[str, Any], key: str) -> str | None:
    return str(raw[key]) if raw.get(key) is not None else None


def identifiable_day(raw: Any) -> date | None:
    try:
        return parse_source_date(raw.get("dEven")) if isinstance(raw, dict) else None
    except ValueError:
        return None


class Repository:
    """A repository is bound to one session-owned instrument, never a global pilot."""

    def __init__(
        self, conn: AsyncConnection, ins_code: str, *, fault: Callable[[str], None] | None = None
    ) -> None:
        self.conn, self.ins_code, self.fault = conn, validate_ins_code(ins_code), fault
        self.identity_evidence_id: int | None = None
        self.run_context: dict[str, Any] = {}

    @asynccontextmanager
    async def atomic(self, *, ingest: bool = False) -> AsyncIterator[None]:
        async with self.conn.begin():
            await fence(self.conn, self.ins_code)
            yield
            await fence(self.conn, self.ins_code)
            if ingest and self.fault:
                self.fault("before_commit")
        if ingest and self.fault:
            self.fault("after_commit")

    async def begin_run(
        self, run_id: UUID, job: str, spec: dict[str, Any]
    ) -> dict[str, Any] | None:
        async with self.atomic():
            old = await self.conn.execute(sa.select(t.runs).where(t.runs.c.run_id == run_id))
            prior = old.mappings().one_or_none()
            if prior and (
                prior["ins_code"] != self.ins_code
                or prior["job"] != job
                or prior["request_spec"] != json_safe(spec)
            ):
                raise ValueError("run ID already belongs to another instrument/job/request")
            if prior and prior["status"] in {"success", "partial"}:
                return dict(prior["summary"])
            # Holding the session lock proves no other owner of this instrument is alive.
            await self.conn.execute(
                t.runs.update()
                .where(t.runs.c.ins_code == self.ins_code, t.runs.c.status == "running")
                .values(status="interrupted", ended_at=utcnow(), failure_category="owner_lost")
            )
            values = dict(
                run_id=run_id,
                ins_code=self.ins_code,
                job=job,
                request_spec=json_safe(spec),
                status="running",
                started_at=utcnow(),
                ended_at=None,
                failure_category=None,
                summary={},
                checkpoint={"phase": "started"},
            )
            if self.run_context:
                checkpoint = prior["checkpoint"] if prior else {}
                history = checkpoint.get("attempt_history", [])
                if prior:
                    history = [
                        *history,
                        {
                            "status": prior["status"],
                            "failure_category": prior["failure_category"],
                            "started_at": json_safe(prior["started_at"]),
                            "ended_at": json_safe(prior["ended_at"]),
                        },
                    ]
                values["checkpoint"].update(
                    attempt_count=checkpoint.get("attempt_count", 0) + 1,
                    attempt_history=history[-20:],
                )
            await self.conn.execute(
                insert(t.runs)
                .values(**values)
                .on_conflict_do_update(index_elements=[t.runs.c.run_id], set_=values)
            )
            await self.conn.execute(
                insert(t.status)
                .values(
                    ins_code=self.ins_code, job=job, last_run_id=run_id, last_attempt_at=utcnow()
                )
                .on_conflict_do_update(
                    index_elements=[t.status.c.ins_code, t.status.c.job],
                    set_={"last_run_id": run_id, "last_attempt_at": utcnow()},
                )
            )
        return None

    async def observation(
        self,
        run_id: UUID,
        response: JSONResponse,
        *,
        kind: str = "live_http",
        processing: str = "accepted",
    ) -> int:
        receipt = response.received_at
        if receipt.tzinfo is None or receipt.utcoffset() != timedelta(0):
            raise ValueError("observations require an actual aware UTC receipt timestamp")
        result = await self.conn.scalar(
            t.observations.insert()
            .values(
                run_id=run_id,
                ins_code=self.ins_code,
                endpoint=response.path,
                request_parameters={
                    "path": response.path,
                    "attempt_start_known": response.attempted_at is not None,
                    "identity_observation_id": self.identity_evidence_id,
                },
                attempted_at=response.attempted_at or receipt,
                received_at=receipt,
                http_status=response.status_code,
                raw_body=response.raw_body,
                raw_sha256=hashlib.sha256(response.raw_body).hexdigest(),
                parser_version="m2-v1",
                source_kind=kind,
                processing_status=processing,
            )
            .returning(t.observations.c.observation_id)
        )
        assert result is not None
        return int(result)

    async def metadata(
        self,
        run_id: UUID,
        record: Instrument,
        response: JSONResponse,
        *,
        kind: str = "live_http",
        active: bool = False,
    ) -> int:
        if record.ins_code != self.ins_code:
            raise ValueError("metadata belongs to another instrument")
        self.identity_evidence_id = None
        observation_id = await self.conn.scalar(
            sa.select(t.observations.c.observation_id)
            .join(
                t.instruments,
                t.instruments.c.metadata_observation_id == t.observations.c.observation_id,
            )
            .where(
                t.instruments.c.ins_code == self.ins_code,
                t.observations.c.ins_code == self.ins_code,
                t.observations.c.received_at == response.received_at,
                t.observations.c.raw_sha256 == hashlib.sha256(response.raw_body).hexdigest(),
                t.observations.c.source_kind == kind,
            )
        )
        if observation_id is None:
            observation_id = await self.observation(run_id, response, kind=kind)
        self.identity_evidence_id = int(observation_id)
        await self.conn.execute(
            t.instruments.update()
            .where(t.instruments.c.ins_code == self.ins_code)
            .values(
                symbol=record.symbol,
                company_name=record.company_name,
                instrument_id=record.instrument_id,
                isin=record.isin,
                raw_metadata=json_safe(record.raw),
                metadata_observation_id=observation_id,
                verified_at=response.received_at,
                active=active,
            )
        )
        return observation_id

    async def mark_coverage(self, day: date, state: str, observation_id: int) -> None:
        await self.conn.execute(
            insert(t.coverage)
            .values(
                ins_code=self.ins_code,
                trading_date=day,
                state=state,
                observation_id=observation_id,
                checked_at=utcnow(),
            )
            .on_conflict_do_update(
                index_elements=[t.coverage.c.ins_code, t.coverage.c.trading_date],
                set_={"state": state, "observation_id": observation_id, "checked_at": utcnow()},
            )
        )

    async def quarantine_row(
        self,
        observation_id: int,
        index: int,
        raw: Any,
        reason: str,
        *,
        day: date | None = None,
        record_kind: str = "daily",
    ) -> int:
        day = day or identifiable_day(raw)
        fingerprint = canonical_hash(
            {
                "instrument": self.ins_code,
                "day": day,
                "kind": record_kind,
                "raw": raw,
                "reason": reason,
            }
        )
        statement = insert(t.quarantine).values(
            ins_code=self.ins_code,
            trading_date=day,
            record_kind=record_kind,
            observation_id=observation_id,
            last_observation_id=observation_id,
            row_index=index,
            raw_row=json_safe(raw),
            reason=reason,
            fingerprint=fingerprint,
            status="open",
        )
        result = await self.conn.scalar(
            statement.on_conflict_do_update(
                index_elements=[t.quarantine.c.ins_code, t.quarantine.c.fingerprint],
                set_={
                    "last_observation_id": observation_id,
                    "sightings": t.quarantine.c.sightings + 1,
                },
            ).returning(t.quarantine.c.quarantine_id)
        )
        if day is not None and record_kind == "daily":
            accepted = await self.conn.scalar(
                sa.select(t.daily.c.financial_hash).where(
                    t.daily.c.ins_code == self.ins_code, t.daily.c.trading_date == day
                )
            )
            if accepted is None:
                await self.mark_coverage(day, "quarantined", observation_id)
        assert result is not None
        return int(result)

    async def daily_record(
        self,
        record: DailyRecord,
        observation_id: int,
        *,
        acceptance: str = "observed",
        reason: str = "validated_list_refresh",
        row_index: int = 0,
    ) -> str:
        if record.ins_code != self.ins_code:
            raise ValueError("daily record belongs to another instrument")
        try:
            measurements = numeric_values(record)
        except ValueError:
            await self.quarantine_row(
                observation_id,
                row_index,
                record.raw,
                "numeric_storage_limit",
                day=record.trading_date,
            )
            return "conflict"
        where = (t.daily.c.ins_code == self.ins_code, t.daily.c.trading_date == record.trading_date)
        prior = await self.conn.execute(sa.select(t.daily).where(*where).with_for_update())
        old = prior.mappings().one_or_none()
        state, digest = financial_state(record), canonical_hash(financial_state(record))
        if acceptance == "observed" and (old is None or old["financial_hash"] != digest):
            pending = (
                await self.conn.scalars(
                    sa.select(t.quarantine.c.raw_row).where(
                        t.quarantine.c.ins_code == self.ins_code,
                        t.quarantine.c.trading_date == record.trading_date,
                        t.quarantine.c.record_kind == "daily",
                        t.quarantine.c.status == "open",
                    )
                )
            ).all()
            for raw in pending:
                try:
                    candidate = parse_daily(raw, self.ins_code)
                    numeric_values(candidate)
                except (SourceDataError, ValueError):
                    continue
                await self.quarantine_row(
                    observation_id,
                    row_index,
                    record.raw,
                    "unresolved_valid_source_conflict",
                    day=record.trading_date,
                )
                return "conflict"
        # Another endpoint's disagreement cannot replace a reconciled candidate.
        if (
            old
            and old["acceptance"] == "reconciled"
            and acceptance == "observed"
            and old["financial_hash"] != digest
        ):
            await self.quarantine_row(
                observation_id,
                row_index,
                record.raw,
                "valid_list_disagrees_with_reconciled_record",
                day=record.trading_date,
            )
            return "conflict"
        now = utcnow()
        values = dict(
            ins_code=self.ins_code,
            trading_date=record.trading_date,
            **measurements,
            source_d_even=source_field(record.raw, "dEven"),
            source_h_even=source_field(record.raw, "hEven"),
            raw_row=json_safe(record.raw),
            observation_id=observation_id,
            financial_hash=digest,
            last_verified_at=now,
        )
        if old is None:
            await self.conn.execute(
                t.daily.insert().values(
                    **values,
                    revision=1,
                    first_seen_at=now,
                    acceptance=acceptance,
                    finalization_state="source_unverified",
                )
            )
            outcome = "inserted"
        elif old["financial_hash"] == digest:
            values["acceptance"] = "reconciled" if old["acceptance"] == "reconciled" else acceptance
            await self.conn.execute(t.daily.update().where(*where).values(**values))
            outcome = "unchanged"
        else:
            new_revision = old["revision"] + 1
            await self.conn.execute(
                t.revisions.insert().values(
                    ins_code=self.ins_code,
                    trading_date=record.trading_date,
                    revision=new_revision,
                    old_state=financial_state(daily_from_row(old)),
                    new_state=state,
                    old_hash=old["financial_hash"],
                    new_hash=digest,
                    old_observation_id=old["observation_id"],
                    new_observation_id=observation_id,
                    reason=reason,
                    discovered_at=now,
                )
            )
            await self.conn.execute(
                t.daily.update()
                .where(*where)
                .values(
                    **values,
                    revision=new_revision,
                    acceptance=acceptance,
                    finalization_state="source_unverified",
                )
            )
            outcome = "corrected"
        coverage = (
            "reconciled"
            if acceptance == "reconciled" or (old and old["acceptance"] == "reconciled")
            else (
                "confirmed_no_trade"
                if record.trade_count == 0
                and record.traded_volume == 0
                and record.traded_value == 0
                else "observed"
            )
        )
        await self.mark_coverage(record.trading_date, coverage, observation_id)
        return outcome

    async def finish(
        self, run_id: UUID, job: str, summary: dict[str, Any], *, partial: bool = False
    ) -> dict[str, Any]:
        result = {
            "run_id": str(run_id),
            "ins_code": self.ins_code,
            "status": "partial" if partial else "success",
            **summary,
            "archive_completeness": "unproven",
        }
        now = utcnow()
        checkpoint = await self.conn.scalar(
            sa.select(t.runs.c.checkpoint).where(
                t.runs.c.run_id == run_id, t.runs.c.ins_code == self.ins_code
            )
        )
        await self.conn.execute(
            t.runs.update()
            .where(t.runs.c.run_id == run_id, t.runs.c.ins_code == self.ins_code)
            .values(
                status=result["status"],
                ended_at=now,
                summary=json_safe(result),
                checkpoint={
                    **(checkpoint or {}),
                    "phase": "committed",
                    "accepted": result.get("accepted", 0),
                },
            )
        )
        await self.conn.execute(
            t.status.update()
            .where(t.status.c.ins_code == self.ins_code, t.status.c.job == job)
            .values(last_success_at=now, failure_category=None, failure_count=0, retry_after=None)
        )
        return result

    async def ingest_history(
        self,
        run_id: UUID,
        job: str,
        instrument: Instrument,
        metadata_response: JSONResponse,
        response: JSONResponse,
        parsed: HistoryResult,
        *,
        kind: str = "live_http",
        active: bool = False,
    ) -> dict[str, Any]:
        async with self.atomic(ingest=True):
            await self.metadata(run_id, instrument, metadata_response, kind=kind, active=active)
            observation_id = await self.observation(
                run_id,
                response,
                kind=kind,
                processing="partial" if parsed.has_errors else "accepted",
            )
            counts = {key: 0 for key in ("inserted", "unchanged", "corrected", "conflict")}
            source_indices: dict[date, int] = {}
            for index, raw in enumerate(parsed.raw_payload["closingPriceDaily"]):
                day = identifiable_day(raw)
                if day is not None:
                    source_indices.setdefault(day, index)
            for record in parsed.records:
                counts[
                    await self.daily_record(
                        record, observation_id, row_index=source_indices[record.trading_date]
                    )
                ] += 1
            rejected = 0
            for diagnostic in parsed.diagnostics:
                if diagnostic.severity == "error":
                    await self.quarantine_row(
                        observation_id,
                        diagnostic.index,
                        diagnostic.raw,
                        diagnostic.code + ": " + diagnostic.message,
                    )
                    rejected += 1
            result = await self.finish(
                run_id,
                job,
                {
                    **counts,
                    "source_records": len(parsed.raw_payload["closingPriceDaily"]),
                    "accepted": len(parsed.records) - counts["conflict"],
                    "quarantined": rejected + counts["conflict"],
                    "empty_valid_response": not parsed.raw_payload["closingPriceDaily"],
                },
                partial=bool(rejected or counts["conflict"]),
            )
        return result

    async def reconcile(
        self,
        run_id: UUID,
        job: str,
        instrument: Instrument,
        metadata_response: JSONResponse,
        candidates: list[tuple[date, DailyRecord | None, JSONResponse, str | None]],
        *,
        kind: str = "live_http",
        active: bool = False,
    ) -> dict[str, Any]:
        async with self.atomic(ingest=True):
            await self.metadata(run_id, instrument, metadata_response, kind=kind, active=active)
            accepted, unresolved, corrected = 0, 0, 0
            for day, record, response, error in candidates:
                if record is not None:
                    try:
                        numeric_values(record)
                    except ValueError:
                        record, error = None, "numeric_storage_limit"
                observation_id = await self.observation(
                    run_id,
                    response,
                    kind=kind,
                    processing="quarantined" if error else "accepted",
                )
                if record is None:
                    reason = "invalid_targeted_candidate: " + (error or "unknown")
                    await self.quarantine_row(observation_id, 0, response.payload, reason, day=day)
                    await self.conn.execute(
                        t.decisions.insert().values(
                            run_id=run_id,
                            ins_code=self.ins_code,
                            trading_date=day,
                            candidate_observation_id=observation_id,
                            accepted=False,
                            reason=reason,
                            decided_at=utcnow(),
                        )
                    )
                    unresolved += 1
                    continue
                old = (
                    (
                        await self.conn.execute(
                            sa.select(t.daily).where(
                                t.daily.c.ins_code == self.ins_code,
                                t.daily.c.trading_date == record.trading_date,
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                digest = canonical_hash(financial_state(record))
                # Endpoint priority alone cannot resolve two valid but different records.
                pending = (
                    await self.conn.scalars(
                        sa.select(t.quarantine.c.raw_row).where(
                            t.quarantine.c.ins_code == self.ins_code,
                            t.quarantine.c.trading_date == record.trading_date,
                            t.quarantine.c.record_kind == "daily",
                            t.quarantine.c.status == "open",
                        )
                    )
                ).all()
                valid_disagreement = False
                for raw in pending:
                    try:
                        quarantined = parse_daily(raw, self.ins_code)
                        numeric_values(quarantined)
                    except (SourceDataError, ValueError):
                        continue
                    if canonical_hash(financial_state(quarantined)) != digest:
                        valid_disagreement = True
                agrees = (old is None or old["financial_hash"] == digest) and not valid_disagreement
                reason = (
                    "two_valid_records_disagree"
                    if not agrees
                    else (
                        "validated_target_replaces_invalid_list"
                        if pending
                        else "validated_target_initial_observation"
                    )
                    if old is None
                    else "target_confirms_canonical"
                )
                await self.conn.execute(
                    t.decisions.insert().values(
                        run_id=run_id,
                        ins_code=self.ins_code,
                        trading_date=record.trading_date,
                        candidate_observation_id=observation_id,
                        previous_observation_id=old["observation_id"] if old else None,
                        accepted=agrees,
                        reason=reason,
                        decided_at=utcnow(),
                    )
                )
                if not agrees:
                    await self.quarantine_row(
                        observation_id, 0, record.raw, reason, day=record.trading_date
                    )
                    unresolved += 1
                    continue
                outcome = await self.daily_record(
                    record, observation_id, acceptance="reconciled", reason=reason
                )
                corrected += outcome == "corrected"
                await self.conn.execute(
                    t.quarantine.update()
                    .where(
                        t.quarantine.c.ins_code == self.ins_code,
                        t.quarantine.c.trading_date == record.trading_date,
                        t.quarantine.c.record_kind == "daily",
                        t.quarantine.c.status == "open",
                    )
                    .values(
                        status="resolved",
                        resolution_observation_id=observation_id,
                        resolution_hash=digest,
                        resolved_at=utcnow(),
                        resolution_method=reason,
                    )
                )
                accepted += 1
            result = await self.finish(
                run_id,
                job,
                {
                    "accepted": accepted,
                    "reconciled": accepted,
                    "unresolved": unresolved,
                    "corrected": corrected,
                },
                partial=bool(unresolved),
            )
        return result

    async def ingest_current(
        self,
        run_id: UUID,
        job: str,
        instrument: Instrument,
        metadata_response: JSONResponse,
        response: JSONResponse,
        record: CurrentPrice,
        *,
        kind: str = "live_http",
        active: bool = False,
        correction_reason: str | None = None,
    ) -> dict[str, Any]:
        if record.ins_code != self.ins_code or record.received_at != response.received_at:
            raise ValueError("current record identity/receipt does not match its evidence")
        async with self.atomic(ingest=True):
            await self.metadata(run_id, instrument, metadata_response, kind=kind, active=active)
            observation_id = await self.observation(run_id, response, kind=kind)
            old = (
                (
                    await self.conn.execute(
                        sa.select(t.snapshots)
                        .join(t.latest, t.latest.c.snapshot_id == t.snapshots.c.snapshot_id)
                        .where(t.latest.c.ins_code == self.ins_code)
                    )
                )
                .mappings()
                .one_or_none()
            )
            digest = canonical_hash(financial_state(record))
            decision = choose_latest(
                dict(old) if old else None, record, digest, correction_reason=correction_reason
            )
            snapshot_id = await self.conn.scalar(
                t.snapshots.insert()
                .values(
                    ins_code=self.ins_code,
                    observation_id=observation_id,
                    **numeric_values(record),
                    source_date=record.source_date,
                    source_time=record.source_time,
                    source_reported_at=record.source_reported_at,
                    received_at=response.received_at,
                    source_d_even=source_field(record.raw, "dEven"),
                    source_h_even=source_field(record.raw, "hEven"),
                    raw_row=json_safe(record.raw),
                    instrument_state=record.instrument_state,
                    instrument_state_title=record.instrument_state_title,
                    financial_hash=digest,
                    decision=decision.code,
                    decision_reason=correction_reason,
                    is_state_change=decision.state_change,
                )
                .returning(t.snapshots.c.snapshot_id)
            )
            if decision.update:
                await self.conn.execute(
                    insert(t.latest)
                    .values(ins_code=self.ins_code, snapshot_id=snapshot_id, updated_at=utcnow())
                    .on_conflict_do_update(
                        index_elements=[t.latest.c.ins_code],
                        set_={"snapshot_id": snapshot_id, "updated_at": utcnow()},
                    )
                )
            if decision.review:
                await self.quarantine_row(
                    observation_id,
                    0,
                    record.raw,
                    decision.code,
                    day=record.source_date,
                    record_kind="current",
                )
            result = await self.finish(
                run_id,
                job,
                {
                    "accepted": 1,
                    "snapshot_id": snapshot_id,
                    "latest_updated": decision.update,
                    "decision": decision.code,
                    "state_change": decision.state_change,
                    "new_trade_claimed": False,
                },
                partial=decision.review,
            )
        return result

    async def fail(
        self,
        run_id: UUID,
        job: str,
        category: str,
        responses: list[JSONResponse],
        *,
        failed_path: str | None = None,
        http_status: int | None = None,
        kind: str = "live_http",
    ) -> None:
        if self.conn.in_transaction():
            await self.conn.rollback()
        async with self.atomic():
            old = (
                (
                    await self.conn.execute(
                        sa.select(t.runs).where(
                            t.runs.c.run_id == run_id, t.runs.c.ins_code == self.ins_code
                        )
                    )
                )
                .mappings()
                .one()
            )
            if old["status"] in {"success", "partial"}:
                return  # Commit succeeded but its acknowledgment was lost: never relabel it failed.
            for response in responses:
                await self.observation(run_id, response, kind=kind, processing="ingestion_failed")
            if failed_path:
                await self.conn.execute(
                    t.observations.insert().values(
                        run_id=run_id,
                        ins_code=self.ins_code,
                        endpoint=failed_path,
                        request_parameters={"path": failed_path},
                        attempted_at=utcnow(),
                        http_status=http_status,
                        raw_body=None,
                        parser_version="m2-v1",
                        source_kind=kind,
                        processing_status=(
                            "source_rejected" if http_status == 200 else "request_failed"
                        ),
                        failure_category=category,
                    )
                )
            now = utcnow()
            state = "interrupted" if category == "cancelled" else "failed"
            await self.conn.execute(
                t.runs.update()
                .where(t.runs.c.run_id == run_id)
                .values(
                    status=state,
                    ended_at=now,
                    failure_category=category,
                    summary={"status": state, "failure_category": category},
                    checkpoint={**old["checkpoint"], "phase": "failed_before_data_commit"},
                )
            )
            await self.conn.execute(
                t.status.update()
                .where(t.status.c.ins_code == self.ins_code, t.status.c.job == job)
                .values(
                    failure_category=category,
                    failure_count=t.status.c.failure_count + 1,
                    retry_after=now + timedelta(seconds=30),
                )
            )
