# Collector observability and capacity planning

`collector-health` returns instrument-scoped JSON. Default output excludes raw
responses and financial measurements. `--include-prices` explicitly includes exact
diagnostic decimal strings locally; keep that output private.

```powershell
uv run python scripts/local_db.py run -- db-status
uv run python scripts/local_db.py run -- collector-health --stale-after 180
uv run python scripts/local_db.py run -- collector-health --include-prices
uv run python scripts/local_db.py run -- inspect-collection-evidence --kind quarantine
uv run python scripts/local_db.py run -- inspect-collection-evidence --kind revisions
```

| Independent dimension | Evidence and meaning |
|---|---|
| Process | Runtime, heartbeat age, operation, actual advisory owner PID/backend start; missing owner overrides a stale running flag |
| Source availability | Successful current HTTP receipt and age, recent failure category; invalid JSON/schema distinct from network/access failure |
| Data freshness | Accepted source instant/age, financial-change receipt, latest decision, source state, session expectation/confidence/provenance |

Unknown clocks yield unknown freshness; future clocks are flagged. Beyond the
threshold, EXPECTED yields unexpectedly_stale, NOT_EXPECTED yields
unchanged_updates_not_expected, UNKNOWN yields stale_session_unknown. Recent HTTP
can coexist with old source data. Last successful request means a received
response, even if parsing later rejects it; availability separately reports source
usability. No result establishes complete trade capture.

Runtime session evidence expires at its next boundary/window end. Ownership uses
the actual advisory lock/backend, not heartbeat alone. Health is read-only and
does not contact TSETMC. It includes latest pointer, latest canonical daily date
and acceptance/finalization, revision/quarantine totals, next-due/active slots,
pending schedules, failed/interrupted runs and bounded recovered attempt history.
Quarantine totals include resolved cases; inspect status for open cases.

A scheduled reconciliation with no pending dates is a durable zero-request check,
not a fabricated ingestion commit. Last successful database commit is the recorded
end of a committed successful/partial ingestion run, not a WAL commit timestamp.

## Failure interpretation

Network, DNS, timeout, rate limit, denial and server failures retain separate
transport categories. Invalid JSON/schema, records and identity remain source-data
failures. Job deadline, logical budget, ownership loss and PostgreSQL failure do
not establish exchange unavailability. Denial stops collection; transient errors
have persisted bounded retries/backoff. Database failure stops the owner without
unfenced reconnection. `db-status` returns a safe error category when unavailable.
If shutdown cannot be recorded, absent ownership reveals the interruption once
the database can be queried again.

## Storage and request planning

This hypothetical **four-hour approved window** is not an exchange schedule or
tested scaling capacity. A 30-second schedule allows at most 480 current polls
per instrument/window, usually fewer because intervals start after completion.
A 900-second identity TTL adds about 16 metadata requests. Recent refresh/full
audit each add one; reconciliation adds up to five dated requests/job. Budgets
cover all operations; wire attempts are at most logical requests*(retries+1).

| Instruments (planning only) | Current polls/window | Approx. metadata/window | Raw bodies at assumed 4 KiB/poll | Snapshots+runs at assumed 3 KiB/poll |
|---|---:|---:|---:|---:|
| 1 | 480 | 16 | 1.875 MiB | 1.406 MiB |
| 10 | 4,800 | 160 | 18.750 MiB | 14.063 MiB |
| 100 | 48,000 | 1,600 | 187.500 MiB | 140.625 MiB |

Explicit size assumptions exclude archives, indexes, TOAST, metadata, WAL,
backups and logs; measure raw-body lengths and relation sizes privately before
capacity commitments. At 22 windows/month, assumed raw current bodies alone total
41.25/412.5/4,125 MiB. Identical snapshots cost storage but prove no new trades.
No second snapshot stream was added. At one-second global pacing, 100 instruments
cannot each receive two polls/minute in a serial process: that needs over three
requests/second before metadata. No capacity claim is made at that scale.

Existing explicit retention keeps all snapshots for seven days and meaningful
changes for 90 days, always protecting latest state. Raw-body pruning after 90
days affects only unreferenced evidence. Revisions, unresolved quarantine,
canonical provenance, metadata identity and review evidence stay protected. M3A
adds cached-identity/review reference protection; no live pruning is automatic.
Runs, reviews and full-audit evidence can keep growing and need archival policy
before unattended operation. Private qualification logs have no automatic rotation;
bounded windows cap them, and the operator archives/removes them explicitly.

Only one instrument is live. Synthetic A/B tests prove isolation, not performance.
Expansion needs separately approved global pacing/concurrency and measured storage
budgets; a larger HTTP pool alone is insufficient.
