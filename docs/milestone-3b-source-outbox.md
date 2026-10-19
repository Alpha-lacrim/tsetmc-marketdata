# Proposed TSETMC transactional outbox and worker state

**PROPOSED; no schema or worker is implemented here.** Source database remains
independent PostgreSQL 16.1. Existing 0001–0003 migrations and canonical values
are immutable inputs. A later reviewed 0004 adds the following logical tables and
restricted routines; names below are the reserved proposal, not installed objects.

## Instrument-scoped state

Provider is tsetmc at this source. Financial state, epochs, positions, checkpoints
and instrument ownership include ins_code directly or through composite links;
no constraint contains the pilot's code. Producer sessions are intentionally
producer-scoped, matching the actual company control plane, as explained below.

| Proposed table | Keys, contents and constraints |
|---|---|
| sync_datasets | ins_code PK/FK instruments; source_epoch UUID; installation_id UUID; enabled false; immutable configured destination/producer binding; unique(ins_code,source_epoch) |
| sync_stream_clocks | PK(ins_code,source_epoch,stream); transactional BIGINT head>=0, acknowledged prefix for daily/coverage, retained floor, logical row/byte budgets; CHECK ack<=head |
| sync_daily_heads | PK(ins_code,source_epoch,trading_date); state_version>0, last published semantic hash; financial_revision remains the existing canonical revision |
| sync_outbox | PK(ins_code,source_epoch,stream,source_position) for daily/coverage; observation_id UUID unique; kind/event_type, date/state_version and financial_revision/hash where applicable, exact immutable JSON record, payload hash/byte count; composite clock/dataset links |
| sync_latest_pending | PK(ins_code,source_epoch,stream) for current/status; version>0, acknowledged_version<=version, immutable head record/UUID/hash, capture/expiry, local snapshot ID where relevant |
| sync_batches | PK(destination_id,producer_id,batch_id); ins_code/epoch/stream/generation, exact BYTEA request, SHA256, immutable selected record IDs/hashes, daily after/through or latest version, phase, attempts/backoff, receipt; only lifecycle fields mutable |
| sync_worker_owners | PK(destination_id,ins_code); owner UUID/generation, dedicated advisory backend PID/start; separate lock namespace from collector ownership |
| sync_worker_state | PK(destination_id,ins_code,source_epoch); approved producer binding, reconciliation fence/root, enrollment ID and progress; references the producer session coordinator, no cloned per-instrument session recovery |
| sync_producer_sessions | PK(destination_id,producer_id); single coordinator owner UUID/generation/PID/backend-start, current session/generation, complete expected grant manifest, pending recovery ID/exact bytes; no credential secret in SQL |

source_position is a positive int64 encoded as a string on HTTPS. It is allocated
per instrument/epoch/stream, not inferred from source_observations identity IDs,
collection-run UUIDs, trading date or wall clock. Observation UUID is UUID5 of the
source_epoch namespace and `stream:source_position`, allocated once and persisted.
Company mapping UUID follows its existing canonical-symbol UUID5 rule. These are
different identities. A dataset restore/clone does not authorize a new epoch.

## Atomic publication points

Extend Repository.atomic(ingest=True) immediately before its existing before_commit
fault hook. Gather touched dates, then compare the final accepted public state of
each date against sync_daily_heads, after all reconciliation/quarantine changes in
that transaction. Publish at most one full canonical state per date/transaction.
Repository.daily_record, reconcile, ingest_current, quarantine_row and review_daily
must all participate; an after-commit callback or periodic scan alone is insufficient.

| Local change | Proposed publication |
|---|---|
| New accepted day | daily.accepted full state; state_version=1 |
| Financial correction | daily.corrected; existing financial_revision increments; public state_version increments; include exact old/new revision evidence |
| Reconciliation changes acceptance/quality | daily.reconciled or daily.quality_changed with unchanged financial revision if values match |
| Confirm/revoke | daily.review_confirmed / daily.review_revoked; reviewed hash/summary; state_version increments even when financial hash stays equal |
| Correction after confirmation | New financial revision, finalization resets source_unverified; old review remains linked to old hash |
| Open/resolved conflict with canonical record | Quality-only full state with open count/status; no competing candidate values |
| Invalid/conflicting date without canonical record | Coverage/status diagnostic only, no accepted daily event |
| Equal financial/raw-only recheck | No daily event for receipt/raw-flag/provenance-only refresh; retain new raw evidence locally |

