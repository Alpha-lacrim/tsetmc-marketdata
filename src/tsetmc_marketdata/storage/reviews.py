"""Single-date operator confirmation, anchored to immutable financial hashes and evidence."""

import hashlib
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from tsetmc_marketdata.collection.sessions import aware
from tsetmc_marketdata.jsonio import loads_source
from tsetmc_marketdata.parsing import parse_history, parse_targeted_daily
from tsetmc_marketdata.storage import schema_v1 as t
from tsetmc_marketdata.storage import schema_v3a as s
from tsetmc_marketdata.storage.repository import Repository
from tsetmc_marketdata.storage.serialization import canonical_hash, financial_state


async def review_daily(
    repo: Repository,
    *,
    review_id: UUID,
    day: date,
    expected_hash: str,
    action: str,
    actor: str,
    reason: str,
    now: datetime,
    first_observation_id: int | None = None,
    second_observation_id: int | None = None,
    session_end: datetime | None = None,
    session_evidence: str | None = None,
    grace_seconds: int = 3600,
) -> dict[str, Any]:
    now = aware(now)
    if action not in {"confirm", "revoke"} or not actor.strip() or not reason.strip():
        raise ValueError("review requires explicit action, actor and reason")
    if not 3600 <= grace_seconds <= 31 * 86400:
        raise ValueError("operator confirmation grace must be at least one hour")
    values = dict(
        review_id=review_id,
        ins_code=repo.ins_code,
        trading_date=day,
        financial_hash=expected_hash,
        action=action,
        actor=actor,
        reason=reason,
        first_observation_id=first_observation_id,
        second_observation_id=second_observation_id,
        session_end=aware(session_end) if session_end else None,
        session_evidence=session_evidence,
        grace_seconds=grace_seconds,
    )
    async with repo.atomic(ingest=True):
        previous = (
            (
                await repo.conn.execute(
                    sa.select(s.reviews).where(s.reviews.c.review_id == review_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if previous:
            if any(previous[k] != value for k, value in values.items()):
                raise ValueError("review ID belongs to a different review")
            return {"review_id": str(review_id), "replayed": True, "source_finality": "unproven"}
        record = (
            (
                await repo.conn.execute(
                    sa.select(t.daily)
                    .where(t.daily.c.ins_code == repo.ins_code, t.daily.c.trading_date == day)
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )
        if record is None or record["financial_hash"] != expected_hash:
            raise ValueError("review must match the current accepted financial hash")
        if action == "confirm":
            if day >= now.astimezone(ZoneInfo("Asia/Tehran")).date():
                raise ValueError("confirmation requires a prior Tehran calendar date")
            if session_end is None or not session_evidence or not session_evidence.strip():
                raise ValueError("explicit session-completion evidence is required")
            if (
                aware(session_end) >= now
                or aware(session_end).astimezone(ZoneInfo("Asia/Tehran")).date() != day
            ):
                raise ValueError("session completion must belong to the reviewed trading date")
            if (
                not first_observation_id
                or not second_observation_id
                or (first_observation_id == second_observation_id)
            ):
                raise ValueError("two distinct retained source observations are required")
            pending = await repo.conn.scalar(
                sa.select(sa.func.count())
                .select_from(t.quarantine)
                .where(
                    t.quarantine.c.ins_code == repo.ins_code,
                    t.quarantine.c.trading_date == day,
                    t.quarantine.c.record_kind == "daily",
                    t.quarantine.c.status == "open",
                )
            )
            if pending:
                raise ValueError("unresolved daily quarantine prevents confirmation")
            receipts = []
            for identity in (first_observation_id, second_observation_id):
                source = (
                    (
                        await repo.conn.execute(
                            sa.select(t.observations).where(
                                t.observations.c.ins_code == repo.ins_code,
                                t.observations.c.observation_id == identity,
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if source is None or source["raw_body"] is None or source["received_at"] is None:
                    raise ValueError(
                        "review evidence is unavailable or belongs to another instrument"
                    )
                if hashlib.sha256(source["raw_body"]).hexdigest() != source["raw_sha256"] or not (
                    source["http_status"] is not None and 200 <= source["http_status"] < 300
                ):
                    raise ValueError("review source evidence integrity check failed")
                payload = loads_source(source["raw_body"])
                if "GetClosingPriceDailyList/" in source["endpoint"]:
                    candidates = [
                        r
                        for r in parse_history(payload, repo.ins_code).records
                        if r.trading_date == day
                    ]
                    candidate = candidates[0] if candidates else None
                elif "GetClosingPriceDaily/" in source["endpoint"]:
                    candidate = parse_targeted_daily(payload, repo.ins_code, day)
                else:
                    raise ValueError("daily source evidence is required")
                if candidate is None or canonical_hash(financial_state(candidate)) != expected_hash:
                    raise ValueError(
                        "both source observations must confirm the reviewed financial hash"
                    )
                receipts.append(source["received_at"])
            if (
                receipts[0] < aware(session_end)
                or receipts[1] > now
                or (receipts[1] - receipts[0] < timedelta(seconds=grace_seconds))
            ):
                raise ValueError("post-session rechecks must be separated by the publication grace")
        await repo.conn.execute(s.reviews.insert().values(**values, reviewed_at=now))
        state = "operator_finalized" if action == "confirm" else "source_unverified"
        await repo.conn.execute(
            t.daily.update()
            .where(t.daily.c.ins_code == repo.ins_code, t.daily.c.trading_date == day)
            .values(finalization_state=state)
        )
        repo.publication_days.add(day)
        repo.publication_reviews[day] = review_id
    return {
        "review_id": str(review_id),
        "finalization_state": state,
        "source_finality": "unproven",
        "policy": "operator_review_v1",
    }
