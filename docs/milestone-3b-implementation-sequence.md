# Proposed implementation sequence and release gates

**DESIGN ONLY.** Every stage below requires its own implementation authorization.
No worker, API route, migration, producer, deployment, live transfer or Git
publication is performed by this milestone. No stage implicitly authorizes the
next. Actual company deployment remains unverified; 1.1.0rc1/0010 is the prepared
compatibility baseline, not a statement that it is running at the company.

| Stage | Small deliverable | Acceptance / stop point |
|---|---|---|
| 0. Contract review | Agree tsetmc.v1 schemas, registry/units evidence, source finality labels, company namespace and privacy/redistribution permissions | Resolve version/field ownership and site inventory; use synthetic examples, no production connectivity required |
| 1. Source transactional publication | Review/create additive source 0004, instrument/stream counters, immutable daily/coverage outbox and current/status heads; hook existing transactions/reviews | S01–S06 real PostgreSQL tests; preserve canonical source values and existing APIs; worker remains disabled |
| 2. Company control plane/storage | New company 0011 after verified 0010; typed TSETMC registry/legacy isolation, stream constraints/recovery allowlists, namespace tables and restricted role checks | Populated migration/rollback tests only in disposable DBs; preserve all legacy TradingView suites and original candidate checksums |
| 3. Additive ingestion | New strict TSETMC subrouter/writer and receipt/reconciliation schemas in existing INGEST factory | Atomic ledger/data/event/receipt, auth/fencing/version/hash tests; original endpoints unchanged, no real producer |
| 4. Independent worker | TSETMC-only config/token/anchor, worker ownership, immutable staging, receipt/ACK, expiry recovery, backoff and current-first fairness | Actual process-kill/local TLS/two-DB tests; no TradingView module/database/runtime coupling |
| 5. Initial enrollment + parity | Explicit bounded seed of already committed local state, revision evidence and coverage; live correction follows higher version | Synthetic source archive/current parity at a captured H, retry and restore tests; actual 4,662-row seed requires separate transfer approval |
| 6. Shared READ/frontend | New TSETMC discovery/daily/current/ChartData/metadata/status/WS routes and namespace reader in existing READ app | F01–F04, old REST/WS golden contracts, selection honesty and multi-replica metadata consistency |
| 7. Recovery/capacity qualification | Inject WAN/DB outages, backup restores, competing owners, storage caps and backlog/current contention | Complete failure matrix; measured synthetic fairness/latency budgets, not inferred capacity from schema readiness |
| 8. New release candidate | Reserve proposed company 1.2.0rc1; freeze source hashes, manifests, migration/grant scripts, READ/INGEST image and independent source/worker artifact | Fresh Windows/Linux install and exact-image two-role TLS verification, no frozen 1.1.0rc1 replacement |
| 9. Site approval | Separately verify running company version/head, approved source mappings/epochs, gateway/TLS, least privilege, off-host backups and rollback | Explicit company deployment and real producer activation authorization; never inferred from this design or an earlier Git push |
| 10. Controlled pilot transfer | Only approved فولاد history/current, bounded seed and request budgets; reconcile exact state/quality/revisions before dashboard enablement | Separate authorized operation; no new live instrument, no minute-candle reinterpretation or automatic finalization |

Stage numbers are proposed implementation slices, not claims of completed work or
new deployed product versions. Stages 2–6 must land together in a release that is
backward compatible, although development/testing is incremental. Source 0004 and
company 0011 are separate migration lineages. Reserve those revision IDs again
when work begins; if intervening authorized migrations exist, append after the
new verified heads instead of reusing a number.

## Site rollout and rollback design

The company maintainer first inventories the actual running image/version/schema
under separate site permission. Back up and restore-check the dedicated market-data
DB in isolation, preserve the frozen artifact and current TradingView configuration,
and qualify the new release with TSETMC disabled. No company database needs a
public port; all uploads use the gateway and independently provisioned producer.

Old 1.1.0rc1 rejects destination heads other than 0010. Therefore this is **not**
a zero-downtime arbitrary mixed-binary rollout promise. Use a reviewed maintenance
window/ingestion drain: existing source workers retain pending data, stop INGEST
writes, perform additive migration, update both role binaries/grants, verify old
TradingView contracts with TSETMC disabled, then resume existing ingestion.
Unrelated company application storage stays untouched. Never edit frozen migrations.

Application rollback on 0011 uses the verified new-release compatibility mode with
TSETMC disabled, keeping TradingView serving from the same approved schema. Do not
restart frozen 1.1.0rc1 against 0011 or downgrade persistent data blindly. A true DB
rollback requires separately approved restore/cutover and reconciliation of writes
since the backup. No running installation is changed by this task.

After separate authorization, provision only the approved TSETMC mapping, producer,
stream grants, source epochs and independent credentials. Send no real market data
until rights, units, site TLS and restore/ownership procedures are approved. Keep
full-session source qualification and unattended service activation separate: a
reviewed bounded transfer can preserve unknown session/finality without claiming
the acquisition service is production-qualified.

## Design-time verification record

The design task inspected source and frozen release files read-only and compared
their normalized hashes; deployment was not probed. The original local handover
ZIP hash matches the published M5 value and passes ZIP CRC checking; all 79
SHA256SUMS payload entries verify. All 41 packaged Python/migration files match
the current public source. No newer tagged release/distribution was
found in the inspected reference revision. Its source_version and destination
head remain 1.1.0rc1 and 0010 respectively.

