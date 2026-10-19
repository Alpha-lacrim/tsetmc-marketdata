# Historical فولاد pilot qualification

The original Milestone 1 live investigation was performed on 2026-10-19 using
Python 3.12.7 and the independent httpx client on Windows. The findings below are
a historical report, not claims established by the public synthetic fixtures.
Original genuine responses, receipt manifests, hashes and detailed model exports
remain preserved locally under ignored `docs/evidence/`, and are excluded from
Git and distributions because source-data redistribution permission is unresolved.

## Identity and history

Metadata resolved string insCode `46348559193224090` to **فولاد**, company
**فولاد مبارکه اصفهان**, instrument ID `IRO1FOLD0001`, cIsin `IRO1FOLD0009`.
The source used Arabic ك; comparison normalizes text without changing raw metadata.

The `/0` history request returned **4,661 distinct dates**, strictly descending,
from **2007-03-11 through 2026-10-18**. `/1` and `/2` equaled the latest one and
two list rows. This establishes the observed row-limit behavior, not completeness
of the exchange archive or a guarantee that every calendar/session date is present.

Validation accepted **4,660** rows and quarantined **one**, dated **2025-07-29**.
The list reported `priceFirst=0` despite positive activity and a positive trading
range. A separate targeted daily request reported `priceFirst=2956`; other fields
agreed. Both originals remain unchanged locally. The list row is still explicitly
quarantined; the targeted result does not silently replace it.

The investigation also counted **285 positive-trade records** whose official close
was outside the executed-trade range, and 414 source-provided zero-count/zero-volume
rows. These observations justify keeping official close separate from last traded
price and avoiding fabricated calendar fills. Operational flags and `priceChange`
were not accepted as substitutes for measured prices or the required calculations.

## Current-price qualification

The current endpoint succeeded and parsed last traded price, official/current close,
previous close, opening/high/low, count, volume, value, state, source date/time and
HTTP receipt separately. The captured top-level insCode was "0" and nested identity
was null, so the model explicitly binds that response to the requested endpoint
after independent metadata qualification. Nonzero identity mismatches are rejected.
Receipt times do not prove new trades, and source clocks do not become daily candle
timestamps. The original snapshot values and receipt evidence remain private locally.

## Public reproducibility and original verification

All 14 mappings and calculations are defined in [field-mapping.md](field-mapping.md).
The public numerical examples there and in `examples/` are explicitly synthetic.
The exact [Go frontend contract](frontend-contract.md), UTC-midnight daily date
labels, f=count/g=volume/h=value, optional i:null and null/placeholder policies are
unchanged. No synthetic fixture is offered as independent live-source evidence.

Before publication cleanup, the original local suite recorded **139 offline tests
passed**, with **3 live tests skipped by default**; those same three opt-in live
tests also passed when run separately. Ruff, formatting, strict mypy, builds and
an independent wheel installation/export passed. Current publication checks,
including a snapshot without private captures, are recorded separately in
[publication-verification.md](publication-verification.md). Seven genuine-capture
regressions remain available locally and skip transparently in a public clone.

To replay public synthetic inputs without network access:

```powershell
uv run --offline python -m tsetmc_marketdata.cli probe-history --input tests/fixtures/synthetic-history.json
uv run --offline python -m tsetmc_marketdata.cli probe-daily --date 20260321 --input tests/fixtures/synthetic-daily.json
uv run --offline python -m tsetmc_marketdata.cli export-chartdata --input tests/fixtures/synthetic-history.json --output output/chartdata.json
```

The original full-history export accepted 4,660 rows only with explicit
`--allow-partial`, disclosed the quarantined date, and used no unknown-activity
placeholders in f/g/h for that capture. That source-derived export remains private.

## Remaining qualification limits

Preliminary urllib requests returned HTTP 403 while subsequent configured httpx
requests succeeded; the cause was not isolated. Exact exchange closing formulas,
calendar/state meanings, historical adjustment details, archive completeness,
flag meanings and future availability remain unverified beyond the observations
reported. The list/targeted discrepancy awaits explicit durable reconciliation in
a future task. No TradingView resource, database, deployment or company FastAPI
implementation was changed. No Milestone 2 feature has been implemented.
