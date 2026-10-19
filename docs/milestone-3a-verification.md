# Milestone 3A verification — 2026-10-19

The technical scheduling foundation is implemented. **Full trading-session source
qualification remains pending.** No unattended collector, company integration,
synchronization or additional live instrument was activated.
Protected M2 commit: `01a827be39bb48864d0b76c8e952f176a4904556`.

## Implementation and financial compatibility

[Design](milestone-3a-design.md) identifies the new session/config/service/budget
modules, durable schedule/runtime/review persistence and CLI boundaries. Existing
HTTP client, financial models, parsers, current ordering and pure ChartData adapter
remain in use. No dependency or lock-file change was needed. Changes to the
existing repository preserve cached metadata's original evidence, bounded retry
history, and unresolved valid source conflicts during later history audits.

History maintenance uses existing refresh/reconcile/audit jobs. Deterministic
instrument/job/specification/slot run IDs survive crashes. Data commits precede
schedule completion; recovery after uncertain acknowledgment replays committed
results without HTTP. Missed intervals coalesce. Current polling is serial,
completion-relative and at least 30 seconds; full audits defer while current
observation is eligible. A monotonic deadline also bounds each operating window.

Default session expectation is UNKNOWN. Dated evidence and explicit provenance
control eligibility; neither old prices nor an assumed weekday/hour invent a
closure. Health separates actual process ownership, HTTP availability and accepted
source freshness. No missing calendar dates become fabricated candles.

Operator confirmation is single-date, explicit and reversible, tied to a financial
hash and two retained post-session observations separated by a minimum one-hour
operational grace. It is not upstream finality. All 4,662 pilot records remain
source_unverified; real review count is zero. Corrections reset local confirmation
while retaining the previous review. [Policy](daily-finalization-policy.md).

## PostgreSQL safety and preservation

The actual existing independent PostgreSQL **16.1** database/volume was retained.
Before upgrading, a private custom-format backup (1,181,360 bytes) was restored
into a generated disposable database. It contained head 0002, 4,662 daily records,
one snapshot and eight observations; all eight retained raw hashes verified.

Additive head `0003_scheduling` adds only scheduled_jobs, collector_runtime and
daily_reviews: 14 application tables total. Existing migrations and frozen M2
metadata remain unchanged. The persistent daily state fingerprint includes
instrument/date/financial hash/revision/finalization, and was identical before
upgrade, after upgrade and after live qualification. No persistent downgrade,
database reset, volume replacement or container restart was performed.

Disposable integration tests cover fresh install, populated M2 upgrade, downgrade
of only new tables, real migration-process death before transaction commit and
successful restart. Daily measurements, snapshots, revisions and raw evidence
survive those migration tests. No destructive test targets the persistent pilot.

## Test results

All automated source responses are mocked or explicitly private captured
regressions. Socket/DNS guards prevent TSETMC access. PostgreSQL tests use unique
disposable databases on actual 16.1. See the commands in
[operations](automatic-collector.md) and README. Final environment counts follow.

| Check | Result |
|---|---|
| Linux Python 3.12.15, public offline checkout | 189 passed, 78 skipped, 0 failed |
| Linux public checkout with PostgreSQL | 256 passed, 11 skipped, 0 failed |
| Windows Python 3.12.7 default, private captures present | 196 passed, 71 skipped, 0 failed |
| Windows full PostgreSQL suite | 264 passed, 3 skipped, 0 failed |
| Ruff lint / formatting | Passed on Windows and Linux |
| Strict mypy | Passed, 43 source/script files, both environments |
| Wheel + source distribution | Built successfully on Windows and Linux |
| Three opt-in live pytest cases | Not executed in M3A; skipped in automated runs |

Linux public skips comprise seven intentionally unpublished capture regressions,
three opt-in live tests and one Docker-exec backup test. The latter is exercised
on Windows with the explicit container setting. Default runs additionally skip
PostgreSQL tests by design. Private captures are not required by public CI.

