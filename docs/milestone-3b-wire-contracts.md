# Proposed wire contract: tsetmc.v1

**PROPOSED, not implemented by 1.1.0rc1.** The normative structural definition is
[schema.json](contracts/milestone3b/schema.json), JSON Schema draft 2020-12.
All object properties are required unless explicitly nullable; unknown properties
are rejected. Cross-field rules below are additionally mandatory. The
[example manifest](contracts/milestone3b/examples-manifest.json) identifies complete
synthetic requests/receipts and SHA256 of their exact UTF-8 files. None contains a
real instrument's financial observations or a usable credential.

## Routes and versioning

Same INGEST factory/product, new subrouter:

| Method/path | Schema and behavior |
|---|---|
| POST /api/ingest/v1/tsetmc/daily | Batch, stream=tsetmc_daily, 1..100 DailyRecord/RevisionRecord; HTTP 200 Receipt after atomic commit |
| POST /api/ingest/v1/tsetmc/current | Batch, stream=tsetmc_current, exactly one CurrentRecord |
| POST /api/ingest/v1/tsetmc/coverage | Batch, stream=tsetmc_coverage, exactly one CoverageRecord containing 1..100 date states |
| POST /api/ingest/v1/tsetmc/status | Batch, stream=tsetmc_status, exactly one StatusRecord |
| POST /api/ingest/v1/tsetmc/reconcile | ReconcileRequest -> ReconcileResponse, bounded read-only current-owner comparison |
| GET /api/ingest/v1/receipts/{batch_id} | Existing producer-only path, returns original committed receipt; 404 is absence at that check, not proof an in-flight request failed |
| POST /api/ingest/v1/session, /session/renew, /session/recover | Existing paths/semantics; proposed shared grant/recovery allowlists additionally admit four tsetmc_* names |

protocol_version is strict JSON integer 1. New requests/receipts additionally
require contract_version="tsetmc.v1". This names an additive v1 extension; it
does not alter legacy candle/quote payloads. The old four-stream Batch decoder is
not used for these routes. Unknown contract versions fail 422, never downgrade
to a minute candle or tick. Breaking future fields require a new contract version;
clients do not ignore new authoritative fields under the same version.

Every ingestion request uses verified HTTPS and independent producer Bearer auth.
Uploads require Content-Type: application/json and exactly one X-Payload-SHA256
lowercase hex header, computed over the **exact transmitted bytes**, including
whitespace/newline. No compression, redirects, duplicate JSON keys or NaN/Infinity.
Hard body limit remains min(configured limit,2 MiB). Staging targets 512 KiB and
splits before the hard cap without changing a record identity. Recovery/reconcile
body limit is 256 KiB. Existing database-backed per-producer request budgets,
Origin denial, no-store errors and total request timeout remain active.

## Scalar rules

| Type | Exact wire representation |
|---|---|
| UUID | Canonical UUID string; producer/session/batch/epoch/mapping/observation identities are distinct |
| ins_code | Original decimal-digit string, 1..20 digits, no float/integer conversion or symbol normalization |
| source_position, state_version, financial_revision, local IDs | Canonical positive decimal strings, max int64 9223372036854775807; no leading zeros |
| Financial prices/volume/value | Nullable nonnegative canonical plain decimal strings, max 128 characters; no insignificant fractional trailing zeros, exponent, plus sign, numeric JSON or float conversion |
| trade_count | Nullable nonnegative integral decimal string, max 128 digits; source NUMERIC can exceed int64, frontend conversion may then fail |
| Session/ownership generation | Strict positive JSON integer <=int64; booleans are not integers |
| Gregorian trading/source date | YYYY-MM-DD; real calendar validation required |
| Actual instant | UTC RFC3339 ending Z, seconds and at most six fractional digits; no naive datetime |
| source_time | Nullable HH:MM:SS exchange-local wall clock, valid 00:00:00..23:59:59; interpreted only with source_date and Asia/Tehran rules |
| Hash | Lowercase 64-character SHA256 hex |
| Missing measurement | Explicit null, never 0 or omitted property |

Values larger than the negotiated wire bound stay exact locally and cause an
explicit outbound validation/capacity error; neither truncation nor rounding is
allowed. Native source precision is not limited by the frontend float64 contract.
Diagnostic counts are bounded nonnegative JSON integers, not financial measurements.

Original dEven/hEven/lastHEven/finalLastDate are nullable bounded strings under
source_fields. Invalid/unusable original clocks can be preserved there while the
parsed source_date/time/instant remain null. No chart label or HTTP receipt fills
an unknown source clock. Source date/clock/UTC instant must agree when all known;
ambiguous historical timezone conversion leaves source_reported_at null.

