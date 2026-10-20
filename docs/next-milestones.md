# Completed milestones and proposed implementation

Milestones 1, 2 and 3A implement the independent TSETMC source client/models,
PostgreSQL 16.1 persistence and bounded operator-controlled scheduling. Published
M3A baseline: 6b95c899a7c78f4f62c580c56eb124eb310f076b. The historical report records
4,662 accepted daily rows; upstream finality and full-session qualification remain
unverified. No source history is automatically finalized.

## Milestone 3B-D: completed design scope

The integration specification proposes two independent source pipelines entering
**one shared company FastAPI product**, with existing READ/INGEST roles. It does
not implement or activate synchronization, company routes, migrations or producers.
The documented prepared company baseline is 1.1.0rc1 / destination 0010 at public
reference e114a25be8679451f6064ad1fb03c0ef6a8aaefe. Actual company deployment is
unverified; the owner explicitly clarified this. No company server was contacted.

- [Design and verified source/release revisions](milestone-3b-design.md)
- [Actual compatibility matrix](milestone-3b-compatibility-matrix.md)
- [Versioned wire contracts](milestone-3b-wire-contracts.md) and
  [synthetic schema/examples](contracts/milestone3b/README.md)
- [Commit-safe source outbox and initial seed](milestone-3b-source-outbox.md)
- [Additive company persistence/authentication](milestone-3b-company-storage.md)
- [REST, ChartData, finality metadata and WebSocket](milestone-3b-rest-websocket.md)
- [Failure/recovery matrix](milestone-3b-recovery.md)
- [Future acceptance tests](milestone-3b-test-plan.md)
- [Incremental implementation/release sequence](milestone-3b-implementation-sequence.md)

## Milestone 3B-1: source publication foundation

Source migration 0004_outbox and local transactional publication/staging primitives
are implemented and qualified only on synthetic disposable PostgreSQL 16.1.
See [implementation/deviations](milestone-3b1-design.md),
[verification evidence](milestone-3b1-verification.md) and
[safe operations](source-outbox-operations.md). The original pilot is unchanged;
no actual archive seed, network worker, producer or company endpoint is activated.
The previous M3B-D specification remains a published design at
0a770a050e1939b1fa26ba00c86ff45696ea366f.

## Next authorization: M3B-2 company INGEST/storage

Review contract/units/redistribution evidence and the real company baseline first.
Next separately authorize company schema/control-plane 0011 and additive TSETMC
ingestion, preserving the existing TradingView contracts. Independent worker,
producer coordinator/external anchor, real enrollment/parity and shared READ/frontend
remain later stages, with their own tests. Company revision IDs are proposed; reserve new
numbers if intervening work changes those heads. The candidate company version is
proposed 1.2.0rc1, not an existing release. Preserve frozen 1.1.0rc1 and all TradingView
contracts; do not run destination migrations on a source database.

Only a later explicit site task may inspect/change actual company deployment,
provision credentials or transfer real data. No direct worker-to-company PostgreSQL
connection belongs in the topology. Independent source databases, credentials,
installation identities, epochs, ownership, pending batches and recovery remain
mandatory. Current last trade stays separate from official close; ChartData keeps
a-h, genuine f/g/h, UTC-midnight date labels and optional legacy i:null.

Before unattended acquisition, separately qualify a full source session,
calendar/state evidence, publication timing, correction policy, capacity and backups.
Unknown session/finality must remain visible in bounded transfers meanwhile; a
successful HTTPS pipeline cannot establish upstream finality or trade completeness.
Only فولاد has live authorization. Bulk market-watch acquisition is another source
milestone, not part of the synchronization protocol. No additional real instrument,
company change, deployment, Git commit/push/tag/release is authorized by 3B-D.
