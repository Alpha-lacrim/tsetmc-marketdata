# Explicit foreground collection

No Windows service, scheduled task, systemd unit or Docker auto-start policy is
installed or enabled. `run-collector` runs only when both the JSON configuration
has enabled=true and the operator supplies --activate. Only فولاد is allowed live.
The existing one-shot and manual poll commands continue to work.

## Setup and migration

Use the existing independent PostgreSQL environment; never recreate its volume.
Before upgrading an existing Milestone 2 database:

```powershell
uv sync --locked
uv run python scripts/local_db.py backup --output .local/backups/before-3a.dump
uv run python scripts/local_db.py restore-check .local/backups/before-3a.dump --expected-revision 0002_instrument_links
uv run python scripts/local_db.py migrate
uv run python scripts/local_db.py run -- db-status
```

The historical revision option verifies a backup without altering or upgrading it.
Migration head is 0003_scheduling. Startup checks the schema and never migrates.
The helper uses private credentials from ignored .local/database.json; URLs are
never printed. Fresh installations follow README's independent init/start/migrate
sequence. Existing installation credentials must not be overwritten.

## Configure an operator window

Copy config/collector.example.json to .local/collector.json. The example is disabled
and uses illustrative future dates, not an actual trading schedule. Set enabled,
ins_code/expected instrument ID, aware start/end (at most one day), job first_due,
interval, eligibility and provenance, request/job caps, identity TTL, HTTP deadlines
and retries. Set dated session evidence only when justified. Without evidence use
UNKNOWN plus explicitly approved OPERATOR_WINDOW jobs, or leave jobs deferred.

Current intervals must be at least 30 seconds. History intervals must be at least
60 seconds. Metadata TTL is 60..86400 seconds, normally 900. HTTP retries are 0..2
and request-start pacing is at least one second; qualification should use zero
retries. A logical budget of N permits at most N*(retries+1) wire attempts. Metadata
and each dated reconciliation request count against that budget. Pending
reconciliation is capped at five dates per job.
Request/job caps apply to one explicitly activated process. Restart requires
activation again and grants a new allowance; they are not a global daily quota.
For a qualification spanning restarts, the operator must account for earlier
requests in the remaining declared experiment budget.

```powershell
uv run python -m tsetmc_marketdata.cli validate-collector-config --config .local/collector.json
uv run python scripts/local_db.py run -- run-collector --config .local/collector.json --activate
```

Linux uses the same commands from the checkout root. The helper supplies the
collector role through the child environment. Ctrl+C (SIGINT) performs graceful
cancellation, rolls back uncommitted data and releases ownership. The service stops
on window/runtime, request or job budget; denial stops immediately, transient
failures back off and stop at the configured failure bound. A PostgreSQL failure
stops the owner; it does not silently reconnect and continue unfenced writes.

Use the same schedule keys/specifications after restart. Their durable active run
IDs recover uncertain commit acknowledgment. Updated operating start/end is allowed;
changing a job specification requires a new schedule key. Missed periods coalesce
without a burst, and restart imposes a 30-second current cooldown. Periodic history
jobs remain pending until their eligibility is supported. A session-completion
refresh and a delayed/next-operating-window recheck can use separate first_due keys;
neither defines a holiday calendar. A weekly audit uses a 604800-second interval
with NOT_EXPECTED evidence and defers while current collection is eligible.

For a short qualification, declare a window of at most ten minutes, 30–60 second
current intervals and an explicit small request cap. `--evidence-dir` must be under
.local or output; a unique subdirectory preserves exact bodies, UTC request/receipt
times, source clocks, hashes, current measurements, job decisions and latencies.
Those are private artifacts, not public fixtures or production telemetry exports.
No process should be left running when an initial qualification ends.

```powershell
uv run python scripts/local_db.py run -- run-collector --config .local/qualification.json --activate --evidence-dir .local/qualification
uv run python scripts/local_db.py run -- collector-health
uv run python scripts/local_db.py run -- collector-health --include-prices
```

The repository's actual experiment used six scheduler requests over about one
minute, then two separately budgeted dated inspections, for eight total and zero
retries. It did not qualify an active session. See the verification report.

## Maintenance and evidence inspection

```powershell
uv run python scripts/local_db.py run -- refresh-history --source-limit 20
uv run python scripts/local_db.py run -- observe-current
uv run python scripts/local_db.py run -- reconcile-history --date 20250729
uv run python scripts/local_db.py run -- inspect-collection-evidence --kind revisions --date 20250729
uv run python scripts/local_db.py run -- inspect-collection-evidence --kind quarantine --limit 20
uv run python scripts/local_db.py run -- inspect-collection-evidence --kind observations --limit 20
uv run python scripts/local_db.py run -- inspect-collection-evidence --kind reviews
```

Inspection hides raw rows, raw bodies and financial old/new states by default.
--private-details explicitly includes row/state details locally, never raw HTTP
bodies. Historical observations can span many dates, so observations inspection
does not accept a misleading single-date filter. The existing legacy
collection-status command can include source details; keep its output private.

An operator review uses review-daily --date YYYYMMDD --action confirm|revoke,
--expected-hash, --actor, --reason and optionally a chosen --review-id. Confirmation
also requires two --observation-id values, --session-end, --session-evidence and
--grace-seconds. Read [the full policy](daily-finalization-policy.md) first. There
is no bulk confirmation and no automatic review invoked by the service.

## Supervisor examples for later qualification

A future Windows supervisor should run the foreground command above in the
checkout directory, with one-instance behavior, manual activation, no automatic
restart and SIGINT/console-interrupt shutdown. A Task Scheduler action would use
uv.exe as Program, the foreground command's arguments, and the checkout as Start
in; no task or service is registered by this milestone. A Windows service adapter
would need separately selected/qualified tooling; plain python.exe is not a native
Windows Service Control Manager service executable.

A future Linux unit definition could use:

```ini
[Unit]
Description=Independent TSETMC foreground collector
[Service]
Type=simple
User=tsetmc
WorkingDirectory=/srv/tsetmc-marketdata
ExecStart=/usr/local/bin/uv run --offline python scripts/local_db.py run -- run-collector --config .local/collector.json --activate
Restart=no
KillSignal=SIGINT
TimeoutStopSec=30
```

This is documentation only, without an Install section or activation command.
Do not deploy or enable unattended operation until session rules, source behavior,
backup monitoring and the intended operating window are explicitly qualified.
