# Current-price collection and ordering

M3A reuses these ordering rules in the [foreground service](automatic-collector.md),
with expiring verified identity caching and durable schedule slots. See
[freshness versus availability](collector-observability.md) and the bounded
[source observations](tsetmc-source-behavior.md). No new receipt implies a trade.

`observe-current` is one-shot. It stores an actual HTTP observation and parsed
snapshot, then updates an instrument-specific latest pointer in the same transaction.
`pDrCotVal` remains last traded price; `pClosing` remains official/current closing
measurement. Previous close is never substituted for an unavailable last trade.
The remaining daily measurements and instrument state/title are retained separately.

Original dEven/hEven are preserved. Parsed source date and wall clock stay distinct
from the optional Asia/Tehran-derived UTC source instant and actual UTC HTTP receipt.
Zero/absent source clocks remain unknown; no second-level precision is fabricated.
A successful receipt, or unchanged source timestamp, is not proof of a new trade.

Latest ordering, after metadata and parser identity validation:

1. The first valid observation establishes initial state, even with unknown position.
2. A known later source date supersedes an earlier date; an older date never wins.
3. Within a known date, a later known source clock wins and an earlier clock loses.
4. Equal source position and equal financial state is a repeated receipt, not a
   state-change event. A later receipt may advance its provenance pointer.
5. Equal position but changed state is quarantined for review by default.
   `--same-time-correction-reason "reviewed reason"` explicitly accepts a same-time
   correction, preserving both snapshots and the reason. It cannot override an
   older source date/clock.
6. Unknown source position cannot displace an established different state. Matching
   state may gain more precise, consistent date/time evidence. No receipt-only
   freshness assumption is made.

Every retained snapshot records its decision and whether an accepted financial
state changed. Unaccepted stale snapshots remain evidence without changing latest.
Ambiguous changed observations enter current-kind quarantine, separate from daily
reconciliation and coverage. No change is advertised as a tick or new trade.

## Explicit manual polling

After one-shot checks, an operator can opt in, for example on PowerShell:

```powershell
$end = [DateTimeOffset]::UtcNow.AddMinutes(2).ToString("o")
uv run python scripts/local_db.py run -- poll-current --until $end --interval 30
```

The window must end in the future, have an explicit UTC offset and span at most one
day. Interval 30..3600 seconds is configurable. The interval is a collection policy,
not an asserted upstream update period. Source current clocks use Asia/Tehran.
The scheduler makes **no market-open/closed claim** from weekdays or unknown state;
the operator chooses the manual window. Exact session-hour qualification remains
unresolved. No unattended polling service is installed or started.

Requests/jobs are sequential; one instrument owner remains held for the window.
Ordinary transient failures back off between jobs, up to three consecutive failures
by default; 401/403 stops immediately. Existing transport retries remain bounded.
Cancellation propagates, rolls back uncommitted writes, records interruption when
the DB is reachable, and closes resources. Database failures stop the poll instead
of spinning. An injected clock tests timing, slow jobs, failure stops and restart
without real waiting or TSETMC access. No long-running live poll was executed.

## Retention

`retention` defaults to a read-only dry run; `retention --apply` explicitly acquires
ownership. Keep all snapshots seven days; keep accepted state changes 90 days;
always protect the current latest pointer. After pruning eligible snapshots, exact
raw bodies older than 90 days can be removed only when no canonical record,
revision, metadata pointer, remaining snapshot, quarantine, decision or coverage
references them, including M3A's cached identity and operator-review evidence.
Their hash, receipt, request and audit metadata remain, with a
body-pruned timestamp. Canonical daily data, corrections and unresolved/resolved
quarantine evidence are protected. No retention schedule runs automatically.

Audit/run metadata and financially significant evidence intentionally continue to
grow; this is not a fixed-size database guarantee. Review storage and backups and
plan archival of audit metadata before scaling. Retention was verified on synthetic
data; no live financial evidence was pruned during qualification.
