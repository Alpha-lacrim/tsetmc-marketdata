"""A targeted endpoint cannot arbitrarily arbitrate two individually valid rows."""

from datetime import date

import pytest
import sqlalchemy as sa

from tsetmc_marketdata.storage import schema_v1 as t

from .helpers import A, SyntheticSource, row
from .test_persistence import count, ingest

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("canonical_exists", [False, True])
async def test_valid_quarantined_disagreement_stays_visible(pg_database, canonical_exists):
    db, _ = pg_database
    source = SyntheticSource()
    if canonical_exists:
        await ingest(db, source)
    source.rows = [row(pClosing=1020), row(pClosing=1022)]
    result = await ingest(db, source)
    assert result["quarantined"] == 2
    resolved = await ingest(db, source, "reconcile-history", dates=[date(2025, 7, 29)])
    assert resolved["unresolved"] == 1 and resolved["reconciled"] == 0
    assert await count(db, t.daily) == int(canonical_exists)
    async with db.read() as conn:
        assert (
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(t.quarantine)
                .where(t.quarantine.c.ins_code == A, t.quarantine.c.status == "resolved")
            )
            == 0
        )
