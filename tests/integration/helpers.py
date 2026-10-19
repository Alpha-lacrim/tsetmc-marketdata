"""Invented observations for database tests; never live API evidence."""

import copy
import json
from datetime import UTC, datetime

from tsetmc_marketdata.jsonio import loads_source
from tsetmc_marketdata.providers.http_client import JSONResponse

A = "900000000000000001"
B = "900000000000000002"
RECEIPT = datetime(2026, 3, 21, 10, tzinfo=UTC)


def row(code=A, day=20250729, **overrides):
    result = dict(
        insCode=code,
        dEven=day,
        hEven=123000,
        priceYesterday=1000,
        priceFirst=1010,
        pDrCotVal=1030,
        priceMax=1040,
        priceMin=1000,
        pClosing=1020,
        zTotTran=1234,
        qTotTran5J=7000000123,
        qTotCap=7154000125700,
    )
    result.update(overrides)
    return result


class SyntheticSource:
    def __init__(self, code=A, rows=None, current=None):
        self.code = code
        self.rows = rows if rows is not None else [row(code)]
        self.current = current if current is not None else row(code, day=20260321)
        self.target = {}
        self.calls = []
        self.error = None
        self.receipt = RECEIPT

    async def get_json(self, path):
        self.calls.append(path)
        if "GetInstrumentInfo" in path:
            payload = {
                "instrumentInfo": {
                    "insCode": self.code,
                    "lVal18AFC": "SYNTHETIC",
                    "lVal30": "Synthetic company",
                    "instrumentID": "TEST-" + self.code,
                }
            }
        else:
            if self.error:
                raise self.error
            if "DailyList" in path:
                limit = int(path.rsplit("/", 1)[1])
                payload = {"closingPriceDaily": copy.deepcopy(self.rows[: limit or None])}
            elif "GetClosingPriceInfo" in path:
                payload = {"closingPriceInfo": copy.deepcopy(self.current)}
            else:
                day = int(path.rsplit("/", 1)[1])
                payload = {
                    "closingPriceDaily": copy.deepcopy(self.target.get(day, row(self.code, day)))
                }
        raw = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
        return JSONResponse(loads_source(raw), raw, self.receipt, 200, path)
