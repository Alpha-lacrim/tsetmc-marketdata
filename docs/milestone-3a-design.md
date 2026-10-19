# Milestone 3A design

Protected baseline: `01a827be39bb48864d0b76c8e952f176a4904556`. The existing client,
Collector, Repository, source parsers, exact financial models, latest ordering,
manual PollPolicy, Clock and ChartData adapter remain the foundation. There is no
new HTTP transport or parallel persistence system. The local foreground service
is disabled by default, bounded by an explicit operator window and request/job
budgets, and never registered for OS auto-start.

| Component | Responsibility |
|---|---|
| collection/sessions.py | Dated, instrument-specific evidence; EXPECTED / NOT_EXPECTED / UNKNOWN; explicit priority and provenance |
| collection/service_config.py | Validated operating window, jobs, request budget, identity TTL, deadlines and retry bounds |
| collection/service.py | One owner, current-first scheduling, bounded catch-up, graceful stop and durable recovery |
| collection/budget.py | Logical-request cap and optional private qualification evidence around the existing Source protocol |
| storage/scheduling.py | Durable slots, deterministic run IDs, checkpoints, runtime ownership and heartbeat |
| storage/health.py | Separate process health, source availability and financial-data freshness |
| storage/reviews.py | Auditable single-date operator confirmation/revocation, never automatic source finality |
| service_cli.py | Explicit activation, safe health/evidence inspection and review commands |

## Durable scheduling

Each configured schedule has a stable key scoped by ins_code, immutable specification
hash, next due instant and active slot/run ID/parameters. A UUID derived from
instrument, schedule key, specification and slot remains stable after restart.
Pending reconciliation dates and session provenance are frozen when a slot starts;
recovery does not silently change its request. Changed specifications require a
new schedule key. Changing only the operating window does not reset job progress.

Collection commits use the existing atomic ingestion transaction. A schedule may
advance only after a committed successful/partial collection run, or a committed
check that no daily quarantine dates are pending. If the process dies after the
data commit but before checkpoint advancement, the same run UUID returns its saved
summary without HTTP. Before commit, data rolls back and the slot remains pending.
New ownership marks abandoned running attempts interrupted. Retry history remains
in the run checkpoint (latest 20 attempts plus total attempt count).

Overdue intervals coalesce into the latest eligible slot; they do not become a burst
of synthetic observations or calendar-gap candles. Current jobs win every turn;
only one history job can run before current work is rechecked. Full archive audits
defer while current observation is eligible. Recent refresh/reconciliation during
an approved observation window has a deadline no longer than the current interval.
Slow work may delay a poll, but never overlaps transactions or fabricates skipped
observations. There is no promise of exact 30-second delivery under slow dependencies.

Wall-clock UTC instants define durable eligibility. Monotonic time bounds the
process lifetime and current-job separation despite clock changes. Restart adds
a conservative 30-second current-job cooldown, including when an earlier HTTP
request may have escaped a rolled-back transaction. Source-reported clocks remain
separate. Asia/Tehran conversion uses IANA rules, not a fixed historical offset.

## Additive schema

Alembic `0003_scheduling` follows `0002_instrument_links`; neither earlier revision
nor frozen schema_v1 metadata changes. Three tables are added:

| Table | Purpose and keys |
|---|---|
| scheduled_jobs | PK(ins_code,schedule_key), job/spec hash, next_due, active_slot/run/parameters, last completed slot/commit, failures, coalesced count; index(ins_code,next_due) |
| collector_runtime | ins_code PK, service UUID, owner backend PID/start, state/operation, heartbeat/start/end, config hash, session decision/evidence expiry, last financial change, failure and stop reason |
| daily_reviews | review UUID PK, FK(ins_code,trading_date), reviewed financial hash, action/actor/reason/time, session evidence/grace, two instrument-scoped observation FKs; index(ins_code,trading_date) |

There are now 14 application tables. Every new entity is instrument-scoped, and
review evidence uses composite identity foreign keys. Existing financial columns
and acceptance/finalization enums are unchanged. The migration never seeds instruments
or updates market measurements. Upgrading the persistent pilot followed a verified
private backup restore; all 4,662 prior records retained the identical financial
hash, revision and finalization fingerprint. Downgrade and interrupted-migration
tests operate only on generated disposable databases.

## Compatibility changes

Collector identity caching defaults off for existing one-shot commands and on for
service/manual polling. Expiry uses both receipt age and monotonic elapsed time;
identity is revalidated, and source-data errors invalidate the cache. Cached
metadata reuses its original observation/receipt rather than inventing a new HTTP
response. Market observations reference that identity evidence in request parameters;
retention protects those references. Daily review evidence is protected too.

History audits now retain an ordinary canonical record when an open, individually
valid competing source exists, including when a later list agrees with that competing
candidate. They cannot arbitrate the disagreement merely by endpoint priority.
Ordinary corrections without an unresolved valid conflict still create revisions.
Official closing prices outside the executed range remain accepted unchanged.

No new runtime dependency is required. PostgreSQL remains 16.1, with existing
SQLAlchemy/asyncpg/Alembic and HTTP precision/security behavior. No FastAPI route,
HTTPS synchronization worker, company database, additional live symbol or deployment
is introduced. See [verification](milestone-3a-verification.md) for implementation
results versus the separate, still-incomplete live market-session qualification.
