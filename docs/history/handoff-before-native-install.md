# Current state — unified dashboard integration, 2026-10-21

The user requested connecting both collectors to one independent company API and
handling Git. This supersedes prior milestone-only prohibitions on implementing
integration. Original persistent pilot/runtime resources remain untouched.

Main includes `0005_delivery`, explicit archive enrollment, and a bounded HTTPS
worker with coordinator fencing, durable staged bytes/receipts/ACKs, external
continuity evidence and expired-session recovery. Company implementation lives on
audited `main` of tradingview-marketdata (c0ba9e1b or later). Never deploy the older
company codex/unified-dashboard-flow branch's incompatible alternative migration0011.
Read `docs/company-delivery.md` and its linked company setup guide first.

Validation uses synthetic records and isolated PostgreSQL 16.1, never the pilot.
The earlier company unified-dashboard-verification report describes the superseded
company branch; use current company HANDOFF.md for audited-main qualification.
No company service, live delivery or unattended collection was activated.
Recovery checkpoint tags were added during the later workspace cleanup; they
are not deployments or package releases.

Next: deploy matching commits to an approved staging company/source database,
configure real TLS and company login/BFF, and qualify the exact source registry.
Before unattended operation, address retained-batch audit limits, retention,
least-privilege worker SQL and actual restore procedures. Do not silently migrate
the original pilot or treat accepted history as finalized.

Review fixes: delivery no longer competes with the collector's lifetime ownership
lock. Independent coordinator-fenced transactions serialize with publication via
the existing stream clock rows. There is no connection-info permission flag;
real stage/receipt/ACK calls require an active delivery fence. Receipt audits check
the full saved receipt, and coordinator takeover serializes external-anchor writes.
No schema/protocol/frozen migration changed. The new PostgreSQL regression holds
the collector owner open, publishes during a mocked HTTP upload, rejects a second
worker, restarts without reupload, and rejects a changed acknowledged receipt.
Local review validation:372 passed,5 skipped on a newly initialized PostgreSQL16.1
cluster under ignored .local/delivery-review-20261021 (loopback56041). Skips: three
opt-in live tests and two optional backup tests. The source pilot was untouched.
Ruff/format and strict mypy passed. Final targeted delivery checks:19 passed.
Portable PostgreSQL dump/restore continuity checks:2 passed. The isolated test
cluster was stopped cleanly after testing; no persistent pilot resources changed.

PR #1 merged verified runtime9bee3ce in main5303516 after GitHub run39597489566
passed all jobs: Windows and Ubuntu251 passed/126 skipped each; PostgreSQL114
passed/2 optional backup skips. Local-only private captures account for the extra
local passes; these are offline regressions, not new live-provider qualification.
https://github.com/alpha-lacrim/tsetmc-marketdata/actions/runs/39597489566
## Workspace cleanup

The active folder remains on `main`. Both repositories preserve annotated
`checkpoint/unified-dashboard-2026-10-21` tags for the verified implementation
and `checkpoint/workspace-clean-2026-10-21` for the organized workspace.
Merged delivery/integration task branches were removed; commits remain in main.
No runtime, migrations, dependency locks or published milestones changed.

Conversation files moved into ignored `.local/notes/conversation-history/`.
Previous build outputs were archived externally; `LOCAL_WORKSPACE.md` records
private recovery locations. `.local/`, exports, captures, backups and the original
pilot remain intact. Historical agent context is in `docs/history/`; current
rules and procedures are concise in AGENTS.md and CODEX.md. The graph hook now
uses PATH instead of an operator-specific executable path. Generated navigation
and caches remain local. See `docs/workspace.md`.

Cleanup validation: pytest **258 passed / 119 skipped**, Ruff, formatting and
strict mypy passed. No database/live rerun was needed for this documentation and
configuration cleanup; prior database evidence above covers the unchanged runtime.
`graphify update .` refreshed local navigation; SQL graph extraction is unavailable
in the installed tool. Both repositories' archived ZIPs passed CRC checks; moved
source files were verified by SHA256. No persistent database or volume was changed.
