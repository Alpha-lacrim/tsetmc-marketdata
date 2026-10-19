# TSETMC Market Data — Milestone 2

Independent Python foundation for a TSETMC HTTP/JSON collector and the Go
`ChartData` daily chart contract. Authorized pilot: **فولاد — فولاد مبارکه اصفهان**,
`insCode` **`46348559193224090`** (a string).

Milestone 2 adds independent PostgreSQL 16.1 persistence, Alembic migrations,
historical import/corrections/reconciliation, current snapshots/latest state,
recovery and database-backed ChartData export. TradingView projects and runtime
resources remain completely independent.
Repository: [Alpha-lacrim/tsetmc-marketdata](https://github.com/Alpha-lacrim/tsetmc-marketdata).
This is a development implementation, with no production-readiness claim. Polling
is opt-in and limited to an explicit manual window; no unattended service is enabled.
Automated historical scheduling, durable remote synchronization, company FastAPI
integration and production deployment are not implemented. Only فولاد is live;
schema keys, ownership and reusable collectors already support multiple instruments.

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
Runtime dependencies are httpx, jdatetime, tzdata, SQLAlchemy 2.x, asyncpg and Alembic.
Exact versions are pinned in uv.lock. No third-party market-data client is used.

## Independent local PostgreSQL

Inspect Docker resources and listening ports before choosing a host port. The
following commands create only the `tsetmc-m2-local` project, its `pgdata` volume,
`tsetmc_marketdata` database and separate owner/collector roles. Commands work in
PowerShell and Linux from the checkout root:

```powershell
docker compose ls
docker ps -a
docker volume ls
# Windows: Get-NetTCPConnection -State Listen | Where-Object LocalPort -eq 5542
# Linux: ss -ltn
uv run python scripts/local_db.py init --port 5542
uv run python scripts/local_db.py start
uv run python scripts/local_db.py migrate
uv run python scripts/local_db.py run -- db-status
```

`init` refuses to overwrite existing private configuration. Secrets are randomly
generated in ignored `.local/database.json` and `.local/postgres.env`; restrict
access to these files and keep them with your private backups. The helper supplies
credentials to child environments without printing them. The database is published
only on loopback. Startup and migrations are separate; collectors never migrate.
An existing local installation should start at `db-status`, not rerun `init`.

```powershell
uv run python scripts/local_db.py run -- backfill-history
uv run python scripts/local_db.py run -- refresh-history --source-limit 20
uv run python scripts/local_db.py run -- reconcile-history --date 20250729
uv run python scripts/local_db.py run -- observe-current
uv run python scripts/local_db.py run -- collection-status
uv run python scripts/local_db.py run -- export-db-chartdata --selection accepted-unverified --output output/stored-chartdata.json
uv run python scripts/local_db.py test -- --postgres -q
```

Jobs verify metadata and the configured instrument identifier, then use the same
Milestone 1 client/parsers. `--dry-run` on a one-shot job performs source reads and
validation in a read-only database transaction. `--instrument-config` selects an
extensible JSON configuration; the CLI still authorizes only the live pilot.
`TSETMC_MAX_CONNECTIONS` controls the reusable HTTP pool, and
`TSETMC_PACING_SECONDS` controls request pacing. One instrument has one database
owner, so writes and polling never overlap for that instrument.

**Finality is unverified.** Default database export selects only explicitly finalized
records and currently returns eight empty arrays, with excluded counts in the
report. Use `--selection accepted-unverified` deliberately for accepted source
observations. Reconciliation does not establish candle finality. No automatic
finalization or manual finalization command is implemented.

Live Milestone 2 verification on 2026-10-19 stored **4,662 accepted dates**,
2007-03-11 through 2026-10-18, and one current snapshot. A repeated full audit found
4,662 unchanged records and zero revisions. Unlike the original capture below,
the new list reports July 29 open=2956 and agrees with the dated endpoint. The
original anomaly and its repair were separately reproduced from private captures
in a disposable database. See [actual verification](docs/milestone-2-verification.md).

Polling remains disabled unless explicitly invoked, for example with a short,
future aware `--until` value and `--interval 30`. It uses an operator-selected
window, not a guessed exchange calendar; no full market-session qualification is
claimed. See [operations](docs/collector-operations.md), [schema](docs/database-schema.md),
[current-price policy](docs/current-price-collection.md), and
[backup/recovery](docs/recovery-and-backup.md).

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
asyncio internals and opt-in PostgreSQL tests. Those tests use uniquely named
disposable databases and are skipped by default. The Docker service hostname is
allowed only for explicitly selected database tests. See
[Milestone 1 verification](docs/pilot-verification.md).

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
[architecture](docs/architecture.md), [Milestone 2 design](docs/milestone-2-design.md),
and [next milestone](docs/next-milestones.md).

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
