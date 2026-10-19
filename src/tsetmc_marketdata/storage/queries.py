"""Read-only queries and explicitly activated retention, all instrument-scoped."""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from tsetmc_marketdata.models.daily import DailyRecord
from tsetmc_marketdata.storage import schema_v1 as t
from tsetmc_marketdata.storage import schema_v3a as s
from tsetmc_marketdata.storage.database import fence
from tsetmc_marketdata.storage.serialization import daily_from_row, json_safe


async def read_daily(
    conn: AsyncConnection,
    ins_code: str,
    *,
    selection: Literal["finalized", "accepted-unverified"] = "finalized",
) -> tuple[list[DailyRecord], dict[str, Any]]:
    if selection not in {"finalized", "accepted-unverified"}:
        raise ValueError("unsupported finalization selection")
    all_count = await conn.scalar(
        sa.select(sa.func.count()).select_from(t.daily).where(t.daily.c.ins_code == ins_code)
    )
    assert all_count is not None
    statement = sa.select(t.daily).where(t.daily.c.ins_code == ins_code)
    if selection == "finalized":
        statement = statement.where(t.daily.c.finalization_state == "operator_finalized")
    rows = (await conn.execute(statement.order_by(t.daily.c.trading_date))).mappings().all()
    return [daily_from_row(row) for row in rows], {
        "selection": selection,
        "stored_accepted": all_count,
        "selected_records": len(rows),
        "source_finality": "not_established",
        "excluded_unverified": all_count - len(rows),
    }


async def pending_dates(conn: AsyncConnection, ins_code: str, limit: int = 10) -> list[Any]:
    if not 1 <= limit <= 20:
        raise ValueError("reconciliation request bound must be 1..20")
    result = await conn.scalars(
        sa.select(t.quarantine.c.trading_date)
        .where(
            t.quarantine.c.ins_code == ins_code,
            t.quarantine.c.record_kind == "daily",
            t.quarantine.c.status == "open",
            t.quarantine.c.trading_date.is_not(None),
        )
        .distinct()
        .order_by(t.quarantine.c.trading_date)
        .limit(limit)
    )
    return list(result)


async def collection_report(conn: AsyncConnection, ins_code: str) -> dict[str, Any]:
    statuses = await conn.execute(sa.select(t.status).where(t.status.c.ins_code == ins_code))
    runs = await conn.execute(
        sa.select(t.runs)
        .where(t.runs.c.ins_code == ins_code)
        .order_by(t.runs.c.started_at.desc())
        .limit(10)
    )
    coverage = (
        await conn.execute(
            sa.select(t.coverage.c.state, sa.func.count())
            .where(t.coverage.c.ins_code == ins_code)
            .group_by(t.coverage.c.state)
        )
    ).all()
    counts = {}
    for table in (t.daily, t.revisions, t.snapshots, t.quarantine, t.observations):
        counts[table.name] = await conn.scalar(
            sa.select(sa.func.count()).select_from(table).where(table.c.ins_code == ins_code)
        )
    current = (
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
    return cast(
        dict[str, Any],
        json_safe(
            {
                "ins_code": ins_code,
                "counts": counts,
                "status": [dict(row) for row in statuses.mappings()],
                "recent_runs": [dict(row) for row in runs.mappings()],
                "coverage": {state: count for state, count in coverage},
                "absent_dates": "unknown; no inferred exchange calendar",
                "latest": dict(current) if current else None,
                "archive_completeness": "unproven",
            }
        ),
    )


async def retain(
    conn: AsyncConnection, ins_code: str, *, apply: bool = False, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    # Seven days of every receipt; 90 days of state changes; current_latest is permanent.
    candidate = sa.and_(
        t.snapshots.c.ins_code == ins_code,
        t.snapshots.c.received_at < now - timedelta(days=7),
        sa.or_(
            t.snapshots.c.is_state_change.is_(False),
            t.snapshots.c.received_at < now - timedelta(days=90),
        ),
        ~sa.exists(
            sa.select(t.latest.c.snapshot_id).where(
                t.latest.c.snapshot_id == t.snapshots.c.snapshot_id
            )
        ),
    )
    snapshot_count = await conn.scalar(
        sa.select(sa.func.count()).select_from(t.snapshots).where(candidate)
    )
    if apply:
        await fence(conn, ins_code)
        await conn.execute(t.snapshots.delete().where(candidate))
    references = [
        sa.select(table.c[column]).where(table.c[column].is_not(None))
        for table, columns in (
            (t.instruments, ["metadata_observation_id"]),
            (t.daily, ["observation_id"]),
            (t.revisions, ["old_observation_id", "new_observation_id"]),
            (t.snapshots, ["observation_id"]),
            (t.quarantine, ["observation_id", "last_observation_id", "resolution_observation_id"]),
            (t.decisions, ["candidate_observation_id", "previous_observation_id"]),
            (t.coverage, ["observation_id"]),
            (s.reviews, ["first_observation_id", "second_observation_id"]),
        )
        for column in columns
    ]
    identity_reference = sa.cast(
        t.observations.c.request_parameters["identity_observation_id"].astext, sa.BigInteger
    )
    references.append(sa.select(identity_reference).where(identity_reference.is_not(None)))
    body_candidate = sa.and_(
        t.observations.c.ins_code == ins_code,
        t.observations.c.received_at < now - timedelta(days=90),
        t.observations.c.raw_body.is_not(None),
        t.observations.c.observation_id.not_in(sa.union_all(*references)),
    )
    body_count = await conn.scalar(
        sa.select(sa.func.count()).select_from(t.observations).where(body_candidate)
    )
    if apply:
        await conn.execute(
            t.observations.update().where(body_candidate).values(raw_body=None, body_pruned_at=now)
        )
        await fence(conn, ins_code)
    return {
        "dry_run": not apply,
        "snapshot_rows": snapshot_count,
        "unreferenced_raw_bodies": body_count,
        "protected_evidence": (
            "canonical, revisions, decisions, quarantine, metadata, coverage and latest"
        ),
    }
