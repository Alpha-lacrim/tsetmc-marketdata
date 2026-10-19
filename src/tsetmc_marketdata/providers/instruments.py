"""Metadata identity qualification, scoped to the authorized pilot."""

from tsetmc_marketdata.config import require_pilot
from tsetmc_marketdata.models.instrument import Instrument
from tsetmc_marketdata.parsing import parse_instrument
from tsetmc_marketdata.providers.http_client import JSONResponse, TSETMCClient


async def fetch_instrument(client: TSETMCClient, ins_code: str) -> tuple[Instrument, JSONResponse]:
    require_pilot(ins_code)
    response = await client.get_json(f"Instrument/GetInstrumentInfo/{ins_code}")
    return parse_instrument(response.payload, ins_code), response