Independent wheel installation into a fresh environment used locked runtime
requirements. Eleven CLI checks ran outside the source checkout: help, disabled
configuration validation, synthetic canonical/legacy export, accepted/default
database export, health, and four evidence inspection modes. The stored export
contained 4,662 equal-length chronological records, identical to the M2 export;
default finalized export stayed empty and legacy i:null stayed optional. The
installed wheel's bundled migrations independently created a fresh disposable
database at head 0003 with 14 application tables and no seeded instrument.

A second private post-qualification backup (1,194,551 bytes) restored successfully
at head 0003 with all 4,662 daily records, four snapshots and 16 verified raw
response hashes. Its complete daily state fingerprint matched the pre-M3A backup.

One earlier full Windows run encountered a five-second asyncpg connection timeout
at initial owner acquisition, with no scheduler assertion failure. The isolated
case passed immediately, and subsequent full verification passed. No test retry
plugin or increased database timeout was introduced to conceal it. Treat this as
a transient local availability observation, not proof that outages cannot recur.

New coverage includes session openings/closures/unknown/exception priority, timezone
history and year boundaries, repeated/older/unknown source clocks, financial
changes at equal source time, publication delays and provisional changes,
confirmation/revocation/late correction, cache expiry/identity changes, current
priority, scheduled refresh/audit/reconciliation, prolonged-offline coalescing,
wall-clock jumps, slow HTTP and simulated slow commits, actual scheduler process
death, cancellation in retrieval/persistence, duplicate ownership, actual backend
loss, 403/429/timeout failure bounds, protected evidence and synthetic A/B isolation.

## Bounded live evidence

Only فولاد was fetched. The experiment ran **11:04:13.985647–11:05:21.783396 UTC**
on 2026-10-19 (14:34:13.985647–14:35:21.783396 Tehran), with eight logical/wire
requests, zero retries and eight successes. Three current receipts were about
32 seconds apart with unchanged financial state/source clocks. Their reported
source age was about two hours; no first-publication delay was measured.

Two recent lists excluded the current date; the dated endpoint supplied it and
agreed with current measurements. The previous dated result agreed with the list.
The two dated responses were inspection-only: zero canonical updates. There is no
claim about the full `/0` list during that window, first daily publication,
permanent stability, or temporary omissions. Session conditions remained UNKNOWN.

The scheduler stopped at its six-request budget after five committed jobs; two
separately budgeted inspections then completed the eight-request experiment.
Afterward the pilot had 4,662 unchanged daily records, four current snapshots,
16 source observations, zero revisions/quarantines/reviews and two schedules.
Exact bodies, measurements, source clocks, hashes and detailed traces remain
private under ignored `.local/milestone3a/`. The aggregate
[source assessment](tsetmc-source-behavior.md) separates findings from hypotheses.

## Operation, security and next boundary

No collector remains running and no OS service/task or auto-start policy was
installed. Persistent pending schedules alone do not execute anything. Exact
captures, backups, credentials and financial exports remain ignored and excluded
from distributions; public tests/examples are synthetic. Software licensing and
source-data redistribution permissions remain unresolved; neither is invented.

The M1 tag and M2 commit are preserved. This report records pre-publication
verification; the owner subsequently authorized committing and pushing the reviewed
M3A changes directly to main. No new tag or release is authorized. TradingView worktree fingerprints are
unchanged against the pre-task snapshot; its code, Git state, configuration,
databases, volumes and deployment are outside this task and remain untouched.
The 111-file [project inventory](file-inventory.md) covers the project. Local
conversation and handoff notes are preserved in an ignored directory, excluded
from both Git publication and distributions without deleting their contents.

We are ready to **design** additive M3B contracts that carry uncertainty and
revisions. Full-session source qualification, session/calendar evidence,
publication timing, backup monitoring and retention/capacity planning still
precede unattended collection. [Next milestone proposal](next-milestones.md).
