# Proposed company persistence and authorization

**PROPOSED, not applied.** Extend the existing dedicated company market-data
database with company_tsetmc schema and shared ingestion policy extensions. The
unrelated company application database stays untouched. This is the same FastAPI
codebase/image in existing READ and INGEST roles, not a new backend product.

## Reused control plane and necessary changes

Reuse public.ingest_producers, ingest_source_owners, ingest_batches,
ingest_observations, ingest_request_budgets, ingest_session_recoveries and
ingest_destination_state. Keep existing producer authentication, key revocation,
session expiry, producer-first locking, owner generation fencing and durable
receipts. Four tsetmc_* stream names require additive CHECK allowlist expansion
in the ownership/batch/observation tables. Existing four names retain their meaning.

The shared session admission returns the producer's authorized streams only. Add a
GrantStream union for session/recovery models; **do not widen the existing Batch
decoder** into accepting TSETMC observations on legacy routes. 0009's
ingest_recover_session SQL also hardcodes stream names: new 0011 must replace that
function with an equivalently fenced allowlist extension, not edit 0009. Test its
exact old four-stream behavior and old recovery receipts. Separate TSETMC producers
must not be granted legacy streams, nor TradingView producers TSETMC streams.
New daily/current records explicitly carry delivery_status=unknown; the grant
must permit unknown. Neither old historical dates nor a successful poll qualifies
realtime delivery. This does not change existing TradingView allowed-status checks.

Keep the shared admin-only registry in public.instruments/provider_instruments.
Canonical symbol TSETMC:<ins_code> uses existing UUID5(NAMESPACE_URL,
`marketdata:instrument:` + canonical_symbol); mapping provider=tsetmc,
provider_symbol=the exact original code. Persian symbol/company are display fields,
never identity keys. Add TSETMC-specific typed registry/DTO values equity and
common_stock, preserving legacy domain/wire enum sets; no fake CFD,
crypto or futures classification. Existing legacy discovery/prices/history/coverage
queries and registry loading must exclude TSETMC **before** old Instrument
deserialization, preserving their source universe, enum sets and OpenAPI models;
the new provider router opts into it explicitly. Ingestion never provisions registry.

## Proposed company_tsetmc objects

All financial amounts use unconstrained PostgreSQL NUMERIC, counts additionally
integral/nonnegative; wire limits may reject overlong values but never round them.
Dates are DATE; actual instants TIMESTAMPTZ; original source fields TEXT. No daily
timestamp column is treated as an observed midnight trade.

| Table | Keys and responsibilities |
|---|---|
| instrument_links | PK(provider,ins_code), provider constrained to tsetmc in this provider schema; UNIQUE(instrument_id,provider), composite FK to shared provider mapping; source_instrument_id, display/units profile and approval evidence |
| daily_records | PK(instrument_id,provider,trading_date); nine nullable NUMERIC values; current epoch/generation/source_position; financial_revision/hash, state_version, acceptance, upstream_finality, local_finalization, publication_state, reconciliation/review/provenance JSON |
| daily_states | Immutable PK(instrument_id,provider,source_epoch,trading_date,state_version); unique(producer_id,source_epoch,observation_id); full approved daily state plus source_position/import receipt link, became_canonical and nullable published_event_id; supports exact finality history and as-of reconciliation |
| daily_revisions | PK(instrument_id,provider,source_epoch,trading_date,financial_revision), financial_revision>=2; exact old/new measurements and hashes, original source references/discovered_at, import ledger link; seeded evidence and incremental correction must agree |
| current_latest | PK(instrument_id,provider); accepted full snapshot, clocks/state/decision, NUMERIC measurements, epoch/generation/source_position/hash; no tick-history claim |
| daily_coverage | PK(instrument_id,provider,trading_date); known source state, source epoch/generation/position, reported capture time and quality; absent date=unknown |
| source_status | PK(instrument_id,provider); source epoch/generation/position, captured/expires, process/HTTP/session/financial freshness inputs; no expiry extension during delivery |
| event_clock | Singleton TSETMC namespace journal epoch/head/floor; transactional counter held through commit, independent of legacy marketdata_event_clock |
| events | BIGINT journal ID PK, provider/instrument/date where applicable, event kind, committed approved typed state/quality payload, recorded_at and imported observation link; no raw bodies |

Recommended indexes: daily_records(provider,ins_code via instrument_links,date) is
served by binding lookup plus its PK; add (provider,trading_date,instrument_id) for
bounded cross-instrument date pages only if required. daily_states has
(instrument_id,provider,source_epoch,source_position,trading_date) and a date/state
descending index. Revisions index instrument/date/revision. Events index
(instrument_id,id). Shared ingest_observations gets a provider/instrument/stream/
epoch/position lookup and unique scoped position constraint for TSETMC records
after duplicate/conflict validation. Do not impose that new uniqueness blindly on
legacy data whose historical contract did not require it.

Root ingest_observations already retains immutable payload/outcome and references
the receipt with a deferred FK. Expand its stream allowlist; preserve existing
outcomes applied, recorded_no_change, superseded. An exact duplicate returns duplicate
in a new receipt without mutating the original observation. No rejected record is
stored as an accepted daily state. Persistent rejection diagnostics are separate
safe worker logs/quarantine, not fabricated ingestion success.

## One destination transaction

The proposed TSETMC writer follows DestinationWriter.commit's transaction boundary:
verify authenticated producer/key, live session, explicit instrument/stream epoch
and ownership_generation; lock producer then sorted owner rows/record identities;
verify complete registry binding and profile; decode/validate/recompute financial
and record hashes; apply every record or roll back all; write immutable ledger,
new TSETMC events and receipt; recheck the lease; commit with synchronous_commit=on;
only then return HTTP 200. It must not call the legacy _apply candle/tick branches.

