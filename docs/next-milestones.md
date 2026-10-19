# After Milestone 3A

Milestone 2 implements the independent PostgreSQL collector described in
[design](milestone-2-design.md), [schema](database-schema.md),
[operations](collector-operations.md) and [verification](milestone-2-verification.md).
Its evidence, corrections, quarantine, latest state and restart protocol are local
only. No company integration or remote synchronization is implemented. The original
Milestone 2 proposal remains preserved in the immutable Milestone 1 tag.

Milestone 3A adds bounded foreground scheduling, conservative session evidence,
durable catch-up, health and auditable operator confirmation. Read its
[design](milestone-3a-design.md), [verification](milestone-3a-verification.md) and
[source qualification](tsetmc-source-behavior.md).

## Proposed Milestone 3B: synchronization contract design

We can design the company boundary now, provided source uncertainty is explicit
in the contract. Full-session qualification remains necessary before unattended
market collection; it need not block a design-only discussion. None of the
following synchronization components is implemented in M3A.

Keep the future boundary additive and provider-specific:

TSETMC APIs -> independent collector -> independent local TSETMC PostgreSQL ->
durable outbox -> independent HTTPS worker -> company FastAPI INGEST -> company
market storage -> READ/REST/WebSocket -> existing frontend.

First agree the company's additive ingest/read contracts without modifying any
TradingView route, table, deployment or collector. Namespace every object with
`provider=tsetmc` and string `ins_code`. Daily keys are instrument/date, independent
of TradingView minute-candle assumptions. Preserve separate last-trade and official
close fields, source/receipt instants, finality uncertainty and financial precision.
Use decimal strings or an explicitly specified exact numeric wire representation
for ingest; retain numeric float64 only at the ChartData presentation boundary.
Carry source-unverified versus locally confirmed finalization, its policy/evidence
and revocation. Operator confirmation is not an upstream guarantee.

Proposed local tables in a **later migration**, not implemented now:

- `sync_outbox`: immutable event UUID, ins_code, entity kind/key, canonical revision,
  financial hash, payload version, exact payload, creation time; unique event key
  based on provider/instrument/entity/revision or state hash.
- `sync_delivery`: event UUID and destination, attempt count, next retry, last error,
  acknowledgment/idempotency key and delivered time; unique(event,destination).
- `sync_checkpoints`: provider/instrument/destination/entity stream and acknowledged
  cursor, never advanced before durable acknowledgment.

Write outbox changes atomically with local canonical changes. The worker must not
hold collector ownership during HTTPS delivery, and remote downtime must not stop
local collection. Use authenticated TLS with secrets outside Git, bounded retries,
backoff, idempotent server acceptance, revision-aware conflict rules and replayable
acknowledgments. A stable event ID must survive timeout after remote commit.

Test duplicate/reordered deliveries, lost acknowledgments, remote downtime, crashes
before/after acknowledgment, historical revisions, confirmation/revocation, ambiguous source corrections,
multi-instrument isolation using invented identities, and backward compatibility
of existing TradingView behavior. Agree data redistribution/access permissions
before exposing raw evidence outside the independent collector.

## Qualification needed before unattended operation

Verify source session hours and holidays with defensible evidence; do not infer
Saturday-Wednesday activity. Agree and audit a daily-finalization policy before
using finalized candle streams. Establish an operator policy for two valid but
conflicting daily sources, raw/audit archival at scale, monitored backups away from
the host, alerts and disk capacity. Confirm performance and request budgets before
enabling another real instrument. The schema supports multiple instruments, but
only فولاد has live authorization or qualification.

Milestone 3B implementation requires its own authorization. Do not implement
synchronization, company FastAPI changes, deployment, new instruments or Git
publication as part of M3A. Separately approve a full-session source experiment
with declared dates, session evidence, request budget and post-session rechecks.
