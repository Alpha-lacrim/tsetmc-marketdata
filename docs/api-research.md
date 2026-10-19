# TSETMC API qualification — 2026-10-19

Base URL: `https://cdn.tsetmc.com/api/`. Only insCode `46348559193224090` was
requested. This research distinguishes our observations from third-party claims.
No bulk-market endpoint was requested, because this milestone authorizes one instrument.

## Observed endpoints

All six project-client qualification requests succeeded with HTTP 200, one attempt
each, about one second apart, on 2026-10-19 11:58 Tehran time. Exact bodies,
SHA-256 and aware UTC receipt times are retained locally in ignored
`docs/evidence/qualification/manifest.json`, excluded from the public repository
because redistribution permission has not been established. These historical
observations are a qualification report, not publicly bundled capture evidence.

| Path after /api/ | Envelope and observed result |
|---|---|
| Instrument/GetInstrumentInfo/46348559193224090 | `instrumentInfo`: object; expected symbol/company and identity |
| ClosingPrice/GetClosingPriceDailyList/46348559193224090/0 | `closingPriceDaily`: array, 4,661 rows |
| ClosingPrice/GetClosingPriceDailyList/46348559193224090/1 | same array, 1 row, equals latest /0 row |
| ClosingPrice/GetClosingPriceDailyList/46348559193224090/2 | same array, 2 rows, equals latest two /0 rows |
| ClosingPrice/GetClosingPriceInfo/46348559193224090 | `closingPriceInfo`: object, current source date 20261019 |
| ClosingPrice/GetClosingPriceDaily/46348559193224090/20261018 | `closingPriceDaily`: **object**, equals latest list row |

A seventh targeted probe of `/GetClosingPriceDaily/46348559193224090/20250729`
also succeeded; its `priceFirst=2956` contradicts list `priceFirst=0`. The other
measurements match. Both original bodies are retained privately locally; the parser quarantines
the list row and never silently substitutes a correction.

**History parameter:** observations confirm `1` and `2` limit the number of newest
rows, and `0` returns a much larger available-history set (4,661 dates from
2007-03-11 to 2026-10-18, strictly descending, no duplicate days). This agrees
with the 5j9 client describing `0` as all and n as days. It does **not** prove the
exchange's archive is complete or that every returned date had trades: 414 rows
have zero count and volume. No pagination, maximum n, negative values, invalid
instrument behavior or server-side retention guarantees were probed. The observed
set excludes the current 2026-10-19 session; do not infer an invariant completion
flag from this single capture.

## Response fields and uncertainties

Daily source keys observed: `priceChange`, `priceMin`, `priceMax`, `priceYesterday`,
`priceFirst`, `last`, `id`, `insCode`, `dEven`, `hEven`, `pClosing`, `iClose`,
`yClose`, `pDrCotVal`, `zTotTran`, `qTotTran5J`, `qTotCap`.
Prices/volume/value/count are JSON numbers, not display abbreviations. `dEven`,
`hEven`, `id` are integers, insCode is a string, and the three flags are booleans.
Decimal decoder types do not imply the source sent numeric strings. The complete
mapping/calculation policy, with a clearly labeled synthetic example, is in [field-mapping.md](field-mapping.md).

Current adds `instrumentState`, `instrument`, `lastHEven`, `finalLastDate`, `nvt`,
`mop`, `pRedTran`, `thirtyDayClosingHistory`. The capture has `insCode="0"`,
`instrument=null`, and nested state insCode null. Identity therefore comes from
the requested endpoint plus separately verified metadata, with a model diagnostic.
Nonzero mismatches are rejected. `dEven/hEven` is exposed as a source-reported
clock, not necessarily the exact last trade's timestamp. `lastHEven` and
`finalLastDate` are retained without using them to override that clock.
State fields include `cEtaval="A "` and `cEtavalTitle="مجاز"`.

Metadata includes `lVal18AFC`, `lVal30`, `insCode`, `instrumentID`, `cIsin`, `flow`,
`baseVol`, `zTitad`, sector/staticThreshold objects, EPS and other raw fields.
The captured company uses Arabic ك; identity validation normalizes ك/ک, ي/ی,
whitespace and zero-width join spacing for comparison only. Original text survives.

`last` is boolean, never a price. `priceChange` is not universally either required
change calculation. `iClose/yClose/id` meanings are unverified. Official close
falls outside a positive executed-trade range in 285 rows, so enforcing an OHLC
close-within-range invariant would reject genuine source data. Exact closing
formula, historical base-volume rules, price units/corporate-action adjustment
details and session states require further source qualification. No reconstruction
or adjustment is performed in Milestone 1.

