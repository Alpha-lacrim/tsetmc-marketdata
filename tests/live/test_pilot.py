"""Opt-in source qualification; never silently treat source denial as a pass."""

import pytest

from tsetmc_marketdata.config import PILOT_INS_CODE, Settings
from tsetmc_marketdata.providers.closing_prices import fetch_current, fetch_history
from tsetmc_marketdata.providers.http_client import TSETMCClient
from tsetmc_marketdata.providers.instruments import fetch_instrument

pytestmark = pytest.mark.live


async def test_live_pilot_identity():
    async with TSETMCClient(Settings(max_retries=0, total_timeout=25)) as client:
        instrument, _ = await fetch_instrument(client, PILOT_INS_CODE)
    assert instrument.symbol.strip() == "فولاد"


async def test_live_history_shape():
    async with TSETMCClient(Settings(max_retries=0, total_timeout=25)) as client:
        history, _ = await fetch_history(client, PILOT_INS_CODE, source_limit=2)
    assert history.records and not history.has_errors


async def test_live_current_shape():
    async with TSETMCClient(Settings(max_retries=0, total_timeout=25)) as client:
        current, _ = await fetch_current(client, PILOT_INS_CODE)
    assert current.received_at is not None
