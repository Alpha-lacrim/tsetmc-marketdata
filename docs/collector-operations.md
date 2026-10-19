# Local collector operations

M3A adds [explicit foreground scheduling](automatic-collector.md),
[session policy](market-session-policy.md), [health](collector-observability.md)
and [single-date operator confirmation](daily-finalization-policy.md). The
one-shot/manual operations below remain available. No unattended service is enabled.

Run from the checkout root after `uv sync --locked`. Python 3.12 and Docker Desktop
on Windows, or Docker Engine/Compose on Linux, are supported. Follow README's
resource/port inspection and separate init/start/migrate commands first. Never
point these commands at TradingView or company resources.

The helper reads ignored `.local/database.json` and supplies only the appropriate
URL to child environments. Normal `run` uses `tsetmc_collector`; migration and test
commands use `tsetmc_owner`. Alternatively set `TSETMC_DATABASE_URL` or
`TSETMC_MIGRATION_URL` securely yourself and invoke the CLI/Alembic directly. Only
independent local TSETMC database names and roles are accepted. `.env` is not autoloaded.

```powershell
uv run python scripts/local_db.py run -- db-status
uv run python scripts/local_db.py run -- backfill-history --report output/backfill-report.json
uv run python scripts/local_db.py run -- refresh-history --source-limit 20
uv run python scripts/local_db.py run -- reconcile-history
uv run python scripts/local_db.py run -- reconcile-history --date 20250729
uv run python scripts/local_db.py run -- audit-history
uv run python scripts/local_db.py run -- observe-current
uv run python scripts/local_db.py run -- collection-status --report output/status.json
```

Backfill and audit each request metadata and `/GetClosingPriceDailyList/{code}/0`.
Refresh uses the configured returned-observation limit, **not calendar days**.
Reconciliation uses a single explicit date, or up to `--limit 10` pending daily
quarantine dates (maximum 20). No pending dates means zero HTTP requests. Current
observation uses metadata and one current request. Each logical HTTP call defaults
to at most three attempts under the existing total timeout and pacing policy.
For bounded qualification use, for example:

```powershell
$env:TSETMC_MAX_RETRIES = "0"
$env:TSETMC_TOTAL_TIMEOUT = "35"
$env:TSETMC_READ_TIMEOUT = "25"
$env:TSETMC_PACING_SECONDS = "1"
$env:TSETMC_MAX_CONNECTIONS = "4"
```

Linux uses `export NAME=value` for the same variables. HTTP 401/403 are not retried;
429 honors bounded Retry-After, timeouts/DNS/network/selected 5xx use the existing
bounded retry policy. PostgreSQL failures roll back data and never erase previous
canonical records. No source outage is reported as empty synchronization.

One-shot jobs accept `--dry-run`; this validates source data with no database writes.
`--capture-dir docs/evidence/qualification` replays an original private manifest
without HTTP, validates raw hashes and preserves original receipt instants. Use
replay only in a separate disposable qualification database, not over newer live
canonical data. Replay evidence is marked `captured_replay`, never live freshness.

Instrument configuration is an extensible `instruments` list with string ins_code,
explicit enabled boolean and optional expected instrument_id; the pilot example
is bundled in the wheel. `--instrument-config path.json` selects another file.
Metadata must match both requested code and configured identifier. Generic storage
and jobs are instrument-independent; the live CLI currently permits only فولاد.
No additional real identities are fetched by the synthetic isolation tests.

Each new command gets a UUID run ID. Supply a previously chosen `--run-id UUID`
when recovering from uncertain commit acknowledgment. An identical committed run
returns its saved summary without HTTP or duplicate rows. A reused ID with another
instrument/job/specification is rejected. For a fresh source retrieval use a new
ID. Checkpoints advance to `committed` only with committed data. A new owner marks
abandoned running rows for that instrument interrupted before attempting new work.

Reports are readable structured JSON. Exit codes: 0 success (including documented
empty results), 1 failure, 2 partial/quarantined outcome, 130 user interruption.
Inspect `collection-status` after a failure. A partial run can still preserve valid
records; its last-success timestamp means an ingestion transaction committed,
not that the archive is complete or every row is valid.

Export is read-only and uses the unchanged adapter:

```powershell
uv run python scripts/local_db.py run -- export-db-chartdata --output output/finalized.json
uv run python scripts/local_db.py run -- export-db-chartdata --selection accepted-unverified --output output/accepted.json --legacy-sample
```

Default selection excludes source-unverified rows and reports how many were
excluded. Explicit accepted-unverified selection includes accepted reconciled
observations without asserting finality. Invalid rows are never exported.
`a` date-midnight UTC; `b` open; `c` official close; `d/e` high/low; `f` count;
`g` volume; `h` value. Legacy `i:null` is optional. Unknown activity becomes a zero
placeholder only in the frontend arrays; the report counts those substitutions.
Missing OHLC, int64 count overflow or nonrepresentable float64 fails export.

Recommended operator schedule: recent refresh after a separately qualified session,
pending quarantine review, and full correction audit weekly. This milestone does
not install that schedule or assume a weekday calendar. Polling requires a separate
explicit command; see [current-price policy](current-price-collection.md).