New state_version orders all **public semantic** changes, independently of the
existing financial_revision. Financial hash uses the existing exact algorithm;
public semantic comparison excludes transport attempt clocks and repeated raw
verification receipts. A full event retains the actual source observation that
proved that accepted state; later raw-only verification need not replace its
publication provenance. New outbox/batch references must protect those original
source observations and reviews against raw pruning.

Raw HTTP bodies, actor/reason text, rejected candidates and unapproved diagnostics
stay local. Approved wire records carry opaque observation IDs/raw hashes and a
sanitized review summary, not private capture bodies. A quarantine is never an
alternative accepted price solely because it was queued successfully.

## Commit-safe ordering: required proof

For each affected instrument/stream, take its clock row FOR UPDATE and allocate
positions using transactional UPDATE head=head+N RETURNING head. Insert events and
canonical/quality changes in the **same** transaction, holding that clock lock until
commit. Different instruments have independent clocks. Acquire locks in this order:
collector instrument fence, affected canonical dates ascending, daily-head rows,
stream clocks in lexical stream order. Allocate the outbox tail last; perform no
network I/O while holding it. All publishers, including seeding/reviews, follow this
order. Cross-instrument administrative batches sort ins_code first.

Counterexample prohibited: A reserves sequence 41 and pauses; B reserves 42 and
commits; worker acknowledges through 42; A commits 41 later and is skipped forever.
With the proposed row counter, B cannot allocate the next position for that stream
until A commits or rolls back. A rollback undoes the counter and event; A commit
makes its event visible before B can allocate. A fresh READ COMMITTED worker query
therefore cannot see a later committed prefix without the earlier one. Do not use
SKIP LOCKED to advance a daily prefix around unavailable lower positions.

