# Proposed failure and recovery contract

**PROPOSED tests/behavior; not an operational deployment.** Delivery phases are
staged -> received -> acknowledged, with separate terminal quarantined/replaced
batches retaining original bytes. Only verified committed receipts authorize ACK.
No error path changes source financial values, invents finality, resets epochs or
grants itself ownership. [Wire details](milestone-3b-wire-contracts.md).

| Failure/scenario | Durable state and required behavior | Recovery and proving test |
|---|---|---|
| TSETMC temporarily unavailable | Existing accepted DB state/outbox remain valid; collector records source failure, worker can deliver committed state | Paced collector retry independently; test source outage with successful outbox delivery and unchanged clocks |
| Source PostgreSQL unavailable | No worker staging/ACK, no unfenced reconnect; keep in-flight bytes/receipt | Stop owner, restart/fence when DB available; kill actual backend during send and ACK |
| Source canonical commit uncertain | Canonical, revision, quality and outbox commit together or none | Replay existing collection run ID, inspect committed event identity; kill before/after commit |
| Collector restart | Durable outbox is independent of scheduler memory | Existing collector run/checkpoint recovery; assert no duplicate revision/event |
| Worker crash after staging | BYTEA/hash, selected IDs and after/through remain staged | Reload exact bytes, receipt probe/send; child-process death test |
| Crash after company reply before receipt storage | Company receipt may exist; source remains staged | Fetch original receipt, validate, record then ACK; no fresh logical observation |
| Crash after local receipt before ACK | phase=received and verified original receipt | Replay only fenced ACK, no HTTP required |
| WAN outage | Retain unacked prefixes/latest head/staged bytes, bounded backoff and logical capacity | Recover same identities; current lane first; test finite backlog and capacity refusal |
| Company FastAPI unavailable/TLS invalid | No assumed failure-to-commit; TLS failure never disables verification | Receipt probe after uncertainty, backoff for temporary availability; invalid CA stops |
| Company PostgreSQL unavailable | Atomic destination transaction rolls back or is uncertain to client; no in-memory success | 503/receipt lookup after recovery; restart destination DB in disposable test |
| HTTP response lost after successful commit | Immutable company receipt/ledger/events exist | Exact replay or receipt lookup; assert one financial change and journal event |
| Exact duplicate batch | Same producer/batch/bytes hash -> original receipt unchanged | Replay under valid session or lookup after rotation; compare receipt bytes/fields |
| Batch ID reused with different bytes | 409 batch_payload_conflict, no new data | Stop/quarantine staged operation, retain both local diagnostics; never overwrite ID |
| Observation UUID/position reused with different content | 409 observation_payload_conflict/source_version_conflict | Fence pending work; no automatic repair/new epoch; test cross-batch and cross-instrument attacks |
| Producer lease expires | Retain complete granted manifest and pending recovery bytes/ID | Same-producer recover only when all expected epochs/generations remain current; race/lost recovery reply tests |
| Key revoked/producer disabled | Authentication/policy rechecked under producer lock; pending data remains | Stop; administrator review/new credential only, no session discovery bypass |
| Ownership handover | Generation/epoch mismatch fences old worker and requests | Administrator-controlled transfer; old ACK cannot advance new owner's checkpoint |
| Source backup restore | Compare external continuity anchor, local heads and company heads/destination binding before staging/ACK | A rollback behind any proven staged/acked watermark stops. Full manifest detects more than count-only checks; test restored snapshot |
| Source epoch replacement | Epoch UUID is not ordered; old/new rows and IDs remain distinct | Explicit reviewed new epoch/grants/enrollment. Never automatically rotate epoch to escape a conflict |
| Company backup restore | Returned destination ID or heads/digests may regress | Fence delivery, compare retained receipts/full manifests, explicitly restore/replay. Restoring the same ID cannot be detected by ID alone; site restore must fence/rotate identity under admin procedure |
| Later daily correction | New financial revision + state_version/outbox append; prior confirmation reset | Ordered/idempotent application; test correction during initial archive upload and after confirmation |
| Finality-only confirmation/revocation | Same financial hash/revision, new public state version | Must replicate and emit verification event; no bulk source-finalization |
| Current N superseded while uploading | N's immutable bytes remain, N+1 pending atomically after canonical commit | ACK N can acknowledge N only; compare version+ID/hash before clearing; race test |
| Stale financial-state ACK | Company receipt must match original record; head ahead of known local state signals restore | Never overwrite pending newer state; validate receipt record hashes and local owner fence |
| Older/unknown source current response | Local rejected states never uploaded as accepted; destination repeats source-position guards | Preserve diagnostics; no receipt-time promotion or retry-created trade |
| Company consumer disconnect | Journal persists independently of sockets | Bounded replay/dedup; beyond floor reload REST; no exactly-once WS promise |
| Unverified daily row shown in dashboard | Only explicit accepted-unverified selection; metadata/token discloses uncertainty | Test finalized empty, opt-in exact values, warning retained through BFF |
| Company rejects one archive record | Whole batch rolls back, no partial ACK | Retain staged bytes, safe error index, review local mapping/unit/wire issue. Definitively rejected batches may be replaced/split with original record identities; do not mark canonical date delivered |
| Partial archive reconciliation | Bounded pages/digests plus durable source fence H and next cursor | Compare full ordered set and revisions, including extras/missing; never infer completeness from 4,662 count |
| Upload order differs from trading dates | source_position/state_version, not date order, governs mutations | Retain older states/revisions as evidence without reverting canonical; reverse-order synthetic test |
| Many instruments contend | Distinct ins_code/epoch/worker ownership; shared configured admission budget | Fair current-first/round-robin scheduling, reserve TV capacity; two synthetic instrument tests, no real scaling benchmark |
| Outbox/storage cap reached | Unacked evidence protected; no commit without corresponding outbox | Alert/stop affected collection transaction before capacity exhaustion; do not drop corrections or promise unbounded offline duration |

