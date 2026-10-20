# Milestone 3B-1: transactional source publication

Source-only implementation against published design commit
`0a770a050e1939b1fa26ba00c86ff45696ea366f`, 2026-10-20. PostgreSQL remains **16.1**;
source revision `0004_outbox` follows `0003_scheduling`. Existing 0001–0003 files
and frozen schema metadata are unchanged. No company schema, route, worker,
producer credential or network delivery is implemented. The actual company
deployment remains unverified; prepared compatibility baseline is 1.1.0rc1/0010.

## Implemented boundary

`storage/outbox.py` publishes accepted local state, inside `Repository.atomic`,
after all canonical/revision/quality mutations and before the existing
`before_commit` fault boundary. Every relevant mutation marks its date/current/
status lane. Confirm/revoke uses `atomic(ingest=True)` and records the exact review
ID applied by that transaction; equal supplied review timestamps do not select
the wrong action by UUID order. Scheduler runtime ticks mark the status lane.

No dataset exists by default. Migration seeds nothing. An administrator may create
an immutable local binding with explicit installation/epoch/destination/producer
UUIDs; that still leaves publication disabled. Only an explicit bounded local seed
enrolls it and enables capture. No real mapping was configured during this task.
Once enabled, capture cannot be switched off through ordinary dataset UPDATE:
pausing eventual delivery must not silently stop transactional publication.

Source tables are instrument-scoped; company UUID is computed from the existing
`TSETMC:<ins_code>` canonical-symbol UUID5 rule. Epochs are explicit and globally
unique in this installation, preventing observation UUID collisions between
instruments. No schema or reusable function contains the real pilot's code.

## Tables, integrity and roles

Seven new tables bring the application total to **21**:

| Table | Purpose |
|---|---|
| sync_datasets | One explicit immutable instrument/installation/epoch/binding; disabled and unenrolled initially |
| sync_stream_clocks | Instrument/epoch/stream PK; transactional head, acknowledged prefix and finite logical budgets |
| sync_daily_heads | Instrument/epoch/date PK; public state version, last semantic digest and approved observation |
| sync_outbox | Immutable daily/revision/coverage records, exact UTF-8 BYTEA, observation UUID and record hash |
| sync_latest_pending | Durable current/status head, version and acknowledged version; replacing it cannot edit staged bytes |
| sync_evidence_refs | Composite source-observation/snapshot links protecting published and staged provenance from retention |
| sync_batches | Immutable exact request bytes/binding/hash, selected range, simulated receipt and durable lifecycle |

Composite FKs enforce instrument/epoch/stream links and batch destination/producer
bindings. JSON identity/date/version checks agree with relational keys; stored
record bytes parse to the same JSON. PostgreSQL checks the exact batch byte SHA256
and 2 MiB limit. Counters and versions are int64; financial values remain exact
NUMERIC in canonical tables and canonical decimal strings in the public wire.

Three trigger functions (`sync_immutable`, `sync_batch_guard`,
`sync_dataset_guard`) protect immutable evidence, bytes/receipt lifecycle and
dataset identity. Four table triggers apply them. Functions have fixed search_path,
no SECURITY DEFINER privilege escalation and no PUBLIC execute grant. If the
existing `tsetmc_collector` role exists, migration explicitly grants SELECT on
datasets; SELECT/INSERT on outbox/evidence; SELECT/INSERT/UPDATE on clocks, daily
heads, latest heads and batches. DELETE is revoked on all new state, and UPDATE
is revoked on immutable evidence. No role/login/password is created. Dataset
configuration/enrollment requires the administrator's existing privileges.

## Commit ordering and semantic changes

All publishers use the existing instrument session fence. Canonical dates and
daily heads are locked in date order, then all instrument stream-clock rows in
lexical order. Positions allocate through a transactional row UPDATE, with locks
held through canonical/outbox commit. No network operation occurs in this region.
Rollback restores head and payload together. A later writer cannot commit a higher
same-stream tail while the earlier allocation is unresolved; another instrument
can progress independently. Source positions never use a PostgreSQL sequence.

Daily semantic comparison includes financial hash/revision, acceptance, local
confirmation/review and reconciliation state/open-conflict count. It excludes
receipt/raw-field refresh and redundant reconciliation observation IDs. One final
canonical state is emitted per touched date/transaction. If a transaction makes
multiple financial corrections, intermediate retained revisions use the existing
`daily.revision_seed` audit record and enrollment ID; the final state carries its
own latest revision evidence. This preserves the chain without adding a wire type.

