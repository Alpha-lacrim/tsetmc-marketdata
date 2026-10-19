"""Independent process, HTTP-availability and source-freshness reports; no raw payloads."""

import math
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from tsetmc_marketdata.collection.sessions import Expectation, aware
from tsetmc_marketdata.storage import schema_v1 as t
from tsetmc_marketdata.storage import schema_v3a as s
from tsetmc_marketdata.storage.database import LOCK_NAMESPACE
from tsetmc_marketdata.storage.serialization import json_safe


def age(now: datetime, instant: datetime | None) -> float | None:
    return (aware(now) - aware(instant)).total_seconds() if instant is not None else None


def freshness(age_seconds: float | None, expectation: Expectation, threshold: float) -> str:
    if age_seconds is None:
        return "unknown_source_time"
    if age_seconds < 0:
        return "source_clock_ahead"
    if age_seconds <= threshold:
        return "recent_source_observation"
    return {
        Expectation.EXPECTED: "unexpectedly_stale",
        Expectation.NOT_EXPECTED: "unchanged_updates_not_expected",
        Expectation.UNKNOWN: "stale_session_unknown",
    }[expectation]


async def health_report(
    conn: AsyncConnection,
    ins_code: str,
    now: datetime,
    *,
    include_prices: bool = False,
    stale_after: float = 180,
) -> dict[str, Any]:
    if not math.isfinite(stale_after) or stale_after <= 0:
        raise ValueError("freshness threshold must be positive")
    runtime = (
        (await conn.execute(sa.select(s.runtime).where(s.runtime.c.ins_code == ins_code)))
        .mappings()
        .one_or_none()
    )
    latest = (
        (
            await conn.execute(
                sa.select(t.snapshots)
                .join(t.latest, t.latest.c.snapshot_id == t.snapshots.c.snapshot_id)
                .where(t.latest.c.ins_code == ins_code)
            )
        )
        .mappings()
        .one_or_none()
    )
    receipt = await conn.scalar(
        sa.select(sa.func.max(t.observations.c.received_at)).where(
            t.observations.c.ins_code == ins_code,
            t.observations.c.endpoint == f"ClosingPrice/GetClosingPriceInfo/{ins_code}",
            t.observations.c.http_status.between(200, 299),
        )
    )
    committed = await conn.scalar(
        sa.select(sa.func.max(t.runs.c.ended_at)).where(
            t.runs.c.ins_code == ins_code, t.runs.c.status.in_(["success", "partial"])
        )
    )
    current_status = (
        (
            await conn.execute(
                sa.select(t.status).where(
                    t.status.c.ins_code == ins_code, t.status.c.job == "observe-current"
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    failures = (
        (
            await conn.execute(
                sa.select(
                    t.runs.c.job,
                    t.runs.c.status,
                    t.runs.c.failure_category,
                    t.runs.c.ended_at,
                    t.runs.c.checkpoint,
                )
                .where(
                    t.runs.c.ins_code == ins_code,
                    sa.or_(
                        t.runs.c.status.in_(["failed", "interrupted", "running"]),
                        t.runs.c.checkpoint["attempt_count"].as_integer() > 1,
                    ),
                )
                .order_by(t.runs.c.started_at.desc())
                .limit(10)
            )
        )
        .mappings()
        .all()
    )
    owned = False
    if runtime:
        owned = bool(
            await conn.scalar(
                sa.text("""SELECT EXISTS (
            SELECT 1 FROM pg_locks l JOIN pg_stat_activity a ON a.pid=l.pid
            JOIN instruments i ON i.ownership_key=l.objid
            WHERE l.locktype='advisory' AND l.classid=:namespace AND l.objsubid=2
            AND l.granted AND i.ins_code=:code AND l.pid=:pid AND a.backend_start=:started)
        """),
                {
                    "namespace": LOCK_NAMESPACE,
                    "code": ins_code,
                    "pid": runtime["owner_backend_pid"],
                    "started": runtime["owner_backend_start"],
                },
            )
        )
    operating = "never_started" if runtime is None else runtime["state"]
    if runtime and runtime["state"] == "running" and not owned:
        operating = "interrupted_owner_absent"
    expectation = (
        Expectation(runtime["session_expectation"])
        if runtime and runtime["session_valid_until"] > aware(now)
        else Expectation.UNKNOWN
    )
    daily = (
        (
            await conn.execute(
                sa.select(
                    t.daily.c.trading_date,
                    t.daily.c.finalization_state,
                    t.daily.c.acceptance,
                    t.daily.c.revision,
                )
                .where(t.daily.c.ins_code == ins_code)
                .order_by(t.daily.c.trading_date.desc())
                .limit(1)
            )
        )
        .mappings()
        .one_or_none()
    )
    schedules = (
        (await conn.execute(sa.select(s.schedules).where(s.schedules.c.ins_code == ins_code)))
        .mappings()
        .all()
    )
    counts = {
        table.name: await conn.scalar(
            sa.select(sa.func.count()).select_from(table).where(table.c.ins_code == ins_code)
        )
        for table in (t.daily, t.revisions, t.quarantine)
    }
    snapshot: dict[str, Any] | None = None
    if latest:
        snapshot = {
            key: latest[key]
            for key in (
                "snapshot_id",
                "source_date",
                "source_time",
                "source_reported_at",
                "received_at",
                "decision",
                "instrument_state",
                "instrument_state_title",
                "financial_hash",
            )
        }
        if include_prices:
            snapshot.update({key: latest[key] for key in t.MEASUREMENTS})
    source_age = age(now, latest["source_reported_at"] if latest else None)
    category = current_status["failure_category"] if current_status else None
    if category in {
        "timeout",
        "dns_failure",
        "network_failure",
        "access_denied",
        "rate_limited",
        "http_5xx",
        "http_error",
    }:
        availability = "latest_request_failed"
    elif category in {
        "invalid_json",
        "unexpected_schema",
        "invalid_record",
        "instrument_not_found",
    }:
        availability = "source_unusable"
    elif category:
        availability = "application_failure_http_independent"
    else:
        availability = "http_observed" if receipt else "unknown"
    result: dict[str, Any] = {
        "ins_code": ins_code,
        "process_state": operating,
        "ownership_verified": owned,
        "operating_state": runtime["operating_state"] if runtime and owned else operating,
        "heartbeat_age_seconds": age(now, runtime["heartbeat_at"] if runtime else None),
        "session_expectation": expectation.value,
        "session_confidence": runtime["session_confidence"]
        if runtime and expectation != Expectation.UNKNOWN
        else "unqualified",
        "session_provenance": runtime["session_provenance"] if runtime else [],
        "last_successful_current_http": receipt,
        "http_age_seconds": age(now, receipt),
        "last_successful_database_commit": committed,
        "last_accepted_source_observation": latest["source_reported_at"] if latest else None,
        "source_age_seconds": source_age,
        "data_freshness": freshness(source_age, expectation, stale_after),
        "last_financial_change_at": runtime["last_financial_change_at"] if runtime else None,
        "latest_failure_category": current_status["failure_category"] if current_status else None,
        "source_availability": availability,
        "latest": snapshot,
        "most_recent_daily": dict(daily) if daily else None,
        "counts": counts,
        "scheduled_jobs": [dict(row) for row in schedules],
        "pending_schedules": sum(row["next_due"] <= aware(now) for row in schedules),
        "failed_or_interrupted_runs": [dict(row) for row in failures],
        "archive_completeness": "unproven",
        "captures_every_trade": False,
    }
    return dict(json_safe(result))