## Access results

The preliminary standard-library urllib probes of metadata, /2 history and current
returned HTTP 403; the original failure manifest remains private locally under `docs/evidence/preliminary/`.
A web retrieval tool also failed to retrieve the source. The later normal,
configured httpx client succeeded; the reason for the differing results was not
isolated. The client disables inherited HTTP environment configuration, verifies
TLS, uses one fixed URL and does not rotate IPs, proxies or identities. Success
here does not guarantee availability from every network or at later times.

## Reference review and licensing

The following projects were inspected for endpoint names, response shapes and
architecture. Reference revision metadata remains private locally with the
qualification evidence. Public source links below identify the reviewed projects.
No source code, fixtures or runtime dependency from these projects was copied.

| Reference | Useful observations | License observed |
|---|---|---|
| [5j9/tsetmc](https://github.com/5j9/tsetmc), [instrument source](https://github.com/5j9/tsetmc/blob/main/tsetmc/instruments.py) | async endpoint wrappers, limit argument, daily/current object shapes, state/trade/book routes | GPL-3.0 |
| [Glyphack/pytse-client](https://github.com/Glyphack/pytse-client), [endpoint settings](https://github.com/Glyphack/pytse-client/blob/master/pytse_client/tse_settings.py) | metadata, dated trade/order-book routes; combines older HTTP/HTML sources and newer API routes | GPL-3.0 |
| [yghaderi/oxtapus](https://github.com/yghaderi/oxtapus), [inventory](https://github.com/yghaderi/oxtapus/blob/master/docs/development/tsetmc-api-inventory.md) | endpoint evidence classification; separate official close/last price and raw lineage | MIT |
| [TradingView reference](https://github.com/Alpha-lacrim/tradingview-marketdata) | conceptual split of history/latest state, idempotency and recovery; no runtime reuse | no code reused |

Reference assertions labeled 'verified' describe their own investigations, not
ours. 5j9's days terminology must not be read as 'days with trades'; zero-activity
rows were observed here. The targeted/list opening discrepancy is an observed
source inconsistency, not evidence that any reference implementation caused it.
No third-party documented guarantee of equivalence/completeness was established.
Some references use `http://` routes or float-oriented tabular models; this project
uses HTTPS by default and Decimal internally. No incompatible licensing obligation
is introduced by linking research references; the new code has no chosen public
distribution license yet, pending the owner's publication decision.

## Tentative future endpoints — documented, no collectors implemented

These are route families found in the reference clients/inventory, **not live
qualified here**. Parameter suffixes marked candidate need confirmation.

| Route | Future role / qualification needed |
|---|---|
| ClosingPrice/GetMarketWatch | bulk latest snapshots for efficient scaling; filters, identity and short field names must be mapped before use |
| ClosingPrice/GetPriceAdjustList/{insCode} (candidate suffix) | corporate-action/adjustment evidence; do not overwrite raw prices with adjusted series |
| ClosingPrice/GetPriceAdjustByFlow/… | possible bulk adjustment acquisition; arguments unverified |
| ClosingPrice/GetInstrumentCalendar/{insCode} (candidate suffix) | possible per-instrument session/coverage context; calendar meaning unverified |
| MarketData/GetInstrumentState/{insCode}/{date} | dated instrument-state history; distinguishes suspension from unknown gaps |
| MarketData/GetMarketOverview/1 | market-level state, not a per-instrument historical holiday calendar |
| MarketData/GetInstrumentStateAll/… and GetInstrumentStateTop/… | candidate bulk/state routes; arguments unverified |
| Trade/GetTrade/{insCode} | latest trades; no tick collector in this milestone |
| Trade/GetTradeHistory/{insCode}/{date}/true | dated trades; boolean meaning/corrections/sequence completeness unverified |
| BestLimits/{insCode} and BestLimits/{insCode}/{date} | latest/daily order-book snapshots; no order-book collector |
| ClosingPrice/GetClosingPriceHistory/{insCode}/{date} | intraday aggregate evolution, not completed daily candles |
| ClosingPrice/GetClosingPriceDailyListCSV/…; Trade/GetTradeIntraDayCSV/… | possible larger acquisitions; format/arguments unqualified |

No historical gaps are classified as missing sessions without calendar and state
evidence. Broader acquisition is deferred, including every other instrument.