Operator confirmation is historical evidence for one hash, not upstream finality.
A later conflict can retain that review while publishing disputed quality; the
zero-open-conflict requirement applies when confirming, not an automatic future
revocation. A correction resets local confirmation under the existing source
policy. Pre-enrollment review summaries select an action matching canonical
finalization; unavailable historical finalization chronology is not invented.

Opening/last prices retain executed-range checks. Official close can lie outside
high/low. The nine measurements, nullable values and genuine count/volume/value
remain unchanged. Units use the proposed IRR/share profile with **unverified**
confidence; source-unit and redistribution qualification remain real-transfer gates.

## Current, coverage and status

Only the actual accepted `current_latest` pointer may publish. A newer source clock
at equal financial values advances current state with financial_change=false.
Receipt-only repeats and rejected older/unknown/ambiguous observations do not create
current updates. Initial seed/resnapshot may preserve an accepted repeated_state
pointer without claiming a new trade. Same-clock conflicting resnapshot requires
accepted explicit correction evidence; a version increment alone cannot repair it.

The latest durable head may coalesce, while old staged BYTEA remains immutable.
ACK(N) records N only and leaves N+1 pending. The local financial_change flag
describes the preceding local snapshot: coalesced A→B→B must still leave B available
for a company that holds A. All records keep source clocks and HTTP receipts apart.

Coverage is lossless, in pages of at most 100 explicitly observed dates; omitted
dates stay unknown. Invalid-only dates publish coverage without fake accepted
prices. Status is coalescible with actual capture and a fixed 60-second TTL;
staging/retry never regenerates expiry. It reports process/session/HTTP uncertainty
separately. `last_database_commit_at` is null: a collection-run ended_at is recorded
before commit and cannot truthfully be relabeled as a PostgreSQL commit instant.

## Seed, staging and capacity

Explicit local enrollment holds the source owner and takes one consistent snapshot.
It materializes retained revision evidence, accepted daily seeds, lossless coverage
pages and the existing current head; canonical data and scheduler state are not
edited. Limits are at most 10,000 daily rows / 32 MiB total serialized seed records.
Exceeding either aborts the transaction. Reusing the same committed seed ID is
idempotent; another ID/epoch cannot silently reset the dataset. Later corrections
receive higher source positions and public versions.

Local staging, receiving and acknowledgment are separate committed operations.
Staged bytes are never rebuilt under an existing batch ID. Batch count defaults
to 100 daily records and one record for other lanes; target 512 KiB, hard 2 MiB.
Receipt binding, exact byte hash, complete observation set, record hashes/positions,
stored state versions/hashes and outcome counts must validate before saving it.
Only a saved receipt authorizes contiguous daily/coverage ACK or latest-version ACK.
All current batches are database-labeled **simulated=true** and require explicit
`simulate=True`; they establish no remote success or receipt authenticity.

Per-stream default admission budgets are 1,000,000 publication/staging operations
and 1 GiB of serialized evidence, with 70/85% alerts. Accounting is deliberately
conservative and cumulative, including superseded latest versions and staged
bytes; it is not a heap/WAL/disk-space estimate. No reclamation or pruning of new
sync evidence is implemented. At the hard limit the affected financial transaction
rolls back, and collection must pause/alert. There is no silent loss or infinite
outage guarantee. A reviewed retention/archival stage must precede sustained use.

## Deliberate Stage 4/5 deferrals

The Stage 1 local simulator uses the existing collector owner fence. It is **not**
the future synchronization worker. sync_worker_owners, sync_worker_state and
sync_producer_sessions are deferred together with worker roles/routines, producer
session generations/recovery, renewal, credentials and network activation. Creating
inert placeholders would not prove that coordinator fencing works. The real worker
must add its independent coordinator/instrument fences before using delivery state.

`continuity()` only compares supplied installation/epoch/destination/producer,
head/ACK and staged-hash proof. A disposable restored database behind such proof
is fenced. It does not create, persist, authenticate or independently discover an
external fsynced anchor, nor query company receipts/heads. Those real restore and
lease guarantees remain unverified Stage 4 requirements. No duplicate producer
session recovery state is introduced because no session coordinator exists yet.

Company schema/INGEST/READ/WS, TLS delivery, archive parity and real enrollment are
future stages. Existing source migration head verification now expects 0004;
the original pilot has **not** been upgraded, seeded, backed up or contacted by
this task. Use its published old checkout until a separately authorized migration.

See [operations](source-outbox-operations.md), [verification](milestone-3b1-verification.md)
and the preserved [normative wire contract](milestone-3b-wire-contracts.md).
