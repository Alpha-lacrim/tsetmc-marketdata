# Milestone 3B-D compatibility matrix

**PROPOSED extensions, not implemented.** Baselines and release comparison are in
[the design](milestone-3b-design.md). S means TSETMC source, D company destination.
Destination migration proposals belong in new 0011; source proposals in new 0004.
Each row's test obligation is required before activating that feature.

| Feature | Existing TSETMC semantics | Actual company implementation | Required additive change, owner and risk/test |
|---|---|---|---|
| Stable identity | TEXT ins_code; verified external instrument ID | domain.Instrument.id UUID5 from canonical_symbol; provider_instruments maps provider_symbol | D: canonical TSETMC:<ins_code>, matching UUID5 and provider_symbol=ins_code; company_tsetmc.instrument_links binds TEXT to UUID. S: persist approved binding. Test two synthetic identities and cross-provider UUID collisions |
| Equity type | Pilot is a listed equity, not an FX/CFD/tick feed | AssetClass lacks equity; InstrumentType lacks common_stock | D adds TSETMC registry/DTO models with equity/common_stock; legacy wire enums stay closed. Admin-only bindings and legacy registry/query filtering prevent old enum consumers from seeing the new provider. Test old instrument payload snapshots |
| Historical interval | Genuine Gregorian daily records | MarketCandle interval Literal[1m]; READ HistoricalInterval includes 1d **aggregated from minute data** | New daily ingestion/READ models; no 24h fake native 1m candle. Test daily source route cannot call minute aggregation |
| OHLC | Open priceFirst; close pClosing; close can lie outside high/low | MarketCandle.completed requires close inside range, exactly one-minute bucket, completed status | D dedicated NUMERIC daily table/validation; retain executed open/last bounds, no close-range constraint. Test out-of-range official close |
| Trade count | zTotTran integral NUMERIC, nullable | api_v1.chart_data deliberately inserts f=0; observations counts base bars, not trades | S exact integral strings; D NUMERIC count and int64 boundary check; test genuine count and overflow |
| Volume/value | qTotTran5J quantity; qTotCap monetary value; nullable | One volume plus verified base/tick unit; h=0 | Separate volume/value with unit profile, no volume-as-value or lot/Toman scaling. Unit qualification gate remains open. Test g/h independently |
| Last/official close | Separate pDrCotVal and pClosing | Tick has last/bid/ask; no typed official_close | Dedicated current snapshot model/table, not metadata stuffing into Tick; test values differ |
| Current observations | Polled snapshots, not individual trade events | QuoteRecord identity must equal tick_id; quote_snapshots.materialize handles independently timed partial fields | Reuse durable coalescing/CAS ideas only; new tsetmc_current route and state validator. Never fabricate tick IDs/trades. Test repeated HTTP yields status progress without price event |
| Source instants | Nullable source date/time, original clock fields; Tehran interpretation | Tick event_timestamp may be null; snapshot primary/per-field clocks have separate rules | New source fields/optional instant, local choose_latest rules mirrored. Test unknown, older session, same-clock correction, future clock rejection |
| Receipt instants | Actual source HTTP receipt; not trading time | Quote received_timestamp can participate in existing quote ordering | Keep separate source.received_at, server_ingested_at; no receipt-only promotion of a different TSETMC state. Test delayed delivery |
| Finalization | source_unverified or operator_finalized for an exact hash | Candle model accepts completed native candle, no TSETMC review policy | Separate upstream_finality/local_finalization/publication_state/review summary; no automatic finalization of 4,662 rows. Test confirm/revoke/correction reset |
| Financial revisions | daily_revisions stores exact old/new states and hashes | candle_revisions concerns minute OHLCV; ingest_candle_heads orders source positions | D daily_states + daily_revisions; S public state_version distinct from existing financial_revision. Test finality-only transition and out-of-order revision evidence |
| Source conflicts | Individually valid disagreements remain quarantined | Ingestion validates and commits or rejects a complete batch | Publish accepted canonical state plus disputed quality; never send candidate as accepted. Test audit cannot arbitrate conflict |
| Coverage | Per observed date; absent dates unknown | CoverageObservation.Window enforces minute alignment/partitions; Store applies time multiranges | New per-date coverage pages, no synthesized holiday gaps; test omitted date remains unknown, pagination cannot delete coverage |
| Session uncertainty | EXPECTED/NOT_EXPECTED/UNKNOWN with dated evidence | CapturedHealth/SymbolHealth is the existing provider health shape | New typed TSETMC status preserving evidence expiry and separate process/HTTP/freshness. No invented ProviderHealth conversion |
| Producer auth | No company credentials currently installed | ingest_auth.Credentials; IngestGuard authenticates and enforces HTTPS, Origin denial, DB admission budgets | Reuse same guard/token-file mechanism, new independent producer/key; no credential creation now. Test revocation and token/site separation |
| Instrument ownership | Dedicated PostgreSQL advisory owner per instrument | ingest_source_owners and ingest_lock_owner fence provider/instrument/stream | New stream CHECK values, explicit generation in new envelope, same producer-first lock discipline; S separate worker owner. Test mixed grants and admin handover |
| Epochs | No outbound epoch yet | Source capture uses durable source_epoch; destination owner policy and ledger bind it | S durable per-instrument epoch plus external continuity anchor; D existing controls reused. New epoch is administrator-reviewed, never a retry trick |
| Position order | Observation IDs are not a commit-ordered outbound cursor | source_capture.clock locks a transactional counter; events.append_events locks journal counter | S per-instrument/stream transactional counters; do not copy source's global singleton key. Test paused earlier transaction versus later transaction |
| Session recovery | Not implemented for TSETMC | RecoveryStream uses closed Stream literal; 0009 SQL also hardcodes four streams; lease belongs to producer | D new GrantStream union and additive replacement of recovery function allowlist in 0011; keep old four unchanged. S one durable producer-session coordinator, instrument-scoped data/ACKs. Test lost recovery response, competing coordinators and changed grants |
| Idempotency | Collection run UUID/checkpoint is local job identity | ingest_batches PK(producer,batch), ingest_observations PK(producer,epoch,observation); byte hash mismatch=409 | Reuse physical receipt/ledger with expanded stream CHECKs and new strict decoder. New observation UUID is durable outbound identity, not HTTP run UUID |
| Immutable retries | Existing local jobs replay committed runs without HTTP | SyncState stages bytes; SyncWorker verifies receipts, re-envelopes uncommitted observations after recovery | New independent worker uses same four durable phases, never edits bytes under old batch ID. Test lost ACK/rotation/late original commit |
| Event journal | No outbound/company journal currently | 0006 kinds CHECK only price_update/candle_completed/candle_corrected; render_event assumes Tick or MarketCandle | Separate company_tsetmc journal/clock and renderer in same READ process. No new kind in old journal. Test TradingView WS schemas and retention unchanged |
| REST | CLI/pure adapter only | api_v1 price/candle/coverage models and minute aggregations | New /api/v1/tsetmc router, shared bearer/BFF access; old routes retain contracts. Test 14 columns, nullable measurements and selection metadata |
| ChartData | a–h exact mapping; optional i:null; UTC-date label | Same eight keys, but f/h placeholders and aggregated intervals | New TSETMC adapter call uses genuine f/g/h; bare response plus consistent metadata endpoint/headers. Test numeric JSON and empty eight arrays |
| WS | No company stream yet | MarketHub and /api/v1/ws/marketdata read committed legacy journal | New namespace WS/changes endpoints, same app and auth/origin rules, separate cursors; client reconnect/dedup required |
| Retention/replay | Raw protected by canonical/revision/quarantine/review links; snapshots 7/90 days | Bounded company journal, durable receipts/ledger; existing worker has logical budgets | S retain unacked immutable daily events, staged bytes and anchors; D protect TSETMC states/receipts independently. No cross-provider pruning; test slow offline recovery and retention floor |
| Limits/errors | Bounded HTTP retries; no source evasion | 2 MiB body cap, 500 records general, 50 coverage/status, strict JSON; safe errors and Retry-After | New conservative 100 daily / 1 current / 1 coverage / 1 status per batch, same hard HTTP guard; no partial record ACK. Test bytes/count separately |
| Release/schema | Applied source 0001–0003 frozen | Store.connect rejects destination version other than 0010 | New release explicitly supports 0011 and regression-tested TV behavior. Old 1.1 binary is not a post-migration rollback target; no historical migration edits |

