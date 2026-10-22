"""Discover primary ordinary-share IDs; market-watch prices are not ingestion input."""

import re
from typing import Any

from tsetmc_marketdata.config import validate_ins_code
from tsetmc_marketdata.errors import ErrorKind, SourceDataError
from tsetmc_marketdata.providers.http_client import TSETMCClient


def share_codes(payload: dict[str, Any]) -> list[str]:
    rows = payload.get("marketwatch")
    if not isinstance(rows, list):
        raise SourceDataError(ErrorKind.SCHEMA, "marketwatch must be a list")
    selected: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise SourceDataError(ErrorKind.SCHEMA, "marketwatch row must be an object")
        # Observed ordinary-share families and primary trading lines only. Other
        # products/secondary lines remain separate; never merge by display name.
        if type(row.get("yVal")) is not int or row["yVal"] not in {300, 303, 309, 313}:
            continue
        instrument_id = row.get("insID")
        if not isinstance(instrument_id, str) or not re.fullmatch(
            r"IRO[1357][A-Z0-9]{4}0001", instrument_id
        ):
            continue
        try:
            value = row.get("insCode")
            if not isinstance(value, str):
                raise ValueError("insCode must be text")
            code = validate_ins_code(value)
        except ValueError as error:
            raise SourceDataError(ErrorKind.INVALID_RECORD, "invalid discovery insCode") from error
        if code == "0" or code in selected:
            raise SourceDataError(ErrorKind.INVALID_RECORD, "zero or duplicate discovery insCode")
        selected[code] = instrument_id
    if not selected:
        raise SourceDataError(
            ErrorKind.NOT_FOUND, f"no primary shares discovered from {len(rows)} marketwatch rows"
        )
    return sorted(selected)


async def discover_shares(client: TSETMCClient) -> list[str]:
    response = await client.get_json("ClosingPrice/GetMarketWatch")
    return share_codes(response.payload)
