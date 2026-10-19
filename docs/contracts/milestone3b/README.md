# PROPOSED tsetmc.v1 design artifacts

These are specifications and synthetic examples, **not implemented routes, runtime
models or captured market data**. [The wire document](../../milestone-3b-wire-contracts.md)
defines cross-field/financial/authorization semantics in addition to JSON Schema.

- schema.json: draft 2020-12, 27 shared definitions; strict proposed batch,
  receipt, reconciliation and error shapes. int64 numeric-string upper bounds,
  equality constraints, financial hashes, timezone conversion and transactional
  rules require semantic validation, not JSON Schema alone.
- examples-manifest.json: proposed=true, synthetic=true, 19 complete JSON files,
  each linked to its schema definition and exact UTF-8 SHA256. Upload-file hashes
  are the example X-Payload-SHA256 header values; receipt hashes must match them.
- examples/: eight request/receipt pairs plus reconciliation request/response and
  a new-route error. Decimal values are invented. One synthetic identity represents
  no authorized real instrument. Provenance digests hash synthetic labels; no real
  raw body or usable producer credential is included.

The daily/confirmation/revocation/correction files form an ordered toy lifecycle.
revision-seed then demonstrates an identical retained revision producing
recorded_no_change without altering the canonical state. Current/coverage/status
use independent stream positions. The unit profile is explicitly unverified.
Review summaries illustrate a trusted local policy outcome; complete private
review evidence is deliberately not a transferable market-data capture.

No example authorizes an HTTP call. Validation can load schema.json with a JSON
Schema 2020-12 validator, enable UUID/date/time format checks, and validate each
manifest file against its named $defs entry. The design task additionally checks
financial/record/payload hashes and negative cases offline. No project dependency
or lock-file change is required for these documents.
