"""Synthetic operator confirmation remains local, reversible and correction-aware."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa

from tsetmc_marketdata.storage import schema_v1 as t
from tsetmc_marketdata.storage import schema_v3a as s
from tsetmc_marketdata.storage.queries import read_daily, retain
from tsetmc_marketdata.storage.repository import Repository
from tsetmc_marketdata.storage.reviews import review_daily

from .helpers import A, B, SyntheticSource
from .test_persistence import count, ingest

pytestmark = pytest.mark.postgres
DAY = date(2025, 7, 29)
SESSION_END = datetime(2025, 7, 29, 10, tzinfo=UTC)
NOW = datetime(2025, 7, 30, 10, tzinfo=UTC)


async def evidence(db):
    source = SyntheticSource()
    source.receipt = SESSION_END + timedelta(minutes=1)
    await ingest(db, source)
    source.receipt += timedelta(hours=2)
    await ingest(db, source)
    async with db.read() as conn:
        identities = list(
            await conn.scalars(
                sa.select(t.observations.c.observation_id)
                .where(
                    t.observations.c.ins_code == A, t.observations.c.endpoint.contains("DailyList")
                )
                .order_by(t.observations.c.observation_id)
            )
        )
        digest = await conn.scalar(
            sa.select(t.daily.c.financial_hash).where(t.daily.c.ins_code == A)
        )
    return source, dict(
        review_id=uuid4(),
        day=DAY,
        expected_hash=digest,
        action="confirm",
        actor="synthetic-operator",
        reason="Synthetic manual review",
        now=NOW,
        first_observation_id=identities[0],
        second_observation_id=identities[1],
        session_end=SESSION_END,
        session_evidence="Invented session completion",
    )


async def test_confirmation_replay_revoke_and_late_correction(pg_database):
    db, _ = pg_database
    source, args = await evidence(db)
    async with db.read() as conn:
        records, _ = await read_daily(conn, A)
        assert records == []  # Ingestion alone never finalizes, even after repeated observations.
    async with db.owner(A) as conn:
        result = await review_daily(Repository(conn, A), **args)
        assert result["finalization_state"] == "operator_finalized"
        assert (await review_daily(Repository(conn, A), **args))["replayed"]
    async with db.read() as conn:
        assert len((await read_daily(conn, A))[0]) == 1
    # Later ordinary financial correction resets local confirmation; old review remains evidence.
    source.rows[0]["pClosing"] = 1021
    assert (await ingest(db, source))["corrected"] == 1
    assert (await ingest(db, source))["unchanged"] == 1
    async with db.read() as conn:
        assert (await read_daily(conn, A))[0] == []
        assert await conn.scalar(sa.select(sa.func.count()).select_from(s.reviews)) == 1
        assert await conn.scalar(sa.select(sa.func.count()).select_from(t.revisions)) == 1
    # Another explicit review ID can revoke local confirmation without changing financial data.
    async with db.owner(A) as conn:
        digest = await conn.scalar(
            sa.select(t.daily.c.financial_hash).where(t.daily.c.ins_code == A)
        )
        await conn.commit()
        await review_daily(
            Repository(conn, A),
            **{
                **args,
                "review_id": uuid4(),
                "expected_hash": digest,
                "action": "revoke",
            },
        )
    assert await count(db, t.revisions) == 1


@pytest.mark.parametrize(
    "override",
    [
        {"first_observation_id": None},
        {"second_observation_id": None},
        {"expected_hash": "wrong"},
        {"session_evidence": ""},
        {"grace_seconds": 7201},
        {"now": datetime(2025, 7, 29, 14, tzinfo=UTC)},
    ],
)
async def test_unqualified_or_premature_confirmation_is_rejected(pg_database, override):
    db, _ = pg_database
    _, args = await evidence(db)
    async with db.owner(A) as conn:
        with pytest.raises(ValueError):
            await review_daily(Repository(conn, A), **{**args, **override})
    async with db.read() as conn:
        assert await conn.scalar(sa.select(t.daily.c.finalization_state)) == "source_unverified"
        assert await conn.scalar(sa.select(sa.func.count()).select_from(s.reviews)) == 0


async def test_review_identity_and_protected_evidence_are_instrument_scoped(pg_database):
    db, _ = pg_database
    _, args = await evidence(db)
    other = SyntheticSource(B)
    await ingest(db, other)
    async with db.owner(B) as conn:
        b_hash = await conn.scalar(
            sa.select(t.daily.c.financial_hash).where(t.daily.c.ins_code == B)
        )
        await conn.commit()
        with pytest.raises(ValueError, match="another instrument"):
            await review_daily(Repository(conn, B), **{**args, "expected_hash": b_hash})
    async with db.owner(A) as conn:
        await review_daily(Repository(conn, A), **args)
        async with conn.begin():
            await retain(conn, A, apply=True, now=datetime(2027, 1, 1, tzinfo=UTC))
    async with db.read() as conn:
        for identity in (args["first_observation_id"], args["second_observation_id"]):
            assert (
                await conn.scalar(
                    sa.select(t.observations.c.raw_body).where(
                        t.observations.c.observation_id == identity
                    )
                )
                is not None
            )
        assert (
            await conn.scalar(
                sa.select(t.daily.c.finalization_state).where(t.daily.c.ins_code == B)
            )
            == "source_unverified"
        )