This follows the existing company's transactional journal/capture-clock technique,
with instrument-specific keys. PostgreSQL sequences are not transactional commit
order; see [sequence behavior](https://www.postgresql.org/docs/16/functions-sequence.html)
and [lock lifetime](https://www.postgresql.org/docs/16/explicit-locking.html).
The race/rollback proof must also pass actual PostgreSQL tests before activation.

## Current snapshots: durable coalescing, not a tick tape

Only a snapshot promoted by the existing choose_latest policy is eligible. For
initial seed/resnapshot, read the actual current_latest pointer, even when it
references an accepted repeated_state receipt; preserve that original decision,
use current.seed/current.resnapshot and financial_change=false, not a fabricated
new trade. This exception does not enqueue every subsequent receipt-only poll. Compare
financial hash, source position, instrument state and explicit correction decision
with the last published accepted head. A newer source clock at equal financial
values advances the snapshot version with financial_change=false. Equal state and
equal source clock at a newer HTTP receipt updates status availability only; it
does not create a trade or financial-price event. Rejected older/ambiguous snapshots
remain local and must never be reclassified by retrying delivery.

In the canonical transaction, lock the current clock and durably replace
sync_latest_pending only after the new accepted snapshot itself is durable in
that same commit. Old unstaged heads may coalesce; any staged/in-flight bytes remain
immutable in sync_batches. Current gaps in source_position are allowed and are
not daily-prefix gaps. No complete tick history is promised.

ACK of version N updates acknowledged_version=greatest(acknowledged_version,N)
only for the matching instrument/epoch/stream, authorized owner and validated
receipt. N must be <= the locally committed version. The pending head may be
cleared only if its version **and observation ID/hash** still equal the acknowledged
record. If N+1 committed during upload, N's ACK leaves N+1 pending. A company head
ahead of every known local durable version is a restore/identity alarm, not permission
to advance local state. Reconciliation checks source clocks and exact hashes too.
For current reconciliation, compare the durable approved outbound head with the
company imported state, and separately check its financial values/source position
against current_latest. A later equal-state, equal-clock HTTP receipt may move the
local accepted pointer without changing the published head; that receipt/provenance
difference alone is neither financial divergence nor a reason to enqueue a repair.

Coverage uses a separate **lossless prefix**, not a replaceable single page. Each
transaction emits pages of at most 100 touched date states with their own positions;
unreported dates remain unknown, never deleted. Replacing an unsent coverage page
with another page could lose dates and is prohibited. Status alone uses another
coalesced lane, preserving capture/expiry and source HTTP/DB clocks. The worker
cannot extend expired status merely by sending it later.

## Four durable delivery phases

1. **Stage:** under the worker fence, select a committed daily/coverage prefix or current/status
   head; commit batch UUID, exact bytes/hash, selected records and checkpoint intent.
2. **Send:** no collector lock is held. Use the independent token, TLS verification,
   no redirects/proxies by default, bounded request/response/timeouts and backoff.
3. **Receive:** validate the producer/epoch/batch/stream/instrument/hash and every
   record outcome/hash; commit the original receipt and phase=received.
4. **Acknowledge:** a fenced local transaction advances only that batch's daily/coverage
   prefix or CAS latest version and marks acknowledged. Crashes replay phases;
   source acknowledgment must reference the retained committed receipt.

An empty daily page can advance through a known committed head only if all lower
events are already acknowledged/retained according to the durable prefix. No scan
uses max(sequence) or an arbitrary last row as proof of delivery.

One worker coordinator per destination/producer, with independent instrument
ownership rows, default one HTTPS request at a time. Admission/renewal/recovery
is serialized by that coordinator and its durable producer-session row; per-
instrument jobs do not invent separate recovery IDs for the same producer lease.
Every mutable batch/ACK transaction verifies both coordinator and instrument fence.
One process may own several instruments and schedule them fairly. To split work
among independent worker installations later, provision different producers/grants
rather than cloning session/anchor state. This keeps two synthetic instruments'
financial positions and checkpoints isolated without fighting over one shared lease.
Reserve an opportunity for current delivery before every daily batch; default
daily batch <=100 rows and target 512 KiB, hard 2 MiB. Current/coverage/status batches
carry one record; coverage records contain at most 100 explicitly reported dates. Fair round-robin skips absent/unchanged streams. Configurable
global pacing/in-flight caps must respect the gateway's producer budget and reserve
TradingView capacity. No additional instrument is activated by this design.

## Initial archive enrollment, separate from incremental delivery

An explicitly invoked seeding operation acquires the existing instrument owner
briefly and takes one consistent local snapshot. With capture hooks installed,
materialize original retained revision evidence first, then one daily.seed state
per existing canonical date, bounded lossless coverage pages, and the existing
accepted current head. Allocate the
positions and enrollment/fence atomically; update only new synchronization tables.
Do not re-fetch TSETMC, edit prices, change canonical revisions or finalize records.

For the reported pilot, 4,662 daily rows fit the proposed enrollment ceiling of
10,000 canonical rows / 32 MiB serialized records, subject to actual measurement.
If that ceiling or revision evidence exceeds the configured budget, stop before
commit and require a reviewed materialized/paged enrollment plan; never truncate.
This is a short database seeding transaction, not an HTTPS bulk transaction.
Collection may need an explicitly scheduled pause to acquire its existing owner;
there is no simultaneous second collector. No pause is performed in this task.

Pre-enrollment daily_revisions are exported as daily.revision_seed records with
their genuine old/new states, hashes and original provenance. They populate company
revision evidence without changing its canonical daily head. Do not invent past
finalization chronology unavailable from source evidence. The canonical seed carries
the actual current financial revision/state and latest hash-bound review summary.

After seed commit, upload bounded batches while collection resumes. A correction
after the seed appends a higher daily position and state_version; it cannot be
lost or replaced by a delayed seed. Current traffic gets priority over the archive.
After acknowledging a captured fence H, compare all canonical dates and revision
manifests at H with the company, in bounded pages. Subsequent corrections form a
new fence. Archive parity is agreement with local accepted state, not proof of
complete exchange history. Staging/response-loss/restore cases are specified in
[recovery](milestone-3b-recovery.md).

## Capacity, retention, continuity and permissions

Never prune unacknowledged daily records, unresolved batches/recoveries, or source
evidence they protect. After ACK and verified reconciliation, keep acknowledged
batch bytes/receipts and outbox records at least 90 days; thereafter a reviewed
archive may compact them into immutable epoch/range/digest manifests. Maintain a
permanent identity/hash tombstone so a reused event/batch ID cannot acquire new
meaning. Company receipt/ledger retention must cover this retry horizon.

Use configurable logical budgets (initial proposal: 1,000,000 daily events / 1 GiB
serialized outbox, excluding heap/index/WAL/backups), soft alerts at 70/85%, and
backpressure before the hard limit. WAN downtime does not block collection until
finite storage limits are approached. At hard capacity, fail the whole affected
financial transaction safely and alert/pause; do not commit a change without its
outbox, drop corrections, or claim infinite offline durability.

Worker has SELECT on accepted source views and EXECUTE on narrow fenced sync
functions, with no direct canonical DML, DDL, producer administration or TradingView
permissions. Collector/review roles publish through the transaction-bound routine.
An external private continuity anchor records installation/epoch/destination and
acknowledged/staged high-water/hash evidence, atomically fsynced. Compare it and
company heads before recovery. Missing anchor or a restored DB behind it stops
delivery. A perfectly cloned DB+anchor+credentials cannot identify two machines;
distinct installations require separate credentials and explicit handover.
