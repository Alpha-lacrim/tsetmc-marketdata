# TSETMC Market Data — Milestone 1

Independent Python foundation for a TSETMC HTTP/JSON collector and the Go
`ChartData` daily chart contract. Authorized pilot: **فولاد — فولاد مبارکه اصفهان**,
`insCode` **`46348559193224090`** (a string).

No database, migrations, containers, polling service, synchronization, or FastAPI
integration exists here. TradingView projects and runtime resources are independent.
Repository: [Alpha-lacrim/tsetmc-marketdata](https://github.com/Alpha-lacrim/tsetmc-marketdata).
This is a development baseline, with no production-readiness claim. PostgreSQL
persistence, continuous price collection, automated historical backfill, durable
synchronization, company FastAPI integration and production deployment are planned
work and are not implemented.

## Setup

Python 3.12 and [uv](https://docs.astral.sh/uv/) are used. Windows PowerShell:

```powershell
git clone https://github.com/Alpha-lacrim/tsetmc-marketdata.git
cd tsetmc-marketdata
uv sync --locked
uv run python -m tsetmc_marketdata.cli --help
$env:TSETMC_READ_TIMEOUT = "15"
$env:TSETMC_PACING_SECONDS = "1"
```

Linux, after installing Python/uv:

```bash
git clone https://github.com/Alpha-lacrim/tsetmc-marketdata.git
cd tsetmc-marketdata
uv sync --locked
export TSETMC_READ_TIMEOUT=15
uv run python -m tsetmc_marketdata.cli --help
```

PyCharm: select `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on
Linux. `.env.example` documents every variable; `.env` files are **not** loaded
automatically. Export values in the shell or configure PyCharm's environment.
`uv pip install .` also installs the package; `tsetmc-marketdata` is the console command.
Runtime dependencies are httpx, jdatetime (presentation calendar), and tzdata
(portable IANA zones, including Windows). No third-party market-data client is used.

## Offline verification

After dependency installation, all default tests work without internet. A socket
guard prevents accidental network calls. `--offline` also prevents uv package access:

```powershell
uv run --offline pytest
uv run --offline ruff check .
uv run --offline ruff format --check .
uv run --offline mypy
```

Public tests use MockTransport and explicitly labeled synthetic fixtures. Seven
additional capture regressions run only when the original private capture set is
present; otherwise they are explicitly skipped. The three live tests are also
skipped by default. Synthetic tests do not prove historical source behavior.
External DNS/connections are blocked; loopback sockets are allowed for Windows
asyncio internals. See [verification](docs/pilot-verification.md).

## Explicit live probes

Each command makes one logical read-only request, at most three attempts by default
(403/401 are never retried), with phase timeouts and a 90-second total deadline.
Use `--retries 0 --timeout 25` for a single bounded attempt. No polling starts.

```powershell
uv run python -m tsetmc_marketdata.cli probe-instrument --ins-code 46348559193224090 --retries 0 --report output/instrument-report.json --raw-output output/instrument.json
uv run python -m tsetmc_marketdata.cli probe-history --ins-code 46348559193224090 --retries 0 --report output/history-report.json --raw-output output/history.json
uv run python -m tsetmc_marketdata.cli probe-current --ins-code 46348559193224090 --retries 0 --report output/current-report.json --raw-output output/current.json
uv run python -m tsetmc_marketdata.cli inspect-fields --input output/history.json
```

Live qualification on 2026-10-19 succeeded through the project client: metadata
verified فولاد, `/0` returned 4,661 rows (2007-03-11–2026-10-18), and `/1` and `/2`
returned the latest one/two rows. Preliminary urllib attempts returned HTTP 403;
the cause of the differing access results was not isolated. `/0` requests the
available archive; it is not a proof of complete exchange history. `--source-limit`
passes the source parameter explicitly. No access-restriction bypass is implemented.

One list row (2025-07-29) has open=0 despite positive trading activity and is
quarantined. A targeted request returns open=2956 for the same date. Both captures
are retained privately locally. The original pilot also found 285 positive-trade
records whose official close is outside the executed trading range. To inspect
the dated endpoint explicitly:

```powershell
uv run python -m tsetmc_marketdata.cli probe-daily --date 20250729 --retries 0 --raw-output output/daily-20250729.json
```

For a bounded five-request qualification plus one latest-date reconciliation if
history succeeds:

```powershell
uv run python scripts/qualify_source.py --output output/qualification
uv run pytest -m live --live
```

The live tests are separate and opt-in. They make no requests during default tests.
Exact successful JSON bodies are saved unchanged; sidecars/manifests record UTC
receipt times and SHA-256. Failed requests produce safe status/error diagnostics.
HTTP environment proxies, cookies and credentials are not inherited. TLS is verified.

## Export frontend JSON

```powershell
# Offline, using a saved raw response (synthetic demonstration included):
uv run python -m tsetmc_marketdata.cli export-chartdata --input tests/fixtures/synthetic-history.json --output output/chartdata.json
# Live, one request:
uv run python -m tsetmc_marketdata.cli export-chartdata --ins-code 46348559193224090 --output output/chartdata.json --raw-output output/history.json --allow-partial --report output/export-report.json
# Append the undocumented legacy sample key i:null only when needed:
uv run python -m tsetmc_marketdata.cli export-chartdata --input tests/fixtures/synthetic-history.json --output output/chartdata-legacy.json --legacy-sample
```

Canonical mapping: `a` Unix seconds, `b` open, `c` **official close**, `d` high,
`e` low, `f` trade count, `g` **volume**, `h` **value**. Arrays are chronological
and equal length. Empty results produce eight empty arrays. Missing OHLC prevents
export; missing activity remains null internally and becomes a documented zero
placeholder at this boundary only. Conflicting dates are quarantined; export
requires explicit `--allow-partial` if any rows were rejected. Exit codes: 0 success,
1 request/schema/input failure, 2 historical quarantine, 130 cancellation.

The pure adapter is `tsetmc_marketdata.adapters.chartdata.to_chartdata(records)`.
Models retain exact decimals and raw source fields; frontend prices, volume and
value become finite float64-compatible JSON numbers. Diagnostic/model JSON uses
decimal strings to preserve precision. This differs intentionally from ChartData,
which always uses numeric JSON values.

## Price, time and data accuracy

`pDrCotVal` is last traded price; `pClosing` is official closing measurement.
Current output exposes both, source state/date/time and HTTP receipt time separately.
An unchanged observation or a new receipt time does not prove a new trade. The
endpoint can return an older session. No previous close is substituted as a latest
trade. A source `insCode` of zero/absent on current data is explicitly flagged and
bound to the requested endpoint; real mismatches fail validation.

Canonical trading dates are Gregorian dates. Jalali conversion is presentation only.
Daily chart timestamps use **00:00:00 UTC on that Gregorian date**, a date label,
not an observed trading instant. Source current clocks are interpreted in
`Asia/Tehran` and converted to aware UTC; receipt timestamps are separate aware UTC
instants. No dates are filled, and calendar gaps imply no claim about trading sessions.
See [timestamp and frontend details](docs/frontend-contract.md),
[14-column mapping](docs/field-mapping.md), [API research](docs/api-research.md),
[architecture](docs/architecture.md), and [Milestone 2 proposal](docs/next-milestones.md).

## Publication and licensing

Genuine TSETMC captures, derived financial exports, qualification logs and local
audit backups are excluded from Git and package distributions. Source-data
redistribution permission has not been established. This public repository retains
the historical findings as a report and includes only clearly labeled synthetic
fixtures/examples; it does not bundle the original historical archive.

No software license has been selected by the owner. Public visibility does not
itself grant a license to reuse the code or source data. No third-party market-data
client implementation was copied. See [publication audit](docs/publication-audit.md),
[fixture provenance](tests/fixtures/README.md), [synthetic examples](examples/README.md)
and the [Milestone 1 report](docs/milestone-1-report.md). The
`v0.1.0-milestone1` tag marks this development baseline, not a production release.