## Batch and identity

Batch fields: protocol_version, contract_version, producer_id, session_id,
session_generation, source_epoch, batch_id, instrument_id, ownership_generation,
stream, records. Exactly one instrument/epoch/stream per batch; every observation's
identity must match the top-level instrument and provisioned mapping. Provider is
tsetmc, provider_symbol=ins_code, canonical_symbol=TSETMC:<ins_code>, and the mapping
UUID follows the company's existing canonical-symbol UUID5 function. External
source_instrument_id is nullable TEXT (e.g. IRO1FOLD0001 for the verified pilot),
not the company UUID. Registry changes are administrative, not upload side effects.

Record fields: observation_id, source_position, kind, event_type, observation.
observation_id=UUID5(source_epoch, stream+":"+source_position) is allocated/persisted
once. All records in one batch have unique IDs/positions. Positions are increasing
in staged daily/coverage batches; the receiver still validates each state independently
against its instrument-scoped barriers. Identities survive retries, process restart,
and replacement session envelopes. A collection run UUID is not an outbound event ID.

## Daily state and revision evidence

DailyState contains the six identity fields, trading_date, measurements, units, delivery_status,
financial_revision, state_version, financial_hash, source_fields, source, acceptance,
upstream_finality, local_finalization, publication_state, reconciliation, review and
revision_evidence. Measurements has exactly nine keys:

| Wire field | Source / unit profile |
|---|---|
| previous_close | priceYesterday, IRR/share |
| opening_price | priceFirst, IRR/share |
| last_traded_price | pDrCotVal, IRR/share |
| high / low | priceMax / priceMin, IRR/share |
| official_close | pClosing, IRR/share; may be outside executed range |
| trade_count | zTotTran, integral trades |
| traded_volume | qTotTran5J, source share quantity under the proposed equity profile |
| traded_value | qTotCap, total IRR under that profile |

Units explicitly records profile=tsetmc_equity_irr_shares_v1, price_currency=IRR,
value_currency=IRR, volume_unit=share, confidence and nullable evidence_ref. This is
the proposed common-equity interpretation, **not newly verified upstream evidence**.
M1 left unit/adjustment details open. Preserve confidence=unverified until an
authorized instrument-profile review establishes them; real transfer/display
activation must review that evidence. Never divide by 10 for Tomans, multiply by
a lot size, apply corporate-action adjustments or derive totals from UI abbreviations.

acceptance is observed or reconciled. upstream_finality is always unverified in
this version. local_finalization is source_unverified or operator_finalized.
publication_state is provisional or unverified_history, neither a completeness
claim. Reconciliation contains status (not_checked/agrees/accepted_repair/
unresolved_conflict), nullable local_decision_id and open_quarantine_count. An
unresolved candidate's own financial values must not enter this accepted-state record.

SourceRef contains local_observation_id, raw_sha256, relative source endpoint and
nullable genuine received_at. It links to privately retained evidence; raw body is
not uploaded. Review is null or a sanitized review ID/action/policy/hash/time,
evidence ID list and policy-evidence digest. actor/reason text is not exposed.
operator_finalized requires action=confirm for the same financial hash; revoke
requires source_unverified. Corrections reset confirmation and retain old history.

RevisionEvidence contains local_revision_id, financial_revision>=2, old/new
financial hashes and all nine old/new measurements, old/new SourceRefs and original
discovered_at. DailyRecord event_type is daily.accepted, daily.corrected,
daily.reconciled, daily.review_confirmed, daily.review_revoked, daily.quality_changed,
daily.seed or daily.resnapshot. A correction requires matching revision_evidence.
Nonfinancial transitions keep financial_revision/hash and increment state_version.
Raw-only receipt/flag changes do not create financial events.

RevisionRecord kind=daily_revision/event_type=daily.revision_seed carries identity,
trading_date, seed_id and RevisionEvidence. It imports genuine retained audit history
without changing canonical values or claiming an unobserved historical finalization.
An existing identical revision is recorded_no_change; conflicting evidence is 409.

## Current, coverage and status

CurrentState contains identity, local_snapshot_id, observation_semantics=polled_snapshot,
new_trade_claimed=false, measurements/units/delivery_status, state_version/financial_hash, source_fields/
source, nullable source_date/time/reported_at, nullable instrument_state/title,
accepted_decision, financial_change and nullable correction_reason_sha256.
Accepted decisions are initial_observation, newer_session, newer_source_clock,
same_state_more_precise_position, explicit_same_time_correction. Other local decisions
must not become a current upload, except an already accepted latest pointer whose
original decision is repeated_state: that may be copied only by current.seed or
current.resnapshot with financial_change=false. Ordinary current.updated must not
publish receipt-only repeated state. Explicit same-time correction requires its genuine
nonempty reason digest. State version equals that stream's allocated source_position.

