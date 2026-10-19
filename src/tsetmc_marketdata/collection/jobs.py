"""Reuse the Milestone 1 client/parser boundary; commit checkpoints with accepted data."""

import asyncio
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa

from tsetmc_marketdata.collection.scheduler import Clock, SystemClock
from tsetmc_marketdata.collection.source import Source
from tsetmc_marketdata.errors import RecordError, SourceDataError, TSETMCError
from tsetmc_marketdata.models.daily import DailyRecord
from tsetmc_marketdata.parsing import (
    parse_current,
    parse_history,
    parse_instrument,
    parse_targeted_daily,
)
from tsetmc_marketdata.providers.http_client import JSONResponse
from tsetmc_marketdata.storage.config import StorageError
from tsetmc_marketdata.storage.repository import Repository


class Collector:
    def __init__(
        self,
        repository: Repository,
        source: Source,
        *,
        kind: str = "live_http",
        active: bool = False,
        expected_instrument_id: str | None = None,
        metadata_ttl: float = 0,
        clock: Clock | None = None,
    ) -> None:
        self.repository, self.source, self.kind, self.active = repository, source, kind, active
        self.expected_instrument_id = expected_instrument_id
        if not 0 <= metadata_ttl <= 86400:
            raise ValueError("invalid metadata cache lifetime")
        self.metadata_ttl, self.clock = metadata_ttl, clock or SystemClock()
        self._metadata_cache: JSONResponse | None = None
        self._cache_at: float | None = None

    async def run(
        self,
        job: str,
        *,
        source_limit: int = 0,
        dates: list[date] | None = None,
        run_id: UUID | None = None,
        correction_reason: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if not 0 <= source_limit <= 100000 or (dates is not None and len(dates) > 20):
            raise ValueError("job exceeds the bounded request/row-parameter policy")
        ins_code = self.repository.ins_code
        run_id = run_id or uuid4()
        spec = {
            "source_limit": source_limit,
            "dates": [d.isoformat() for d in dates or []],
            "source_kind": self.kind,
            "correction_reason": correction_reason,
            "expected_instrument_id": self.expected_instrument_id,
            "activate": self.active,
        }
        if self.repository.run_context:
            spec["schedule_context"] = self.repository.run_context
        if not dry_run:
            cached = await self.repository.begin_run(run_id, job, spec)
            if cached is not None:
                return {**cached, "replayed_committed_run": True}
        responses: list[JSONResponse] = []
        path = f"Instrument/GetInstrumentInfo/{ins_code}"
        try:
            now = self.clock.monotonic()
            cached_metadata = (
                self._metadata_cache is not None
                and self._cache_at is not None
                and 0 <= now - self._cache_at < self.metadata_ttl
                and self.clock.now() >= self._metadata_cache.received_at
                and (self.clock.now() - self._metadata_cache.received_at).total_seconds()
                < self.metadata_ttl
            )
            metadata = self._metadata_cache if cached_metadata else await self.source.get_json(path)
            assert metadata is not None
            if not cached_metadata:
                responses.append(metadata)
            instrument = parse_instrument(metadata.payload, ins_code)
            if (
                self.expected_instrument_id is not None
                and instrument.instrument_id != self.expected_instrument_id
            ):
                raise RecordError("metadata instrument ID does not match configuration")
            self._metadata_cache, self._cache_at = (
                metadata,
                now if not cached_metadata else self._cache_at,
            )
            if job in {"backfill-history", "refresh-history", "audit-history"}:
                path = f"ClosingPrice/GetClosingPriceDailyList/{ins_code}/{source_limit}"
                response = await self.source.get_json(path)
                responses.append(response)
                parsed = parse_history(response.payload, ins_code)
                if dry_run:
                    return {
                        "dry_run": True,
                        "accepted": len(parsed.records),
                        "quarantined": sum(d.severity == "error" for d in parsed.diagnostics),
                    }
                return await self.repository.ingest_history(
                    run_id,
                    job,
                    instrument,
                    metadata,
                    response,
                    parsed,
                    kind=self.kind,
                    active=self.active,
                )
            if job == "observe-current":
                path = f"ClosingPrice/GetClosingPriceInfo/{ins_code}"
                response = await self.source.get_json(path)
                responses.append(response)
                current = parse_current(
                    response.payload, ins_code, received_at=response.received_at
                )
                if dry_run:
                    return {"dry_run": True, "parsed_current": True}
                return await self.repository.ingest_current(
                    run_id,
                    job,
                    instrument,
                    metadata,
                    response,
                    current,
                    kind=self.kind,
                    active=self.active,
                    correction_reason=correction_reason,
                )
            if job == "reconcile-history":
                candidates: list[tuple[date, DailyRecord | None, JSONResponse, str | None]] = []
                for day in dates or []:
                    path = f"ClosingPrice/GetClosingPriceDaily/{ins_code}/{day:%Y%m%d}"
                    response = await self.source.get_json(path)
                    responses.append(response)
                    try:
                        record = parse_targeted_daily(response.payload, ins_code, day)
                    except SourceDataError as exc:
                        candidates.append((day, None, response, exc.kind.value + ": " + str(exc)))
                    else:
                        candidates.append((day, record, response, None))
                if dry_run:
                    return {
                        "dry_run": True,
                        "valid_targeted_candidates": sum(
                            r is not None for _, r, _, _ in candidates
                        ),
                        "invalid_targeted_candidates": sum(r is None for _, r, _, _ in candidates),
                    }
                return await self.repository.reconcile(
                    run_id,
                    job,
                    instrument,
                    metadata,
                    candidates,
                    kind=self.kind,
                    active=self.active,
                )
            raise ValueError("unsupported collection job")
        except BaseException as exc:
            if isinstance(exc, SourceDataError):
                self._metadata_cache, self._cache_at = None, None
            if not dry_run:
                category = (
                    exc.kind.value
                    if isinstance(exc, TSETMCError)
                    else "cancelled"
                    if isinstance(exc, asyncio.CancelledError)
                    else exc.category
                    if isinstance(exc, StorageError)
                    else "postgres_write_failure"
                    if isinstance(exc, sa.exc.SQLAlchemyError)
                    else "ingestion_failed"
                )
                try:
                    await self.repository.fail(
                        run_id,
                        job,
                        category,
                        responses,
                        failed_path=path if isinstance(exc, TSETMCError) else None,
                        http_status=(
                            exc.status
                            or (
                                responses[-1].status_code
                                if responses and responses[-1].path == path
                                else None
                            )
                            if isinstance(exc, TSETMCError)
                            else None
                        ),
                        kind=self.kind,
                    )
                except (sa.exc.SQLAlchemyError, StorageError):
                    # The original durable 'running' row remains truthful until next-owner recovery.
                    pass
            raise
