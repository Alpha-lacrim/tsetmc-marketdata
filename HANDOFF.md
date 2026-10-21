# Current state — unified dashboard integration, 2026-10-21

The user requested connecting both collectors to one independent company API and
handling Git. This supersedes prior milestone-only prohibitions on implementing
integration. Original persistent pilot/runtime resources remain untouched.

This branch adds `0005_delivery`, explicit archive enrollment, and a bounded HTTPS
worker with coordinator fencing, durable staged bytes/receipts/ACKs, external
continuity evidence and expired-session recovery. Company implementation lives in
the matching `codex/unified-dashboard-flow` branch of tradingview-marketdata.
Read `docs/company-delivery.md` and its linked company setup guide first.

Validation uses synthetic records and isolated PostgreSQL 16.1, never the pilot.
Final test results and remaining rollout limits are recorded in the company
`docs/unified-dashboard-verification.md`. No company service, live delivery,
unattended collection, tag or release was activated.

Next: deploy matching commits to an approved staging company/source database,
configure real TLS and company login/BFF, and qualify the exact source registry.
Before unattended operation, address retained-batch audit limits, retention,
least-privilege worker SQL and actual restore procedures. Do not silently migrate
the original pilot or treat accepted history as finalized.
