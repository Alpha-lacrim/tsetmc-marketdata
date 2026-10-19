# Proposed shared READ API, dashboard and event journal

**PROPOSED; all paths below are new TSETMC routes in the same company READ
application.** Existing TradingView routes and WebSocket models remain unchanged.
Use exact wire DailyState/CurrentState/Status/identity types from
[the contract](milestone-3b-wire-contracts.md), not minute candles or Tick objects.

## READ route choice

Option A (widen existing provider-aware endpoints) appears small but their enums,
interval aggregation, freshness, price fallback and candle/WS rendering assume
minute-candle or tick semantics. It risks silent f/h zeros and false finality.
Recommend Option B: explicit /api/v1/tsetmc routes in the **same** factory/image,
sharing company bearer/gateway access and database pools. New TSETMC registry/DTO
models expose equity/common_stock; legacy enum sets stay closed and their registry
loaders/source queries exclude the new provider before old-model deserialization. There
is no second company-facing FastAPI product and no collector in the READ process.

| Proposed GET path | Parameters and exact response contract |
|---|---|
| /api/v1/tsetmc/instruments | optional ins_code, after (opaque registry cursor), limit 1..100. {contract_version,items:[InstrumentItem],next_after:null/string} |
| /api/v1/tsetmc/instruments/{ins_code}/current | {contract_version,as_of_at,as_of_cursor,availability:available/unavailable,current:CurrentState/null,current_context:ImportedContext/null,status:StatusView} |
| /api/v1/tsetmc/instruments/{ins_code}/daily | from_date/through_date inclusive, selection=finalized (default) or accepted-unverified, after_date exclusive, optional as_of cursor, limit 1..500. {contract_version,selection,as_of_cursor,items:[DailyItem],next_after_date:null/date,metadata:HistoryMetadata} |
| /api/v1/tsetmc/instruments/{ins_code}/chartdata | Same date/selection/as_of/page filters, legacy_sample=false and allow_partial=false by default. Bare a–h ChartData, i:null only if requested; metadata headers described below |
| /api/v1/tsetmc/chartdata/metadata | Required signed snapshot_token from the ChartData response; authenticated matching immutable HistoryMetadata |
| /api/v1/tsetmc/instruments/{ins_code}/revisions | Authorized audit readers only; date required, optional source_epoch (default canonical day's epoch), after_revision string/null, limit 1..100. {contract_version,instrument_id,ins_code,source_epoch,items:[RevisionEvidence],revision_history_complete,next_after_revision} |
| /api/v1/tsetmc/instruments/{ins_code}/coverage | Inclusive date bounds, after_date exclusive, limit 1..500. {contract_version,items:[CoverageItem],next_after_date,archive_completeness:unproven,unreported_dates:unknown,as_of_at} |
| /api/v1/tsetmc/instruments/{ins_code}/status | {contract_version,as_of_at,status:StatusView} |
| /api/v1/tsetmc/marketdata/changes | after/until opaque namespace cursors, limit 1..1000. {contract_version,items:[Event],cursor,until,has_more} |

Every contract_version above is tsetmc.v1. Dates are Gregorian YYYY-MM-DD, never
Jalali input interpreted implicitly. Unknown instrument returns 404; a known
instrument with no selected history yields an empty successful page/chart. Invalid
range/cursor is 422, expired/wrong journal epoch or unsupported historical snapshot
is 409 resync_required; DB outage is 503, not a successful empty dataset.

InstrumentItem contains the six wire identity fields plus symbol/company_name,
asset_class=equity, instrument_type=common_stock, exchange (approved registry value),
units, active, supported_intervals=[1d], upstream_finality=unverified. Persian names
are display strings. No real additional instrument is enabled by this design.

ImportedContext={source_epoch,ownership_generation,source_position,observation_id},
using the validated batch/record identity, not a fabricated source clock. Every
daily/current/event item carries it so state versions from different epochs are
never compared as one counter. CoverageItem={context:ImportedContext,
coverage:CoverageRow,captured_at}. Revision pages are explicitly scoped to the
echoed source_epoch; older epochs require that explicit filter and audit permission.

DailyItem={context:ImportedContext,state:DailyState,changes:{last_trade_absolute,last_trade_percent,
official_close_absolute,official_close_percent}}. All four derived values are
nullable signed decimal strings. Use the existing source price_change algorithm:
exact subtraction, percentage=(price-previous)/previous*100, local Decimal precision
at least 50 significant digits (the source's scale-aware formula increases it when
needed), no percent when previous=0/missing. Do not store computed percentages as
authoritative source measurements or turn null into zero.

HistoryMetadata has exactly: selection, allow_partial, finalized_meaning (local_operator_confirmation_only),
upstream_finality (unverified), archive_completeness (unproven), instrument_id,
ins_code, from_date, through_date, as_of_cursor, selected_rows, excluded_unverified,
excluded_missing_ohlc, disputed_selected_rows, placeholder_count, placeholder_volume,
placeholder_value, units, next_after_date and nullable chart_sha256. Counts are
nonnegative integers; chart_sha256 is set only for ChartData metadata. It describes
the requested range at its as_of snapshot, not the whole archive. Page counts and
exclusions must distinguish total selected range from the emitted page in their
documented scope: selected_rows is emitted page length; all excluded/disputed/
placeholder counts concern that emitted page or rejected rows encountered while
forming it. Range totals are deliberately not implied. A page scans at most 500
accepted date states at the snapshot; next_after_date advances past the last scanned
date, even if selection excludes every row, so empty selected pages cannot stall
pagination. Reaching the end of that scan is not a coverage-completeness claim.

## Selection and consistent ChartData metadata

selection=finalized means the source's local operator_finalized hash is selected,
**not** source-confirmed finality. selection=accepted-unverified includes accepted
observed/reconciled rows of either local finalization state, and must be explicit.
No source fetch, review or repair occurs in a READ request. The 4,662 qualified
source-unverified records would not appear under the default finalized selection.

The daily/history page is read in one read-only REPEATABLE READ transaction with
the namespace journal cursor. Subsequent pages may supply that as_of cursor;
company daily_states stores became_canonical/published_event_id so a later correction
does not mutate the earlier snapshot. Superseded imported states are retained but
are not retroactively public canonical states. Retention-expired cursors require a
fresh REST snapshot. Do not combine pages from different snapshots silently.

ChartData remains a **bare object** suitable for the existing Go struct. Return
X-TSETMC-Selection, X-TSETMC-Upstream-Finality: unverified,
X-TSETMC-Chart-SHA256 and X-TSETMC-Snapshot-Token headers. The token signs the exact
HistoryMetadata, request identity/filters and expiry (10 minutes), with an independent
READ signing secret shared by READ replicas; maximum token size 8 KiB. It is not
an authentication token. The metadata endpoint verifies signature, expiry and the
ordinary READ authorization, then returns those immutable metadata fields. No
per-process cache or separately timed query can silently mismatch body and metadata.
Gateway/BFF must forward these headers to permitted clients. The JSON chart digest
is over the exact emitted response bytes, before any HTTP content encoding.

## Exact Go mapping and 14-column table

| ChartData key | Source |
|---|---|
| a | 00:00:00 UTC Unix seconds on Gregorian trading_date, a date label only |
| b | priceFirst / opening_price |
| c | pClosing / official_close |
| d / e | priceMax / high; priceMin / low |
| f | zTotTran / genuine integral trade_count |
| g | qTotTran5J / genuine traded_volume |
| h | qTotCap / genuine traded_value |

All arrays have equal length and strict chronological order. Empty results give
{"a":[],"b":[],"c":[],"d":[],"e":[],"f":[],"g":[],"h":[]}.
legacy_sample=true alone appends i:null without inventing a meaning. Unknown
activity stays null internally and becomes a counted zero placeholder only here.
Missing OHLC fails by default with 422 chartdata_missing_ohlc, matching the pure
adapter's strict policy. Only explicit allow_partial=true filters such rows with
metadata counts; the complete daily-record route still retains their nulls.
Nonrepresentable finite float64 or int64 count overflow fails the page (422
chartdata_unrepresentable), never truncates values. Source/storage remain exact.

The synthetic daily example maps through the existing adapter to:

```json
{"a":[1774051200],"b":[104.0],"c":[112.0],"d":[110.0],"e":[100.0],"f":[7],"g":[400.0],"h":[43000.0]}
```

The a value labels 2026-03-21 at UTC midnight. c> d is intentional; frontend
chart/table testing must tolerate official-close semantics without widening the
genuine executed range. Some candle widgets may need explicit display treatment;
do not silently replace c with last trade or rewrite high/low.

The table's 14 columns remain: Gregorian/Jalali display date; trade count; volume;
value; previous close; opening price; last trade; last absolute change; last percent
change; high; low; official close; close absolute change; close percent change.
DailyItem provides all of them. Preserve the existing
[mapping](field-mapping.md) and [UTC timestamp policy](frontend-contract.md).
Current last trade remains independent of the latest completed/confirmed daily row;
the current endpoint does not fall back to yesterday's close to satisfy availability.

## StatusView: three separate axes

StatusView contains source (nullable latest unexpired Status), process_state,
source_availability, data_freshness, source_age_seconds/http_age_seconds (nullable),
status_age_seconds, status_expired, and session_expectation/confidence. Ages derive
from company now and genuine accepted source/receipt/capture instants; delivery
does not refresh them. When status expires, process/session become unknown until
new evidence; prices may remain available but old. Expired status also makes
current source availability unknown, rather than treating its last HTTP result
as a live health assertion. Session valid_until expires independently, even while
the status TTL remains valid. Source freshness categories
mirror M3A: recent_source_observation, unexpectedly_stale under EXPECTED,
unchanged_updates_not_expected under NOT_EXPECTED, stale_session_unknown,
unknown_source_time or source_clock_ahead. Unavailable HTTP is distinct from stale
financial data. A running process does not establish healthy market updates.

## Namespace event journal and WebSocket

Use the proposed company_tsetmc event_clock/events in the same database transaction
as canonical state/receipt. The transactional singleton counter serializes only
the journal tail, matching the demonstrated existing algorithm. Ingestion can
insert uncommitted rows but READ workers cannot publish them until commit. No
after-commit in-memory callback is the sole durable event source. Do not widen
legacy marketdata_events kinds or call its Tick/MarketCandle renderer for TSETMC.

New WSS path: /api/v1/tsetmc/ws/marketdata. Reuse existing READ bearer and the
documented BFF option (its site deployment is unverified), plus explicit allowed
Origin checking; never put permanent producer/service secrets
in browser JavaScript or URL queries. A new strict command has action=subscribe/
unsubscribe/snapshot/ping/disconnect, ins_codes list (max100), nullable request_id
(max64) and nullable after cursor (subscribe/snapshot only). Require codes for
subscribe/unsubscribe, forbid them for ping/disconnect. Existing WS commands are
unchanged on their original path.

Event has version=1, contract_version=tsetmc.v1, type, event_id, cursor,
instrument_id, ins_code, context:ImportedContext, recorded_at, server_timestamp,
persisted=true and data.
event_id is namespace journal epoch UUID + ":" + positive decimal ID. cursor is
opaque base64url encoding `tsetmc1:<journal_epoch>:<position>`, independent of
source epochs/positions and of the legacy journal. data is the approved full
DailyState, CurrentState, Coverage or Status according to type, plus a nullable
measurements_changed flag (only current events use boolean). No raw capture appears.

| Event type | Meaning |
|---|---|
| daily.accepted / daily.seed | A new accepted local daily state became company canonical; never named candle_completed |
| daily.corrected / daily.resnapshot | Corrected/restated canonical daily state with original financial revision/provenance |
| daily.reconciled / daily.quality_changed | Acceptance/disagreement/quality changed, possibly identical financial hash |
| daily.review_confirmed / daily.review_revoked | Local confirmation changed; upstream remains unverified |
| current.updated | Accepted state changed; measurements_changed compares the nine measurements, new_trade_claimed stays false |
| current.seed / current.resnapshot | Existing accepted pointer copied for initial enrollment/repair; no new trade; a repeated_state pointer may be seeded without claiming a source update |
| current.position_updated | Newer/more precise accepted source position with unchanged financial state; no financial price-change event |
| coverage.updated / status.updated | Relevant quality/session/process/availability transition, not every routine unchanged HTTP heartbeat |

The source financial hash also includes instrument-state labels; financial_change
therefore follows that existing state hash and does not by itself prove a price
changed. measurements_changed provides the separate comparison above. Daily
revision seeds and duplicate/superseded imports do not emit canonical financial events.
Both public change classification and measurements_changed compare with the prior
company head; the preserved financial_change flag compares with the prior local
source head. Coalescing can make those comparisons differ without any new-trade
claim. A local false flag must not suppress a company A-to-B update.

For snapshot, return version/contract_version/type=snapshot, request_id,
snapshot_cursor, items (current states/status), batch and final. subscription_ack,
heartbeat and error carry version/contract_version/server_timestamp plus their
request_id/cursor/error fields; no financial state is invented. Snapshot and cursor
come from one MVCC transaction. Client loads REST history at a cursor and replays
changes after it, deduplicating event_id and entity state_version. Reconnect can
repeat events; delivery is not exactly once. If disconnected beyond the retained
floor/wrong epoch, return resync_required and reload REST. Slow consumers have
bounded queues, a send deadline and close 1013; client capacity/origin/payload limits
are separately configurable without raising TradingView's existing limits.

Journal retention removes only an old contiguous prefix (proposed 100,000 events /
7-day maximum). It does not prune financial states/revisions or the legacy journal.
One TSETMC journal reader per READ worker is acceptable; it is a namespace component
of the same process, not another company service.
