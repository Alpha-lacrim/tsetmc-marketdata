# Daily publication and local confirmation

Source retrieval, validation, reconciliation, operational confirmation and immutable
upstream finality are different claims. The APIs do not yet provide a qualified
finality signal. `iClose`, `yClose`, `last`, a clock crossing a closing hour, or
repeated equal responses never automatically finalizes a daily record.

| Evidence/state | Interpretation |
|---|---|
| Successful raw daily response | A retained source observation, possibly malformed or absent from another endpoint |
| Accepted validated daily record | Canonical measurements with financial hash and provenance; source finality unverified |
| Current-date or changing record | Operationally provisional/unverified; no fabricated finality timestamp |
| Older unreviewed record | Source-unverified history, irrespective of age |
| Reconciliation-confirmed | A recorded acceptance decision; source finality still unverified |
| operator_finalized | Local operator confirmation of one exact financial hash under the policy below |
| Historical correction | New valid financial state and revision; previous evidence retained and local confirmation reset |

## Operator policy v1

This conservative local policy is an operational decision, **not** a fact about
TSETMC publication guarantees. The workflow is one date at a time; the collector
never invokes it automatically or bulk-finalizes history.

Confirmation requires an explicit actor/reason/review UUID, instrument/date and
expected current financial hash. It also requires:

1. The trading date is before the current Tehran calendar date.
2. Explicit operator-supplied session-completion instant on that trading date,
   with evidence/provenance. No closing hour is inferred.
3. Two distinct retained successful daily observations, independently parsed with
   the existing parser, both matching that exact financial hash and instrument.
4. The first receipt is after the supplied session completion, and the second is
   at least the configured grace later (minimum one hour, an operational choice).
5. Both receipts are in the past, raw SHA-256 checks succeed, and no daily quarantine
   remains open for the date.

A repeated review UUID with identical content is idempotent. Another instrument's
observations or a changed financial hash are rejected. A separate explicit revoke
review resets local confirmation without changing measurements. Later accepted
financial corrections create ordinary revisions and reset finalization to
source_unverified, retaining the old hash-bound review. Individually valid source
conflicts stay quarantined and require review; confirmation is not permission
to choose one arbitrarily. An operator may revoke an earlier confirmation when
new evidence makes its continued use inappropriate.

Default ChartData export still selects only operator_finalized records. Explicit
`accepted-unverified` export remains available and unchanged. No real pilot record
was confirmed or revoked during Milestone 3A; all 4,662 records remain unverified.
The workflow and late-correction behavior were tested with synthetic observations.

The live experiment observed current-day data from the dated endpoint while two
20-observation lists still ended on the prior date. The dated data was retained
as inspection-only evidence, not automatically promoted or finalized. First
publication time, full `/0` list behavior at that instant, and post-session correction
stability remain pending. See [source behavior](tsetmc-source-behavior.md).