Known older source dates/times cannot replace company latest even with higher
transport version. Unknown different financial state cannot displace a known head.
Initial unknown state is allowed only when no conflicting accepted head exists.
Newer clock with equal values is position progress, not a new trade. Equal source
position and values at a newer HTTP receipt belongs in status, not a financial event.
Current parsed source/receipt clocks more than five seconds ahead of company now
are rejected for review without altering them. Historical delayed receipts are valid.

financial_change preserves the source-local decision relative to its previous
accepted snapshot. It does not describe the company's possibly older head after
coalescing. The receiver independently compares its durable financial hash and nine
measurements to classify the committed public change. For example, source A -> B
changes prices, then B at a later clock has financial_change=false; delivering only
the later B must still update a company head holding A. Do not treat that flag as
an instruction to suppress a genuine company state change.

Coverage has identity, captured_at, inclusive from_date/through_date,
range_scope=observed_dates_only, archive_completeness=unproven,
missing_calendar_dates=unknown and coverage_rows. Rows contain date, state,
nullable financial_hash/local_finalization and upstream_finality=unverified.
States: observed, reconciled, confirmed_no_trade, quarantined, unknown. Unique
dates must lie within the declared range; omission changes nothing. A quarantined
date without accepted canonical state has null financial_hash. Lossless pages have
their own source positions; a later unrelated page cannot supersede an unsent one.

Status contains identity, actual captured_at/expires_at (0<TTL<=120 seconds),
process_state, source_availability, nullable last_successful_http_at,
last_database_commit_at, accepted_source_at, last_financial_change_at, session,
latest_failure_category and diagnostic counts. Session has expectation/confidence,
nullable provenance digest and valid_until. Never extend expiry on upload/retry.
Expired valid status can commit as recorded_no_change evidence without becoming
current health. No financial event is generated by a routine unchanged heartbeat.

## Hashes: three distinct meanings

Daily/current delivery_status is explicitly unknown in tsetmc.v1. The owner grant
must permit unknown; otherwise reject source_status_not_authorized. Fresh HTTP,
instrument permission, old historical dates or local confirmation do not prove
realtime delivery or an end-of-day finality guarantee. Existing TradingView
allowed_statuses behavior remains unchanged.

1. **financial_hash:** exactly current TSETMC serialization.financial_state/
   canonical_hash. Daily includes ins_code, trading_date and nine values; current
   includes ins_code, nine values and instrument_state/title. Count becomes an
   integer for this hash; other nonnull measurements use canonical decimal strings
   without insignificant trailing zeros. Zero is "0". Sort keys, ensure_ascii=true,
   compact separators, UTF-8, no newline. Do not include transport/finality fields.
2. **record_sha256:** SHA256 over compact sorted-key UTF-8 JSON (ensure_ascii=false)
   of exactly {kind,event_type,observation}, with the negotiated canonical financial
   strings. IDs/positions are separately checked against the immutable ledger.
3. **payload_sha256:** SHA256 of exact staged/transmitted batch bytes. Whitespace,
   key order or session changes alter it. Never regenerate it from parsed JSON.

state_sha256 in reconciliation is the same UTF-8 canonical algorithm applied to
the complete approved observation object alone. It therefore detects a finality,
acceptance, provenance or quality difference at an unchanged financial hash.
Canonicalize numeric financial strings before assigning an observation identity;
do not normalize or mutate an already staged observation on retry.
For example 112.0 is serialized as "112" before staging, while 112.125 remains
"112.125". This removes representation-only scale, never financial precision;
the original numeric lexeme remains in private source evidence.

## Durable receipt and all-or-nothing rejection

Receipt fields and nullable fields are exact in schema.json. It echoes identity,
epoch, batch/stream/instrument/generation and byte hash; state=committed;
destination_id identifies the existing company's durable destination identity.
server_ingested_at is the transaction's recorded time, not a source event or a
precise PostgreSQL commit timestamp. event_cursor is the last new committed TSETMC
journal cursor or null if no journal event was added. The HTTP response returns
only after data/ledger/events/receipt commit together.

Every requested observation appears exactly once in receipt.records with its
ID/position/record hash, outcome, nullable stored_state_version/financial_hash and
canonical_updated. Counts for applied/recorded_no_change/superseded/duplicate sum
to the record count. An original receipt is immutable; lookup/replay returns it
unchanged. A replacement batch carrying already imported observations can produce
duplicate outcomes. canonical_updated denotes a daily/current head mutation;
coverage/status may apply with that flag false. No receipt is a grant to accept
rejected source observations.

