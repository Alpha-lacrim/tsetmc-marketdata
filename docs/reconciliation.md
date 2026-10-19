# Corrections and quarantine

List ingestion validates each record with the Milestone 1 parser. Invalid rows and
all records on conflicting duplicate dates enter durable quarantine while valid
dates commit. Identical duplicate dates are collapsed with the original warning.
Raw response bytes, offending row, source index, instrument/date, reason, first
and most recent observation, fingerprint and sightings are retained. Repeated
invalid evidence increments sightings rather than creating endless duplicates.
Accepted canonical data is never deleted because another retrieval is invalid.

Financial changes to an ordinary accepted list record create a revision with old
and new exact state/hashes/observations, increment revision number and atomically
replace canonical state. Unchanged financial values create no revision, even if
JSON order, source flags or receipt time change. All source prices stay unadjusted.

Targeted reconciliation independently parses each dated response. Invalid candidates
remain quarantined with a rejected decision; other valid candidates in that bounded
batch can still commit. A valid target may fill an absent canonical date, including
one whose list record was invalid. The decision and resolution retain references to
both sources, the accepted hash, method and time. A matching target confirms an
existing canonical record. Repeating the check creates new observation evidence
but no duplicate financial revision.

Two individually valid but financially different records remain unresolved. The
target is quarantined and a rejected decision says `two_valid_records_disagree`;
endpoint priority alone is not sufficient. A list disagreement cannot replace an
already reconciled canonical record either. No arbitrary manual override for such
daily conflicts is implemented; preserve the evidence for a future reviewed policy.
This also applies when conflicting duplicate list rows left no canonical record:
the target cannot resolve the dispute merely by matching one of those valid rows.
Reconciliation independently revalidates pending raw rows with the original parser
and keeps a valid disagreement open even when the target confirms an existing
canonical record. Invalid list/target rows alone do not block a validated repair.
Reconciliation means an accepted source decision, not proven daily finality.

## Original July 29 observation versus current source

Milestone 1 privately captured 2025-07-29 list `priceFirst=0` with positive activity,
while the targeted endpoint returned 2956. The list row was correctly quarantined.
Those original captures remain private; public tests use an explicitly synthetic
equivalent with different invented values and instrument identities.

Milestone 2 replayed the **original** captures in a separately named disposable
database: 4,660 list records accepted, one quarantined; the valid dated candidate
inserted the missing date, producing 4,661 canonical dates and one resolved
quarantine, with both source observations retained. Repeating reconciliation
produced zero revisions. The disposable database was removed after its private
report was saved. This was an offline capture replay, not a fresh HTTP observation.

The new live list on 2026-10-19 contains 4,662 valid dates and July 29 open=2956.
The live dated endpoint agrees. It is recorded as `target_confirms_canonical`;
no invalid row was invented in the live database to reproduce an obsolete anomaly.
The change between captures demonstrates why later correction audits matter, but
does not establish why the upstream archive changed or prove full completeness.
All 285 observed positive-trade official closes outside the executed range remain
unchanged. They are not quarantined merely for that behavior.
