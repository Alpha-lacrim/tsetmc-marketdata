# Proposed implementation acceptance tests

**PLAN, not executed implementation tests.** All public fixtures must be invented,
with two synthetic identities, explicit provenance and no TSETMC network requirement.
Use independent actual PostgreSQL 16.1 source/destination disposable databases,
distinct runtime roles and a local verified-TLS gateway. Never point the suite at
existing TSETMC, TradingView or company databases. Preserve frozen migrations and
the exact old FastAPI release artifact. Tests below are mandatory stage gates.

| ID/group | Cases and required evidence |
|---|---|
| S01 outbox atomicity | Kill before/after canonical commit, correction, reconciliation, review and quarantine changes. Financial row/revision/outbox/clock are all-or-none; no after-commit-only event |
| S02 commit ordering | A locks clock and pauses; B same stream cannot allocate/commit later prefix until A completes. Roll back A and retry. Different synthetic instruments can progress independently. Demonstrate unsafe sequence counterexample separately |
| S03 quality versions | Confirm/revoke/reconcile/open-conflict change public state version at equal financial hash; raw-only recheck creates no financial revision/event |
| S04 current coalescing | N+1 replaces only unstaged durable head; in-flight N bytes unchanged; ACK N never clears N+1; unknown/older/rejected snapshots never become accepted through delivery |
| S05 isolation/fencing | Same schedule/stream names and dates for synthetic A/B; test composite FKs, epochs, clocks, outbox, owners, checkpoints, grants and receipts; one producer-session coordinator prevents conflicting per-instrument recovery IDs; actual backend loss blocks stale mutation |
| S06 seed/capacity | Consistent seed plus concurrent later correction, preserved historical revisions, bounded initial rows/bytes, no re-fetch/canonical edit; refusal rolls back atomically; separate coverage prefix never loses a page |
| T01 exact schema | All example bodies and receipts validate with format/cross-field checks; JSON numbers for financial values, exponent/NaN/duplicate keys/unknown fields/invalid times are rejected |
| T02 hashes | Exact source financial hash (daily and current state-title case), record hash and exact-byte payload hash; whitespace/session change alters batch hash but never retroactively changes an existing staged body |
| T03 auth/leases | HTTPS-only, invalid CA/hostname/redirect, browser Origin denial, independent tokens; producer mismatch, key revocation under lock, expiry/renewal, complete expected grant checks |
| T04 recovery races | Exact recovery replay, lost reply, obsolete recovery, competing IDs, 0009 old-stream regression plus all four TSETMC streams, handover during recovery, no old commit after completed generation fence |
| T05 receipts/retry | Timeout after commit, receipt 404 before old in-flight commit, duplicate batch, different bytes under same ID, replacement envelope after fenced absence, receipt tampering and record omission/extra records |
| T06 transport limits | Record and byte caps independently, 429/Retry-After, 503, 500/uncertain outcome, request/response deadlines, bounded jitter/backoff, no environment proxy or credential leakage; one bad row rolls back whole batch |
| T07 process restart | Actual child process death at stage/send/receipt/ACK/cleanup boundaries; immutable pending bytes survive, old worker cannot ACK after ownership loss |
| D01 precision/validation | NUMERIC exact large counts/decimals, null versus zero, official close outside range, executed open/last bounds and no-trade exceptions, no currency/lot conversion |
| D02 daily history | New/corrected day, reverse delivery, same-version conflict, older state superseded without loss of revision evidence, pre-enrollment revision seed, correction while initial archive uploads |
| D03 truthful finality | No automatic bulk finalization; confirm/revoke/correction reset, hash-bound review, disagreement quality without candidate promotion, source_finalized not admitted |
| D04 current ordering | Older date/clock; unknown clocks versus known different state; explicit same-time correction versus ambiguity; newer clock at equal values; receipt-only repeat; state labels separate from measurement changes; coalesced A->B->B delivers B to company A despite local financial_change=false; conflicting same-clock resnapshot cannot bypass correction evidence |
| D05 atomic journal | Kill after financial writes before journal/receipt and after commit; no precommit WS, duplicate/replaced batches create no extra financial events; independent namespace cursor and retention |
| D06 grants/migrations | Empty fresh source/0010 destination upgrades; populated source 0003 preservation; exact 0010->0011 registry/market/receipt/head preservation; restricted read/ingest/source-worker roles; interrupted DDL rollback; disposable downgrade/re-upgrade only |
| D07 reconciliation | Ordered complete manifest/root at H, source advances to H+1 during pages, extras/missing/quality/hash/revision mismatches, archived state unavailable, no count-only parity or silent repair |
| F01 14 columns/ChartData | Genuine f/g/h, c official close, last trade separate, all four derived changes, zero previous close, missing activity placeholders reported, int64/finite-float failure, equal arrays, sorting, empty a–h, optional i:null only |
| F02 selection/snapshots | Default finalized empty for unverified data; explicit accepted-unverified and metadata warning; consistent body/token/hash/selection across BFF/READ replicas; token expiry/tampering; corrections between pages respect as_of |
| F03 dates/sessions | UTC date-midnight labels, Tehran modern/historical offsets, Gregorian/Jalali year boundaries, UNKNOWN/closure/open stale categories, no invented holiday candles |
| F04 REST/WS | REST snapshot + journal replay converge, disconnect/duplicate replay/dedup, wrong epoch/floor resync, bounded slow-client queue 1013, Origin/bearer/size/client limits; no per-poll synthetic trade |
| P01 product isolation | One company codebase, separate READ/INGEST processes; READ starts without collector, INGEST cannot collect; source worker has no company PostgreSQL/upstream credentials; company collector source credentials absent |
| P02 TV regression | Run unchanged legacy ingest/session/quote/minute/coverage/REST/WS/ChartData suites and golden payloads at the new destination head; original provider/source universe and f/h behavior unchanged; no TSETMC event reaches legacy renderer |
| P03 operations | Separate source/destination lifecycles and restricted roles; WAN/DB failures, consistent backups and source/company restore anchors; no real producer activation; synthetic load proves agreed fairness budgets before any capacity claim |

Existing company tests to retain/reference include test_ingest_http.py (atomic
retry/lost ACK), test_session_recovery.py (ownership/revocation/races),
test_sync_worker.py (restart boundaries, coalescing, old ACK, byte caps, restore,
backlog fairness) and destination/migration/market-stream tests. They are references,
not evidence that the new contracts already pass. Source M1–3A tests remain intact.

## Execution/reporting requirements for implementation

Record exact source/destination commit IDs, image/database versions, migration
heads, role privileges and fixture hashes. Run source unit, transport, two-DB TLS,
company regression and frontend suites separately. Report passed/failed/skipped/
unexecuted by platform and SQL backend. Default CI stays offline; integration is
explicit opt-in using task-owned disposable resources. Real full-session source
qualification is a separate acceptance axis, not replaced by synthetic TLS tests.

Design-time checks performed in this task are recorded in
[the implementation sequence](milestone-3b-implementation-sequence.md). They
validate specification consistency, not outbox/worker/database behavior that does
not yet exist.
