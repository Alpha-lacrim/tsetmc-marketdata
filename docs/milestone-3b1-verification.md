# Milestone 3B-1 verification — 2026-10-20

Source-only qualification; no delivery or company integration. Starting branch
`main`, HEAD `0a770a050e1939b1fa26ba00c86ff45696ea366f`, initially clean, origin
`https://github.com/Alpha-lacrim/tsetmc-marketdata.git`. No branch alignment/reset,
commit, push, tag or release was performed during implementation. The owner
subsequently authorized committing and pushing the reviewed changes directly to
main on 2026-10-20; no tag, release or deployment is authorized. The implemented specification and
explicit Stage 4/5 deferrals are in [the design](milestone-3b1-design.md).

## Environment and isolation

Windows, Python 3.12.7, PostgreSQL server_version_num **160001**. Docker's Linux
engine was unavailable and the Docker service stopped at inspection; neither was
started. Container/volume live inventory therefore could not be verified. The
retained configuration names the original tsetmc-m2-local project/container and
127.0.0.1:5542/tsetmc_marketdata endpoint. Its last reported head is 0003_scheduling;
actual running pilot contents/head remain **unverified in this task**.

All writes used a newly initialized portable PG16.1 cluster under ignored
.local/milestone3b1/cluster, listening only on 127.0.0.1:4194, separate from the
original port. No Windows service, auto-start, old volume or company connection
was installed/used. Before test writes, the private runner checked actual
data_directory against that exact task path, version 160001, separate port and
task-generated bootstrap DB. Every test then used a newly generated disposable
tsetmc_test_<hex> database. Credentials stayed in ignored files/child environments.

