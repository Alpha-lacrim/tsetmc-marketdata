# Proposed Milestone 2 — فولاد durable storage and collection

This is a design proposal only. No SQL, migrations, database dependency, container,
scheduler or synchronization service is implemented in Milestone 1.

Create one independently named PostgreSQL database, e.g. `tsetmc_marketdata`, with
its own service account, secrets, Docker named volume, port configuration and backup
policy. Use PostgreSQL NUMERIC without a restrictive precision/scale for prices,
volumes and monetary amounts; use integral NUMERIC for counts if preserving numbers
beyond bigint is required. Preserve null unknowns. insCode remains TEXT, daily keys
are DATE, actual instants TIMESTAMPTZ, and source dates/clocks remain separate fields.
Do not impose official-close bounds against executed-trade high/low.

## Proposed tables and indexes

| Table | Columns / uniqueness / indexes |
|---|---|
| instruments | ins_code TEXT PK; verified symbol/name, instrument_id, c_isin, metadata JSONB, metadata_observation_id; ASCII-digit check |
| source_observations | observation_id BIGINT identity PK, endpoint, ins_code FK, requested_date/parameter, received_at TIMESTAMPTZ, status, exact raw_body BYTEA, sha256 BYTEA, optional decoded JSONB, parser version; btree(ins_code, endpoint, received_at DESC), BRIN(received_at); payload hash is not globally unique because repeat receipts are meaningful |
| daily_records | PK(ins_code, trading_date), nullable exact source measurements including separate last_trade/official_close and previous_close, raw date/time, raw row JSONB, financial_hash, current_revision, observation_id FK, first_seen_at/last_verified_at; nonnegative and high>=low checks; no close-inside-range check; PK supports ascending/descending history reads |
| daily_revisions | revision_id BIGINT PK, ins_code, trading_date, revision_no, prior_hash/new_hash, exact previous/new measurements or full row JSONB, reason, observation_id, observed_at; UNIQUE(ins_code,trading_date,revision_no), index(ins_code,trading_date,observed_at DESC) |
| current_snapshots | snapshot_id BIGINT PK, ins_code FK, source_date/time, source_reported_at nullable, received_at, all current fields/state, observation_id, financial_hash, raw row; UNIQUE(observation_id), btree(ins_code,received_at DESC), BRIN(received_at); repeated HTTP receipts are observations, not synthetic new trades |
| current_latest | ins_code PK, snapshot_id FK, received_at, source date/clock; additive latest-state pointer updated transactionally; stale-session observations cannot displace a newer source session |
| quarantined_records | quarantine_id PK, observation_id, row_index, source date if valid, reason/code, raw row, resolution observation_id/status; UNIQUE(observation_id,row_index,reason_code) |
| collection_status | PK(ins_code,endpoint), last_attempt/success, failure category/count, next_retry_at, last_source_date, lease_until/worker_id, parser version; index(next_retry_at) |
| data_coverage | PK(ins_code,trading_date,coverage_kind), observed/quarantined/reconciled/confirmed_no_trade/unknown classification, supporting observation/state evidence, last_checked_at; index(ins_code,classification,trading_date); absent dates are unknown until calendar/state evidence supports a stronger claim |

Keep raw bytes even if JSONB reorders keys or numeric formatting. Hash canonical
financial measurements for idempotent state updates; hash the raw body separately
for provenance. Exclude receipt timestamps from financial hashes. Store revision
history only when measurements change, while retaining every chosen observation
receipt according to an explicit retention policy. Do not hash binary floats.

## Collector behavior

1. Build one-shot `backfill`, `reconcile`, and `observe-current` jobs first, using
   the Milestone 1 client. Verify metadata before data ingestion. Only فولاد is enabled.
2. Backfill `/0` once; atomically retain the raw observation, ingest validated rows
   idempotently, quarantine invalid rows and update coverage/status in the same
   transaction. Stream/batch database writes without partial coverage claims.
3. Reconcile malformed dates via the dated endpoint. The concrete acceptance case
   is 2025-07-29: preserve list open=0 and targeted open=2956 as separate evidence;
   accept the validated targeted correction with an explicit provenance/reason.
   No arbitrary preference is allowed if both measurements are plausible but differ.
4. On subsequent daily runs, recheck a configurable recent window (initially 20
   returned observation dates), unresolved quarantine, and any known corporate-action
   dates. Re-fetch the complete list weekly to detect older corrections. A smaller
   n is a row limit, not an archive-completeness or calendar guarantee.
5. Add restrained current-price polling only in the next task, initially one request
   every 30 seconds during independently qualified market hours; use exchange-local
   date/state to suppress inappropriate scheduling. No market-hours constants are
   assumed until qualified. Back off on network/429/5xx, stop/review access denial,
   persist status and resume safely after restart. Repeated source state is not a trade.
6. Use a per-instrument advisory lock/lease to prevent concurrent ingestion races.
   Commit observations, revisions, state and coverage together. Advance progress
   only after commit; a crash before commit is safely replayable. Monitor quarantine,
   receipt failures, source dates, coverage and job duration.

## Milestone 2 tests and acceptance

Use an isolated disposable PostgreSQL instance and synthetic/captured fixtures;
never TradingView/company databases. Test exact Decimal round trips and JSON raw
provenance, repeat-backfill idempotency, correction/revision creation, conflicting
duplicate rollback, quarantined-row repair, restart before/after transaction commit,
concurrent writers/leases, stale current-session ordering, explicit no-trade versus
unknown gaps, failure/retry persistence, and backup/restore. Migrations must upgrade
and roll back in disposable databases. Live tests stay bounded and opt-in.

Milestone 2 should finish with complete durable observed history, documented
quarantine/reconciliation for all unresolved dates, current snapshots/latest state,
repeatable recovery and local coverage reports. It must not include production
deployment or company API changes without a separate task.

## Later additive integration

TSETMC APIs → independent collector → separate local TSETMC PostgreSQL → durable
observations/sync state → independent HTTPS sync worker → company FastAPI INGEST →
company market-data storage → FastAPI READ / REST / WebSocket → company frontend.

Propose separate provider/instrument namespace (`provider=tsetmc`, string insCode),
daily-granularity history endpoints returning canonical ChartData, and separate
latest-price payloads carrying last traded price, official close, source clock and
receipt instant. Add idempotent ingest keys, revision-aware daily corrections,
durable outbox/ack cursors and restart recovery in later milestones. Preserve every
existing TradingView route and behavior. Daily records must never be forced into
TradingView one-minute assumptions. No company contract or storage change is made now.