For daily canonical state, order by (authorized ownership_generation, source_epoch
binding, state_version) per date. Epoch UUIDs have **no lexical temporal order**.
Within one epoch, a higher source_position with a lower/equal incompatible
state_version is a conflict, not a correction. Equal state_version must match its
entire approved state digest, not just financial_hash. Older, valid full states may
be retained as superseded history without replacing the head; revision evidence
still imports idempotently. Same revision but a different financial_hash is a 409.
For a correction, revision_evidence must prove its old/new hashes; gaps in retained
revision history are exposed as incomplete, never invented. daily.revision_seed
imports audit evidence only and cannot move canonical values/finality.

A new owner/epoch can establish a reviewed baseline only after explicit admin
handover and reconciliation. It does not automatically overwrite a newer known
source session or silently reset daily history. Original epoch state/revisions stay
retained. Imported latest snapshots obey [source choose_latest](../src/tsetmc_marketdata/storage/ordering.py)
plus monotonic transport version checks. A higher local delivery position alone
does not authorize an older source session. Ambiguous changes fail closed; explicit
same-time corrections require a genuine accepted local correction decision and
its reason digest. Receipt timestamps never fabricate source advancement.

CurrentState.financial_change describes the source's immediately preceding local
accepted state, not the company's previous delivered state. Coalescing can skip
that predecessor. Therefore the company recomputes financial/measurement changes
against its own durable head after ordering validation: a changed imported hash
can produce current.updated even when the retained local flag is false. Equal
company financial state with a newer source position produces position progress
only; seed/resnapshot retain their explicit event kinds. Never suppress a company
change solely because the source flag says false. A same-clock conflicting
seed/resnapshot without retained, accepted correction evidence fails closed; a
higher delivery position is insufficient repair authority.

Daily constraints mirror source executed-range rules, including no-trade/missing
value exceptions. **No constraint requires official_close inside [low,high].**
All accepted values remain unadjusted; no corporate-action rescaling is introduced.

## Finality, units, coverage and privacy

Store upstream_finality=unverified separately from local_finalization. Proposed v1
does not even admit a source_finalized value. Operator confirmation requires the
hash-bound sanitized review summary, not a boolean inferred by the company. A
correction resets local confirmation; revocation can change state_version without
changing financial_revision. UI defaults to locally confirmed selection and must
explicitly opt into accepted-unverified; both disclose upstream uncertainty.

Proposed equity units are IRR/share prices, total IRR value, source share quantity
and trade count. Existing qualification did not establish all unit/corporate-action
details. The instrument profile therefore carries unverified/verified confidence
and evidence reference; actual activation requires separately approved unit evidence.
No Toman division, lot conversion, float serialization or inferred missing zero.

Coverage describes reported dates only. confirmed_no_trade is source-supplied zero
count+volume+value, not a verified exchange closure. Open conflicts may flag a
canonical date as disputed while retaining its last accepted values. No coverage
range, upper date or successful import establishes a complete exchange archive.

Private source raw bodies, unreviewed free text and credentials are not transferred.
Raw SHA references prove linkage to trusted source evidence, not independent company
revalidation of untransferred bodies. Existing company authentication is a trust
boundary; rights to ingest/display/redistribute must be approved separately.

## Additive migration and role plan

New **0011**, down_revision=0010, creates namespace/tables/constraints/indexes,
expands only the required stream allowlists, and replaces the recovery allowlist
function without weakening fencing or PUBLIC revocation. No old migration or
frozen schema artifact changes. No source epoch, real instrument, producer, grant
or secret is seeded by migration. Source 0004 is a different migration lineage and
must never be applied to this database.

READ role retains existing privileges and gets USAGE company_tsetmc plus SELECT
on approved market/quality/journal views, never producer secrets or ingestion
administration. Its default_transaction_read_only remains on. INGEST retains its
restricted existing privileges and gets SELECT/INSERT on immutable TSETMC states,
revisions/events; SELECT/INSERT/UPDATE on canonical/latest/coverage/status; narrowly
scoped event-pruning rights; SELECT/UPDATE on its journal clock. It has no registry,
producer/owner policy writes, history UPDATE/DELETE, DDL or superuser privileges.
Only migration/admin roles manage registry, profiles, policy and controlled cleanup.
Explicit schema-qualified routines use fixed search_path and revoked PUBLIC EXECUTE.

Extend startup permission checks for new objects; do not remove old safety checks
to make a broader owner role pass. Company writer has both provider schemas because
it is one trusted INGEST product; producer authorization fences requests. If a
later security requirement demands separate provider writer roles, use separate
INGEST processes from the same image with restricted roles, not a second product.

Store.connect currently rejects heads other than 0010. The new release must
explicitly validate 0011 for both roles. An old frozen 1.1.0rc1 process will not
restart against 0011; do not promise in-place binary rollback. First qualify a
new-release TSETMC-disabled mode that serves the old TradingView contracts on
0011, and use that as application rollback. Database downgrade is disposable-test
only. Real rollback restores a separately verified backup under explicit site
authorization. See [rollout](milestone-3b-implementation-sequence.md).

Daily states/revisions are durable financial audit data. Journal retention is
separate and bounded (proposed 100,000 events / maximum 7 days, whichever removes
older events first); floor/cursor expires explicitly. Keep receipts and imported
observation identities at least 90 days and while any retry/reference remains;
afterward retain permanent identity/hash tombstones or an approved durable archive.
Missing archived evidence makes old replay fail closed, never a new application of
the same identity. TSETMC retention cannot prune TradingView history or its journal.
