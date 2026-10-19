# PostgreSQL schema

Target PostgreSQL 16.1, SQLAlchemy 2.x + asyncpg, Alembic head
`0002_instrument_links` (after `0001_tsetmc`). Migrations never seed an instrument.
Runtime schema verification rejects absent/incompatible revisions. New schema
changes require an additive migration; do not edit an applied migration.

| Table | Keys and retained data |
|---|---|
| instruments | TEXT `ins_code` PK; unique integer identity ownership_key; active, symbol, company_name, instrument_id, isin, source, verified_at, raw_metadata JSONB, metadata_observation_id |
| collection_runs | UUID run_id PK; ins_code FK, job, request_spec JSONB, status, started_at/ended_at, failure_category, summary/checkpoint JSONB |
| source_observations | BIGINT identity observation_id PK; instrument/run FKs; endpoint and request_parameters, attempted_at/received_at, HTTP status, exact BYTEA raw_body, SHA-256 hex, body_pruned_at, parser_version, source_kind, processing_status, failure_category |
| daily_records | PK(ins_code,trading_date); nine nullable NUMERIC measurements; original dEven/hEven text, raw_row JSONB, observation_id, financial_hash, revision, acceptance/finalization states, first_seen_at/last_verified_at |
| daily_revisions | BIGINT identity revision_id; FK(ins_code,trading_date); UNIQUE(ins_code,trading_date,revision); exact old/new financial JSON states and hashes, old/new observation FKs, reason, discovered_at |
| current_snapshots | BIGINT identity snapshot_id; ins_code, unique observation_id; nine NUMERIC measurements, source_date/time/reported_at, original source fields, receipt, state/title, raw_row, financial_hash, latest decision/reason, is_state_change |
| current_latest | ins_code PK; composite FK(snapshot_id,ins_code); updated_at; state is read from its snapshot |
| quarantined_records | BIGINT identity quarantine_id; ins_code/date/kind, first/last observations, row index/raw_row/reason, UNIQUE(ins_code,fingerprint), sightings, open/resolved, resolution observation/hash/time/method |
| reconciliation_decisions | BIGINT identity decision_id; run/instrument/date; candidate/previous observations; accepted, reason, decided_at |
| collection_status | PK(ins_code,job); composite FK(last_run_id,ins_code,job); last_attempt/success, failure category/count, retry_after |
| data_coverage | PK(ins_code,trading_date); state, observation FK, checked_at |

The nine measurements are `previous_close`, `opening_price`, `last_traded_price`,
`high`, `low`, `official_close`, `trade_count`, `traded_volume`, `traded_value`.
Counts use integral NUMERIC, not bigint, so exact counts above int64 remain storable.
PostgreSQL unconstrained NUMERIC preserves source decimal scale/precision within
its supported range (131072 integer digits, 16383 fractional digits); explicit
serialization guards reject values beyond that range. ChartData's int64 and finite
float64 limits are enforced separately at export. Unknown values remain NULL.

Trading dates are DATE. Actual instants are aware TIMESTAMPTZ in UTC. Source clocks
are TIME without timezone, accompanied by source date and original text; the model
interprets them in Asia/Tehran when possible. Chart labels remain date-midnight UTC,
not observation instants. JSONB decimals are canonical strings for exact JSON
provenance; BYTEA is authoritative for original JSON number lexemes and formatting.
The extended client records the successful attempt's start separately. Older
captures lack that instant: `request_parameters.attempt_start_known=false` marks
the receipt-time fallback in attempted_at. Failure rows record error-registration
time, not a fabricated response receipt, and have no invented raw response body.

Checks enforce nonnegative measurements, integral counts, high >= low and executed
open/last range rules. Model validation additionally rejects nonfinite inputs.
**There is no official-close-inside-range constraint.** Revision hashes must differ.
Status, acceptance, finalization, record-kind and coverage values are constrained.
Composite instrument foreign keys protect metadata, observations, latest pointers,
revisions, quarantine/resolution, reconciliation, coverage and collection status.

Indexes: daily/coverage primary keys support per-instrument dates; unique daily
revision and quarantine fingerprint keys prevent duplication. Additional btrees
cover observations(ins_code,received_at DESC), observations(run_id),
runs(ins_code,started_at DESC), snapshots(ins_code,received_at DESC),
snapshots(received_at), quarantine(ins_code,status,trading_date), and
coverage(ins_code,state,trading_date). No TimescaleDB extension is required.

Coverage states: observed, quarantined, reconciled, confirmed_no_trade, unknown.
Confirmed no-trade requires explicitly observed zero count, volume **and** value;
it does not establish an exchange holiday. Missing calendar dates have no invented
rows and remain unknown. All records initially have finalization `source_unverified`.
The schema reserves `operator_finalized`, but no operator finalization workflow is
qualified or implemented in this milestone.

Collector role has CONNECT, schema USAGE, table SELECT/INSERT/UPDATE/DELETE and
sequence USAGE/SELECT, but owns no tables and has no migration DDL permission.
Owner credentials are used only for explicit migrations, administration and tests.