Portable binaries came from the EDB archive linked through the
[PostgreSQL Windows downloads](https://www.postgresql.org/download/windows/)
and [EDB binary distribution](https://www.enterprisedb.com/download-postgresql-binaries).
Downloaded [16.1 ZIP](https://get.enterprisedb.com/postgresql/postgresql-16.1-1-windows-x64-binaries.zip)
size: 347,492,840 bytes; computed SHA256
`0179cc6d863139b68d1d1a69bdb58db766b040c6b6f2976dd1c5adf83dd0b6de`.
Binary --version and the actual connected server both reported 16.1. Binaries and
cluster are private tooling, excluded from Git/package archives.

The original pilot was **not contacted, migrated, seeded, backed up or restored**.
Its configuration-file hashes and all frozen 0001–0003 migration/schema hashes
are checked unchanged. No real 4,662-record fingerprint comparison is claimed.
TradingView, frozen company FastAPI, company databases, containers and deployments
are outside the write/test boundary. There were no TSETMC API requests or live tests.

## Source migration and financial preservation

Fresh 0001→0002→0003→0004_outbox, populated 0003 upgrade, interrupted migration
child-process death/re-run, and downgrade/re-upgrade were exercised only in
disposable databases. Seven new source tables bring the total to 21. Three trigger
functions/four triggers protect immutable outbox/evidence, batch lifecycle and
dataset identity. The conditional collector grant branch was exercised under
SET ROLE in the disposable instance; a test-created NOLOGIN role was removed.
No production role/login/secret was provisioned.

The populated migration and seed checks compare every row of all 14 original
tables, including NUMERIC measurements, financial hashes/revisions, raw bodies and
hashes, current snapshots/pointer, reviews, quarantine, coverage and scheduler state.
All compare equal where preservation is required. Synthetic dump/restore also
preserves those original tables and exact staged request bytes; externally supplied
newer continuity proof then correctly fences the restored older source state.

These are **synthetic** integrity results. An actual restored pilot backup was not
authorized or used. The historical reported 4,662 real rows and 285 genuine close/
range discrepancies were neither re-fetched nor altered.

## S01–S06 evidence

| Gate | Actual local evidence |
|---|---|
| S01 | Ten real child-process deaths: new daily state, correction, current, quarantine and review, each before/after commit. Canonical state/revisions/reviews/outbox/clock agree all-or-none |
| S02 | Two real database connections: A allocates/pauses; same-stream B remains blocked until A commits/rolls back; rollback reuses the correct next position. Synthetic B instrument progresses independently. A separate unsafe sequence test demonstrates the skipped-watermark counterexample |
| S03 | Confirm/revoke/reconcile/open-conflict versions at unchanged financial hash; exact applied review IDs despite equal timestamps; no daily event on raw-only replay; two in-transaction corrections retain intermediate audit evidence plus one final canonical state |
| S04 | Accepted current ordering, repeated-state seed, rejection of old/unknown/ambiguous state and corrupt older resnapshot; immutable staged N; saved/validated simulated receipt; ACK(N) leaves N+1 pending for both current and status; A→B→B local false retains B; original status expiry preserved |
| S05 | Two invented instrument identities, composite epoch/binding/provenance checks, immutable SQL evidence/batches, independent ACKs, actual backend termination and stale-session refusal. No live producer coordinator/recovery state exists; that part of S05 is deferred |
| S06 | Bounded consistent seed, retained revision and current head, 47 lossless coverage pages, later correction at a higher position/version, complete rollback on row/byte limit refusal, no original-table mutation |

The full-size invented seed contains exactly **4,662 dates**, one retained financial
revision, one current head and **285 synthetic official closes outside high/low**.
Its measured output is **4,711 records / 8,190,383 serialized bytes**, below 32 MiB.
This includes one revision seed, 4,662 daily seeds, 47 coverage pages and one current
seed. No complete exchange archive or genuine-session coverage is inferred.

Additional tests cover the 19 unchanged published synthetic wire examples, strict
decimal strings, unknown fields, financial/record/payload hashes, dates/clock
consistency, finality, record limits, missing/extra/tampered receipts, capacity
refusal, source evidence retention and read-only disabled status inspection.

## Execution results

| Environment/check | Passed | Failed | Skipped / not executed |
|---|---:|---:|---|
| Windows default offline suite | 240 | 0 | 118: 115 opt-in PostgreSQL, 3 opt-in live |
| Windows complete suite with verified disposable PG16.1 | 354 | 0 | 4: 3 live, 1 legacy Docker-exec backup regression |
| PostgreSQL portion of that complete run | 114 | 0 | 1 legacy Docker-exec backup regression; portable dump/restore passed |
| Published synthetic wire examples | 19 | 0 | Included in the offline suite; 44 new wire/unit cases total |
| Ruff lint / formatting | Passed | 0 | 114 files formatted |
| Strict mypy | Passed | 0 | 46 source/script files checked |
| uv sync --locked --offline | Passed | 0 | Lockfile reproducible |
| Wheel and source distribution | Built | 0 | Task-private artifact directory only |
| Fresh independent wheel environment | Passed | 0 | Locked runtime requirements, 7 installed CLI checks, bundled wire schema and fresh migration verified |
| Linux, live APIs, real company/worker tests | — | — | Not executed in this local task |

The default run took 1.72 seconds and the final complete run 165.26 seconds.
Seven passing regression cases use already retained private captures; their inputs
stay excluded from Git and distributions. They skip explicitly in a public clone.
Neither capture regressions nor synthetic tests establish fresh API behavior.
No skipped or unimplemented Stage 4/5 behavior is counted as a pass.

Independent installation ran outside the source import path in a new virtual
environment, with runtime versions from uv.lock. Bundled migrations independently
created head 0004_outbox with 21 tables and zero instruments/datasets. Bundled JSON
Schema contains 27 definitions and validates the proposed daily example. Seven
CLI checks covered help, synthetic canonical/legacy ChartData, db-status, disabled
collection-status, and empty database canonical/legacy exports. Real f/g/h values,
official close, equal array lengths and optional i:null were checked. No source
fetch or real dataset enrollment occurred in these installation checks.

One earlier development full run reported a failure in the unchanged existing
10 ms HTTP pacing test under local load (348 passed, 1 failed, 4 skipped). Its
isolated rerun passed unchanged; no timing threshold, retry plugin, HTTP code or
test skip was introduced. The subsequent 349-pass full run also passed that test;
additional boundary tests were then added before final verification.

The final public-file scan covers all 25 changed text files: no credential URLs,
tokens/private keys, private absolute paths or private IP patterns were found;
documentation links resolve. Wheel/sdist member audits exclude private captures,
task tooling/binaries/databases, environments, Git metadata and conversation notes.
Read-only fingerprints match the prior inspection baselines for both older
TradingView worktrees, the 599-file current reference tree and 80-file frozen
company package. Pilot configuration and frozen source migration/schema hashes
also match the start-of-task inventory. No unrelated Git state was changed.

After test/install checks, all generated test databases had been dropped; only
the task bootstrap database remained. The exact task data directory was verified
again before cleanly stopping its PostgreSQL process. Private cluster files and
evidence are retained ignored for review; no service or listener was left running.

## Changed files and review checkpoint

At the implementation review checkpoint, HEAD remained
`0a770a050e1939b1fa26ba00c86ff45696ea366f` on main and all changes were
unstaged/uncommitted. The later publication authorization covers this reviewed
baseline. Complete 25-file inventory relative to the published design baseline:

| Modified existing file | Change |
|---|---|
| [AGENTS.md](../AGENTS.md) | Current source-only authorization and pilot safety |
| [CODEX.md](../CODEX.md) | Milestone context and explicit deferrals |
| [README.md](../README.md) | Source outbox overview and unupgraded pilot warning |
| [docs/database-schema.md](database-schema.md) | 0004/21-table source schema |
| [docs/next-milestones.md](next-milestones.md) | Source stage completion and M3B-2 prerequisites |
| [docs/recovery-and-backup.md](recovery-and-backup.md) | Protected pilot boundary |
| [pyproject.toml](../pyproject.toml) | JSON Schema validator, typing stubs and schema packaging |
| [uv.lock](../uv.lock) | Locked validator dependencies |
| [storage/database.py](../src/tsetmc_marketdata/storage/database.py) | Explicit new source head/table verification |
| [storage/queries.py](../src/tsetmc_marketdata/storage/queries.py) | Read-only publication status and protected retention |
| [storage/repository.py](../src/tsetmc_marketdata/storage/repository.py) | Atomic touched-state publication hooks |
| [storage/reviews.py](../src/tsetmc_marketdata/storage/reviews.py) | Exact review publication before commit |
| [storage/scheduling.py](../src/tsetmc_marketdata/storage/scheduling.py) | Runtime status hooks |
| [test_migration_3a.py](../tests/integration/test_migration_3a.py) | Expected latest source head; historical migration unchanged |

| New file | Purpose |
|---|---|
| [docs/milestone-3b1-design.md](milestone-3b1-design.md) | Implemented source design/deviations |
| [docs/milestone-3b1-verification.md](milestone-3b1-verification.md) | This evidence/report |
| [docs/source-outbox-operations.md](source-outbox-operations.md) | Safe inspection, synthetic seed, recovery/capacity |
| [0004_outbox.py](../migrations/versions/0004_outbox.py) | New source migration/guards/grants |
| [storage/schema_v3b1.py](../src/tsetmc_marketdata/storage/schema_v3b1.py) | Additive frozen source table definitions |
| [storage/publication_wire.py](../src/tsetmc_marketdata/storage/publication_wire.py) | Canonical wire/hash/semantic validation |
| [storage/outbox.py](../src/tsetmc_marketdata/storage/outbox.py) | Publication, seed, local stages and continuity checks |
| [test_publication_wire.py](../tests/unit/test_publication_wire.py) | Synthetic positive/negative wire cases |
| [test_source_outbox.py](../tests/integration/test_source_outbox.py) | Transaction/concurrency/review/seed/migration gates |
| [test_local_sync_state.py](../tests/integration/test_local_sync_state.py) | Coalescing, ACK, isolation and capacity |
| [test_outbox_recovery.py](../tests/integration/test_outbox_recovery.py) | Disposable dump/restore and role grants |

Private tooling, database/binaries, dump bytes, logs, installation environments and
capture inputs remain ignored; none is a changed public source artifact. No
software license or genuine-data redistribution permission was added.

## Deferred qualification and next stage

Not exercised: Linux execution in this local task, live TSETMC tests, actual pilot
restore/migration/seed, real company receipt/authentication, TLS upload, producer
leases/rotation, independent worker ownership, external anchor persistence or
company archive parity. A supplied local continuity proof test cannot establish
those future operational guarantees. Company deployment stays unverified.

M3B-2 prerequisites: review tsetmc.v1 semantics/units/redistribution evidence;
independently confirm the actual company source/release/schema baseline under a
separate task; reserve an additive company migration after its then-current head;
implement provider-specific INGEST/storage with shared auth/ownership/receipts;
retain all original TradingView regression contracts; qualify synthetic two-role
and atomic ledger/data/event/receipt tests before any real producer activation.
Do not apply source 0004 to the company database or implement company 0011 here.