## Important primary code references

All company links below are pinned to the inspected public commit:

- [Strict wire models and limits](https://github.com/Alpha-lacrim/tradingview-marketdata/blob/e114a25be8679451f6064ad1fb03c0ef6a8aaefe/src/marketdata/replication_models.py),
  [minute candle invariants](https://github.com/Alpha-lacrim/tradingview-marketdata/blob/e114a25be8679451f6064ad1fb03c0ef6a8aaefe/src/marketdata/candles.py#L28),
  [registry enums/UUID identity](https://github.com/Alpha-lacrim/tradingview-marketdata/blob/e114a25be8679451f6064ad1fb03c0ef6a8aaefe/src/marketdata/domain.py#L38).
- [DestinationWriter.commit/_commit/_validate_source](https://github.com/Alpha-lacrim/tradingview-marketdata/blob/e114a25be8679451f6064ad1fb03c0ef6a8aaefe/src/marketdata/replication.py#L108),
  [HTTP guard, routes and errors](https://github.com/Alpha-lacrim/tradingview-marketdata/blob/e114a25be8679451f6064ad1fb03c0ef6a8aaefe/src/marketdata/ingest_api.py#L103),
  [authentication/session admission](https://github.com/Alpha-lacrim/tradingview-marketdata/blob/e114a25be8679451f6064ad1fb03c0ef6a8aaefe/src/marketdata/ingest_auth.py).
- [0007 ownership and ledger constraints](https://github.com/Alpha-lacrim/tradingview-marketdata/blob/e114a25be8679451f6064ad1fb03c0ef6a8aaefe/migrations/versions/0007_destination_ingestion.py),
  [0009 recovery SQL](https://github.com/Alpha-lacrim/tradingview-marketdata/blob/e114a25be8679451f6064ad1fb03c0ef6a8aaefe/migrations/versions/0009_session_recovery.py#L71),
  [0010 snapshot heads/destination ID](https://github.com/Alpha-lacrim/tradingview-marketdata/blob/e114a25be8679451f6064ad1fb03c0ef6a8aaefe/migrations/versions/0010_quote_snapshots.py).
- [SyncState.acknowledge](https://github.com/Alpha-lacrim/tradingview-marketdata/blob/e114a25be8679451f6064ad1fb03c0ef6a8aaefe/src/marketdata/sync_state.py#L157),
  [SourceCapture.acknowledge_quote](https://github.com/Alpha-lacrim/tradingview-marketdata/blob/e114a25be8679451f6064ad1fb03c0ef6a8aaefe/src/marketdata/source_capture.py#L460),
  [worker receipt/recovery tests](https://github.com/Alpha-lacrim/tradingview-marketdata/blob/e114a25be8679451f6064ad1fb03c0ef6a8aaefe/tests/test_sync_worker.py).
- [ChartData zeros](https://github.com/Alpha-lacrim/tradingview-marketdata/blob/e114a25be8679451f6064ad1fb03c0ef6a8aaefe/src/marketdata/api_v1.py#L180),
  [journal commit ordering](https://github.com/Alpha-lacrim/tradingview-marketdata/blob/e114a25be8679451f6064ad1fb03c0ef6a8aaefe/src/marketdata/events.py#L45),
  [legacy event renderer](https://github.com/Alpha-lacrim/tradingview-marketdata/blob/e114a25be8679451f6064ad1fb03c0ef6a8aaefe/src/marketdata/market_stream.py#L46).

OpenAPI snapshots are incomplete evidence: dynamically registered uploads are
manually decoded, while custom OpenAPI injection primarily types recovery and
reconciliation. A READ interval named 1d does not establish native daily ingestion.
The frozen source/migrations and behavioral tests take precedence over those
inferences. No existing company test was executed or claimed to pass in this task.
