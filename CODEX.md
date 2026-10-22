# Engineering procedure

For the current native installation use `docs/native-install.md` and
`simple_collector.py`/`simple_delivery.py`. It needs no source database, migrations
or worker credential provisioning. The older database/outbox procedures below
remain for existing installations and archives only. HTTP and open company access
are explicitly authorized; preserve source semantics and durable upload retries.

Read AGENTS.md and HANDOFF.md first, then the relevant code, callers, tests and
configuration. Inspect Git status and preserve unrelated local changes. Prefer the
smallest cohesive change that fixes the observed behavior; avoid unrelated refactors.

Current architecture and operation references:

- Collection and storage: docs/collector-operations.md, docs/database-schema.md.
- Bounded scheduling: docs/automatic-collector.md.
- Outbox: docs/source-outbox-operations.md and docs/milestone-3b1-design.md.
- HTTPS synchronization and recovery: docs/company-delivery.md.
- Workspace and checkpoints: docs/workspace.md.
- Publication/data restrictions: docs/publication-audit.md.

Inspect callers before changing interfaces. Retain decimal precision, instrument
isolation, evidence and ownership fences. Add behavioral regression tests for
nontrivial changes. Document semantic uncertainty rather than inventing provider
capabilities, units, market sessions, finality or real-time status.

Run the root commands specified by AGENTS.md. PostgreSQL tests require --postgres
and a private TSETMC_TEST_ADMIN_URL targeting a newly isolated endpoint. Their
fixtures create and drop only unique disposable databases. Do not bypass the
original-pilot protections, use company credentials, or start unrelated resources.

After validation, inspect the diff for unrelated changes and secrets, update current
docs and HANDOFF.md, and handle Git within the owner's explicit task authorization.
Checkpoint tags identify code; database backup/restore and deployment are separate.
Earlier milestone authorization narratives are archived under docs/history/.