## Expired session and uncertain upload ordering

1. Keep the exact pending batch bytes/hash and original observation identities.
2. Query the producer-only receipt with a valid current credential. A receipt
   proves that batch committed; verify every field before local receipt persistence.
3. If the old session expired and no receipt is yet visible, commit/replay the
   durable recovery operation with its unchanged complete manifest. Recovery must
   serialize with producer locks, so no old-generation upload can later commit.
4. Query the original receipt again after that fence. If still absent, stage a
   replacement batch UUID/new session envelope with **unchanged** records. Mark
   old batch replaced, retaining bytes and linkage. Replaced is not acknowledged.
5. Commit receipt and ACK in their separate durable phases. A stale local worker
   response cannot bypass a lost worker ownership lock.

Changing ownership/epoch, another winning recovery, revocation or a missing anchor
stops this flow. Never follow an unknown replacement session returned to another
installation. Missing receipt alone, before fencing, does not prove original
failure. Exact duplicate observations across replacement batches remain idempotent.

## Restore limitations and repair authority

An external private fsynced anchor records installation, producer, instrument/
epochs, destination identity, heads, pending batch IDs/hashes and verified receipts.
Keep it outside a database-only backup rollback and back it up securely. Compare
source and company financial/state/revision manifests before resuming. A perfectly
cloned DB+anchor+credentials cannot distinguish two machines; unique credentials
and administrator handover are required. Arbitrary corruption with plausible newer
barriers may still need explicit evidence-based repair; do not promise automatic
disaster recovery from every corruption pattern.

Repairs use new durable resnapshot events bound to genuine accepted local state,
not edited prices or overwritten old observations. Any policy that resets a
company barrier, replaces an epoch or re-enrolls an installation is administrative
and separately authorized. All restore/downgrade/kill tests use disposable source
and destination databases. No such operation is performed on existing databases
or the company server during this design task.
