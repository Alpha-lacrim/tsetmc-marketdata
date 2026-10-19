# Milestone 2 design

The protected Milestone 1 baseline is commit
`87690cb1f03f2b3deecb122c58eb48c06dff4e06`, tag `v0.1.0-milestone1`.
Milestone 2 reuses its async HTTP client, parsers, Decimal models, calendar utilities,
quarantine diagnostics and ChartData adapter. New dependencies are SQLAlchemy 2.x,
asyncpg and Alembic. PostgreSQL **16.1** is the actual database. asyncpg supports
the default Windows asyncio loop and Linux without a second transport or parser.

Compatibility plan: add storage and collector modules beside the pure source
models; migrate an independent empty database explicitly; retain every original
CLI command; add one-shot database jobs before optional polling. Preserve source
precision, original unadjusted prices and the original frontend adapter.

```
TSETMC HTTP -> existing parser/models -> instrument-owned transaction -> PostgreSQL
                                                |
                           raw bytes + canonical data + revisions + coverage
PostgreSQL -> typed daily records -> existing ChartData adapter -> local JSON
```

`collection/jobs.py` verifies metadata before retrieving observations.
`storage/repository.py` commits source evidence, accepted rows, revisions,
quarantine, coverage and the committed checkpoint in one transaction. A separately
committed running row records an attempted job before HTTP. No partial archive
chunk is advertised as complete. A few thousand daily rows fit this deliberately
simple transaction strategy. Interrupted imports can safely repeat the archive.

The implementation uses SQLAlchemy Core with async connections. Financial models
remain independent of SQL and HTTP. No ORM entity replaces a source model. Fresh
migrations use frozen versioned metadata, and an additive second migration
strengthens instrument provenance. Startup only checks the expected revision and
tables; it never creates or modifies schema.

Each instrument gets a unique integer ownership key in `instruments`. A dedicated
connection holds a two-key PostgreSQL session advisory lock. Every write transaction
checks that the same session still holds the correct instrument lock, before and
after its writes. A lost connection cannot transparently reconnect and continue
writing. Another process must acquire ownership and recover. Reads do not acquire
collector ownership. Different instruments can have different owners concurrently.

All daily uniqueness is `(ins_code, trading_date)`. Latest state, revisions,
quarantine, coverage, status and run recovery are instrument-scoped. Composite
foreign keys prevent cross-instrument evidence links. Configuration accepts a list
of instruments and the HTTP pool/pacing are configurable; only the approved pilot
is enabled, and the live CLI refuses other identities. Two invented identities are
used exclusively in offline tests. No schema or reusable job hardcodes فولاد.

Canonical hashes include exact financial measurements and identity, not response
key order, raw flags, receipt time or binary floats. Numerical trailing zeros and
negative zero normalize without Decimal context rounding. Raw hashes separately
identify exact retained bytes. Changed financial data creates one revision;
unchanged data only advances verified provenance. No corporate-action adjustment
is applied. See [schema](database-schema.md) and [reconciliation](reconciliation.md).

No API flag yet proves daily finality. Every new/corrected daily record remains
`source_unverified`. The default exporter excludes it; explicit
`accepted-unverified` selection preserves that uncertainty. Coverage is not a
trading calendar or a claim of full archive completeness.

Polling uses an injected clock and an explicit aware manual window, at most one
day, with a minimum 30-second interval. It is never started automatically. No
unattended historical scheduler, company API, remote synchronization, message
broker or deployment is introduced.