One invalid record rejects the entire batch with no financial/ledger/receipt/event
commit. Errors on new routes have exactly error:{code,retryable,record_indexes};
indexes are zero-based diagnostics and contain no input values. Shared session/
receipt routes retain their existing error:{code,retryable} shape.

| HTTP | Codes/policy |
|---|---|
| 400 | https_required, invalid_content_length, payload_hash_required, payload_hash_mismatch; fix configuration/bytes, no credential-bearing redirect |
| 401/403 | authentication_required, producer_not_authorized, source_not_authorized, browser_access_denied; stop/fence, no token guessing |
| 404 | receipt_not_found; investigate in-flight/session race before replacement envelope |
| 409 | batch_payload_conflict, observation_payload_conflict, source_version_conflict, source_identity_conflict, producer_session_fenced, source_epoch_conflict, current_source_regression, recovery_ownership_changed, recovery_obsolete, recovery_payload_conflict; retain evidence and recover only the explicitly recoverable session case |
| 413/415 | payload_too_large, record_limit_exceeded, unsupported_content_encoding, json_required; split only before staging, or stage replacement after definitive rejection with original record identities |
| 422 | invalid_batch, stream_mismatch, invalid_reconciliation, financial_hash_mismatch, invalid_finalization, collector_clock_ahead, source_clock_ahead; fix/review, never round or invent data |
| 429/503 | rate_limited, ingestion_busy, database_unavailable; retryable=true, honor Retry-After; preserve bytes and probe receipt after uncertain completion |
| 500 or network timeout | Receipt may be uncertain. Retain bytes, probe safely; repeated internal errors stop/alert rather than assuming rollback |

## Session expiry, immutable retries and reconciliation

Use the existing complete expected grant manifest and recovery_id mechanism,
extended to new stream names in both Python and SQL. Renewal cannot resurrect an
expired session. A recovery request's exact logical bytes/ID survive lost replies.
Revocation/changed ownership/epoch never becomes an automatic new session discovery.

If a staged upload has an uncertain result, first query its receipt with the
current producer credential. If expired, recover the unchanged session using the
durable manifest; producer locking fences the old generation. Then query the old
receipt again. Only after that old generation can no longer commit and no receipt
exists may a **new batch ID** envelope the exact same record IDs/positions/content
under the new session. Keep old bytes/replacement linkage. Never mutate the bytes
of the original batch ID. These semantics are inherited from the verified company
worker/recovery design; the TSETMC worker remains independent and unimplemented.

ReconcileRequest uses the active session, mapping/ins_code, epoch and ownership
generation. mode=keys queries 1..100 stream/date keys (date required for daily,
null for current/status; coverage queries one date). mode=daily_manifest supplies
inclusive date bounds, source_fence H, nullable after_date and limit<=100. Use the
latter only after the source's lossless daily ACK prefix reaches H.

Company daily_states reconstructs the latest full state per date with position<=H,
including any later-delivered superseded state, and returns ascending dates.
ReconcileResponse echoes binding/destination, checked time/fence, rows, next date,
has_more and page_sha256=SHA256(canonical(rows)). Each row includes state/financial
version/hash, full state digest, finality and revision count/digest/completeness.
Revision digest hashes the ascending, deduplicated RevisionEvidence array. A false
found flag requires nullable state fields; missing history is not replaced with a
zero hash. Page boundaries are exclusive after_date, inclusive upper trading date.

The source compares ordered complete pages, not just counts/earliest/latest dates,
and checks for extra as well as missing dates and revision evidence at H. Newer
source changes form a later fence; no claim of complete exchange coverage follows.
If the required historical state/identity evidence has been archived beyond query
support, return 409 reconciliation_history_unavailable; do not claim parity from
current rows alone. A reconciliation response is read-only and never repairs,
transfers ownership, resets an epoch or promotes a quarantined candidate.

## Concrete synthetic illustration

The complete [daily request](contracts/milestone3b/examples/daily.request.json)
preserves this invented measurement object:

```json
{"previous_close":"100","opening_price":"104","last_traded_price":"108","high":"110","low":"100","official_close":"112","trade_count":"7","traded_volume":"400","traded_value":"43000"}
```

Official close deliberately exceeds the high. The confirmation/revocation examples
keep its financial hash and increment public state versions. The correction
example changes official close to "113", increments financial revision and resets
confirmation. The [current request](contracts/milestone3b/examples/current.request.json)
separately uses last trade "109" and official close "111", with genuine-in-the-toy-
scenario source/receipt separation. All identities/measurements/provenance hashes
are synthetic; they are not API captures or proof of upstream publication behavior.
