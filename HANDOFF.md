# Current state - native share expansion, 2026-10-22

Default tsetmc-simple sends daily history and current observations directly to one
company FastAPI/PostgreSQL. No source DB or Docker required. HTTP/open access and
optional upload token are authorized. Read docs/native-install.md and the companion
company docs/native-dashboard.md. Original Foolad pilot, old DB/outbox pipeline,
migrations, archives and frozen releases are unchanged. Legacy CLI pilot fences stay.

## Current instrument scope

Owner authorized broad native collection. Default startup discovers primary ordinary
shares from ClosingPrice/GetMarketWatch; --ins-code (repeatable) restricts to selected
IDs. Latest capture: 3,462 rows, 745 eligible primary-share candidates using yVal
300/303/309/313 and IRO[1357][A-Z0-9]{4}0001. Other products and secondary lines are
excluded, not merged. IDs are validated/deduplicated and metadata is qualified per
instrument. Original special Foolad identity checks still hold. Restart rediscovers
new instruments; there is no silent runtime universe rotation.

Bulk market-watch prices are not ingestion input: date and long-form price fields
were zero placeholders. Existing GetClosingPriceInfo and full daily endpoints supply
time-aware prices and exact Decimal history. Four live sample families passed
metadata/full-history/current parsing (Foolad, Simcat, Vashahr, Mehrmam); no claims of
full 745 qualification. Evidence and counts: docs/instrument-expansion.md. Raw bodies
are private under .local/expansion-20261022/. Prior source qualification is separately
recorded in docs/validation-review-2026-10-22.md and its ignored captures.

## Scheduling and durability

One shared paced source client, independent history/latest loops, sequential visits
per stream. One request start/second default: a 745-share latest sweep takes at least
about12.5 minutes, more with metadata/history/failures. --poll-seconds is the pause
AFTER a sweep. Use a small explicit watchlist for better freshness. Do not claim
real-time/source finality, native minutes or invent clocks from receipt times.

Full daily history refreshes every86400 seconds per instrument by default. The
history-completed.json map is atomically fsynced only after all upload receipts and
survives restarts. --once forces a full pass. Partial histories may replay safely;
exact pending batches drain before new collection. Checkpoint binds to API URL, not
DB identity. After intentional company DB replacement archive old state and select
a new directory; do not discard pending files. Bad records skip that instrument and
log the error, permitting other instruments to continue. Access denials and permanent
upload errors stop. Metadata names/company/ISIN are attached, IDs remain source keys.

Upload helper is identical to company copy: exact retry bytes, receipt validation,
30..300s retry with longer Retry-After respected, visible diagnostic causes. Source
parser retains wrong-identity/conflict quarantine, exact decimals, stale clocks and
zero activity. Future source clocks >5min ahead of receipt are rejected. Official
close need not be inside executed price range. No source correctness gate was relaxed.

## Verification and next operation

306 source tests passed /119 skipped (legacy PG/live opt-in); Ruff, format, mypy,
wheel/sdist passed. New tests exercise discovery exclusions and invalid IDs,
independent two-instrument uploads, failure isolation and acknowledged history resume.
Companion full suite565 passed /365 skipped with native disposable PostgreSQL,
including >1000 source directory paging and display names. No live company writes.
Company new native100 TradingView list passed read-only bar/quote probes for100 feeds.

Commit/checkpoint both repos, rebuild ZIPs with new configs/docs, restart processes
with retained state directories. No DB reset/migration. No employer host was supplied
or deployment performed. Monitor full-history fill, errors, pending files, source
freshness and company disk growth. Read LOCAL_WORKSPACE.md/docs/workspace.md before
workspace cleanup; preserve archived original data.