Verification performed on Windows/Python 3.12.7, 2026-10-19:

| Check | Actual result |
|---|---|
| uv run --offline pytest -q | **196 passed, 0 failed, 71 skipped**: 68 require opt-in PostgreSQL and 3 require opt-in live API access. Seven passing tests use already retained private captures locally; those captures remain excluded from Git |
| uv run --offline ruff check . | Passed |
| uv run --offline ruff format --check . | Passed; 103 files already formatted |
| uv run --offline mypy | Passed strict checking; 43 source files |
| Proposed JSON Schema and synthetic examples | Draft 2020-12 schema valid; 27 definitions, 19 complete examples passed, 15 malformed/inconsistent variants rejected; financial/record/payload/page hashes and review/correction lifecycle checks passed |
| Existing pure financial models/adapter versus synthetic examples | Daily/current native hashes match; four price-change calculations, numeric a-h mapping and optional i:null match |
| Documentation/public artifact audit | All 32 changed files are design documentation/JSON; local links resolve and 17 pinned company code links match the inspected snapshot; no private absolute paths, credential URLs, token/private-key patterns or private IPv4 addresses found |
| Project isolation | Before/after fingerprints match for the legacy worktree, older reference clone, 599-file current worktree and 80-file frozen handover tree; original TSETMC HEAD unchanged and index empty |

No build was needed or performed for these documentation-only changes. Company
regression suites, PostgreSQL/live tests, new outbox/transport/company/rollout tests
and full-session qualification were **not executed**. The proposed runtime does
not exist yet; schema/example checks cannot establish its transactional correctness.
No dependency, lock file, source, test, configuration or migration was changed.

The owner separately authorized committing and pushing these design artifacts to
main on 2026-10-19. This authorizes publication only. TradingView source,
Git state, frozen package bytes, company FastAPI code, database configuration,
containers, persistent databases and deployments remain unchanged. Local inspection
snapshots/check logs stay ignored; public design artifacts contain synthetic data.

## Complete changed-file inventory

Relative to the published M3A baseline, one existing document is modified and
31 files are new. Paths below are relative to the repository root. Publishing
these artifacts does not implement the proposed contracts or authorize deployment.

| Design document | Role |
|---|---|
| [docs/milestone-3b-design.md](milestone-3b-design.md) | Baselines and architecture |
| [docs/milestone-3b-compatibility-matrix.md](milestone-3b-compatibility-matrix.md) | Actual source/destination differences and references |
| [docs/milestone-3b-wire-contracts.md](milestone-3b-wire-contracts.md) | Proposed precise protocol |
| [docs/milestone-3b-source-outbox.md](milestone-3b-source-outbox.md) | Atomic publication, staging, seed and ACK rules |
| [docs/milestone-3b-company-storage.md](milestone-3b-company-storage.md) | Proposed tables, roles and migration boundaries |
| [docs/milestone-3b-rest-websocket.md](milestone-3b-rest-websocket.md) | READ/frontend and journal contract |
| [docs/milestone-3b-recovery.md](milestone-3b-recovery.md) | Failure matrix and restore limits |
| [docs/milestone-3b-test-plan.md](milestone-3b-test-plan.md) | Future implementation gates |
| [docs/milestone-3b-implementation-sequence.md](milestone-3b-implementation-sequence.md) | Stages, rollout, verification and this inventory |
| [docs/next-milestones.md](next-milestones.md) | Modified completion/future-work index |

Contract files under `docs/contracts/milestone3b/`:

- [README.md](contracts/milestone3b/README.md)
- [schema.json](contracts/milestone3b/schema.json)
- [examples-manifest.json](contracts/milestone3b/examples-manifest.json)
- [examples/daily.request.json](contracts/milestone3b/examples/daily.request.json)
- [examples/daily.receipt.json](contracts/milestone3b/examples/daily.receipt.json)
- [examples/confirmation.request.json](contracts/milestone3b/examples/confirmation.request.json)
- [examples/confirmation.receipt.json](contracts/milestone3b/examples/confirmation.receipt.json)
- [examples/revocation.request.json](contracts/milestone3b/examples/revocation.request.json)
- [examples/revocation.receipt.json](contracts/milestone3b/examples/revocation.receipt.json)
- [examples/correction.request.json](contracts/milestone3b/examples/correction.request.json)
- [examples/correction.receipt.json](contracts/milestone3b/examples/correction.receipt.json)
- [examples/revision-seed.request.json](contracts/milestone3b/examples/revision-seed.request.json)
- [examples/revision-seed.receipt.json](contracts/milestone3b/examples/revision-seed.receipt.json)
- [examples/current.request.json](contracts/milestone3b/examples/current.request.json)
- [examples/current.receipt.json](contracts/milestone3b/examples/current.receipt.json)
- [examples/coverage.request.json](contracts/milestone3b/examples/coverage.request.json)
- [examples/coverage.receipt.json](contracts/milestone3b/examples/coverage.receipt.json)
- [examples/status.request.json](contracts/milestone3b/examples/status.request.json)
- [examples/status.receipt.json](contracts/milestone3b/examples/status.receipt.json)
- [examples/reconcile.request.json](contracts/milestone3b/examples/reconcile.request.json)
- [examples/reconcile.response.json](contracts/milestone3b/examples/reconcile.response.json)
- [examples/error.response.json](contracts/milestone3b/examples/error.response.json)
