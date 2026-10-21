# Archived context — not current policy

See root AGENTS.md, CODEX.md and HANDOFF.md for current instructions.

# Working context

Current scope (2026-10-21): the owner explicitly requested the shared company API
integration, collector synchronization, end-to-end verification and Git handling.
That request supersedes the historical milestone restrictions below on implementing
integration and publishing task branches. Preserve the original pilot and frozen
releases. No unattended deployment or expanded live instruments were activated.
Read HANDOFF.md and docs/company-delivery.md for the current implementation.

Read AGENTS.md and README.md. This is the independent TSETMC collector project,
independent from Alpha-lacrim/tradingview-marketdata. The owner authorized public
Milestone 1 baseline publication and the v0.1.0-milestone1 tag. Further publication,
release or implementation work requires its own task. Genuine source captures and
local audit backups are ignored; do not force-stage them. Read
docs/publication-audit.md for the data-redistribution decision. Historical findings
and unresolved semantics live in docs/api-research.md and docs/pilot-verification.md.
The owner explicitly authorized Milestone 2 PostgreSQL persistence and local
collectors and subsequently authorized committing and pushing the verified
Milestone 2 implementation directly to main. No new tag or release is authorized.
Read docs/milestone-2-design.md, docs/database-schema.md and
docs/collector-operations.md. No company integration or deployment is authorized. Instrument scoping
is mandatory from the start; only فولاد may be used for live qualification.

Milestone 3A now authorizes source-behavior qualification, conservative session
expectations, durable operator-controlled scheduling, health and auditable daily
reviews. Read docs/milestone-3a-design.md and docs/automatic-collector.md. The owner
subsequently authorized committing and pushing the reviewed Milestone 3A changes
directly to main. This publication authorization does not include a tag or release.
Do not start company integration or remote synchronization, activate unattended
collection, or expand live instruments.

Milestone 3B-1 separately authorizes only the local source outbox, source migration
0004_outbox and synthetic/disposable PG16.1 qualification. Preserve the original
pilot as read-only; do not migrate or seed it. No network worker, real receipt,
producer credential, company schema/route or deployment is authorized. Stage 4
coordinator/anchor behavior and Stage 5 real archive transfer remain deferred.
The owner subsequently authorized committing and pushing these reviewed changes
directly to main. This authorization does not include a tag, release or deployment.
