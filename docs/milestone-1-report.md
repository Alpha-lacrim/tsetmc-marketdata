# Milestone 1 baseline preservation report

This independent Python project implements the completed Milestone 1 foundation.
The owner subsequently authorized public publication under
[Alpha-lacrim/tsetmc-marketdata](https://github.com/Alpha-lacrim/tsetmc-marketdata)
and the annotated development tag `v0.1.0-milestone1`. This is not a production
release. The complete [file inventory](file-inventory.md), [publication audit](publication-audit.md)
and [publication verification](publication-verification.md) describe the public baseline.

## Preserved implementation

The original runtime source and qualification script are unchanged: bounded async
HTTP transport, structured errors, lossless numeric decoding, typed financial
models, daily/current/metadata parsing, quarantine, all 14 calculations/mappings,
Gregorian/Jalali conversion, timezone policy, ChartData and CLI remain intact.
Dependencies are pinned in uv.lock. Python 3.12 is the development baseline.

`pDrCotVal` remains last traded price; `pClosing` remains official close. The Go
contract remains a=time, b=open, c=official close, d=high, e=low, f=count, g=volume,
h=value, with an optional legacy i:null. Exact source decimals remain internal;
float64-compatible numeric serialization occurs only at the frontend boundary.

## Historical findings retained

The original live metadata qualified فولاد, فولاد مبارکه اصفهان, string insCode
46348559193224090 and instrument ID IRO1FOLD0001. The investigation retrieved
4,661 distinct history dates spanning 2007-03-11–2026-10-18, accepted 4,660 and
quarantined one. For 2025-07-29, list priceFirst=0 disagreed with the targeted
endpoint's priceFirst=2956. There were 285 positive-trade records with official
close outside the executed range. Current-price retrieval also succeeded.
These findings do not establish archive completeness. Details and limitations are
in [pilot-verification.md](pilot-verification.md) and [api-research.md](api-research.md).

## Publication-only changes

Genuine captures, derived evidence and original reports remain private locally
because redistribution permission has not been established. They are ignored,
not deleted or relabeled. Public fixtures/examples are synthetic and labeled.
Seven capture regressions skip when the private set is absent; the dated CLI
smoke test uses a synthetic daily fixture. Documentation uses repository-relative
paths, distinguishes historical live findings from public offline tests, and
removes obsolete statements that publication was unauthorized. Minimal offline
GitHub Actions checks require no source API access, secrets, database or deployment.
No software license was added.

## Run the baseline

```powershell
git clone https://github.com/Alpha-lacrim/tsetmc-marketdata.git
cd tsetmc-marketdata
uv sync --locked
uv run --offline pytest
uv run --offline python -m tsetmc_marketdata.cli export-chartdata --input tests/fixtures/synthetic-history.json --output output/chartdata.json
```

## Next milestone remains a proposal

[Milestone 2 design](next-milestones.md) specifies isolated PostgreSQL tables,
indexes, daily uniqueness/revisions, source discrepancy reconciliation, historical
ingestion, current snapshots, status/coverage and crash/restart recovery tests.
None of those capabilities has been implemented. TradingView and the company
FastAPI/database/runtime remain separate and untouched.
