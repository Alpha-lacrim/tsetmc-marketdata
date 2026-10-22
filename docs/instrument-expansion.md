# Broad native share collection

The owner authorized expansion on 22 October 2026. `tsetmc-simple` now discovers
primary ordinary shares by default. `--ins-code CODE` (repeatable) selects explicit
IDs instead. Legacy command pilot restrictions and original pilot databases remain.

Discovery reads https://cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch through the
existing paced client. The bounded capture returned 3,462 rows, of which 745 matched
`yVal` 300/303/309/313 and primary IDs `IRO[1357][A-Z0-9]{4}0001`. These are explicit,
observed selection rules, not a guarantee of a complete official instrument master.
Secondary trading lines, rights, options, funds and other products are excluded.
No display-symbol deduplication merges distinct IDs. Duplicate/invalid/zero insCodes
fail discovery visibly. Instrument metadata is checked independently before collection.

Only IDs are used from bulk market watch. The observed response has `dEven=0`, and
long-form price fields contain zero placeholders while short fields contain prices.
It cannot safely supply source-dated current observations without further semantics.
Current prices still come from `GetClosingPriceInfo/{id}`, full histories from
`GetClosingPriceDailyList/{id}/0`, with original UTC/source dates and exact Decimal.
The current homepage JS asset retrieval returned HTML, so no claim of verified
JavaScript classification semantics is made.

## Live checks

Four read-only samples (one per selected family), selected by reported market-watch
value, supplied metadata, full history and current responses without parser errors:

| insCode | Symbol | Primary ID | Accepted daily rows |
|---|---|---|---|
| 46348559193224090 | فولاد | IRO1FOLD0001 | 4665 |
| 30199365830132996 | سيمكات | IRO3SIMC0001 | 425 |
| 41379697187196382 | وشهر | IRO7BSHP0001 | 3318 |
| 60369091709615715 | مهرمام | IRO5MOMS0001 | 521 |

These checks fetched no other individual candidates and made no company DB writes.
Counts reflect each response, not a completeness claim; upstream history can change.
Private captures stay under ignored `.local/expansion-20261022/`. The original Foolad
qualification and its captures remain separate. No all-market uptime claim is made.

## Scheduling and failure isolation

One paced HTTP client serves independent history and latest loops. Each loop visits
instruments sequentially; initial metadata is cached in memory and shared. Default
pacing is one request start per second. A 745-share latest sweep therefore takes at
least about 12.5 minutes, usually longer with history/metadata requests or failures.
The 15-second poll setting is a pause AFTER a sweep, not per-share freshness. For
faster updates restrict the watchlist rather than claiming broad real-time access.

Full history refresh is per instrument every 86,400 seconds. Completion is saved
atomically only after all exact pending batches have acknowledged receipts. Partial
uploads resume before new collection; that instrument's full history may replay,
which is safe. Completed histories skip redownload until due after a restart.
`--once` ignores completion timing and attempts a full pass, reporting source failures.
An intentional company DB reset needs a new state directory because checkpoints cannot
identify a replacement database at the same API URL. Preserve old pending files.

Bad source records skip that instrument for that cycle with a log; others continue.
Access denials and permanent upload failures stop. No bad rows are silently discarded
from a history labeled complete. Source names/company/ISIN are sent as metadata;
insCode remains the primary source key. Discovery runs on restart; no silent runtime
universe rotations or external services are introduced. Daily corrections and stored
history are preserved, but broader traffic requires monitoring company disk growth.

See [native installation](native-install.md) for commands and freshness details.


Discovery recovery: an empty/no-match market-watch response now logs the number
of rows received and retries after 60, 120, 240, then 300 seconds (capped). It does
not start an empty universe or loosen identity/product filters. Malformed schemas,
invalid identities and access denials still fail visibly. `--once` fails immediately
on unsuccessful discovery. The reported no-share response was not captured; a later
bounded probe returned 3,462 rows and 745 accepted share IDs. Its cause is unconfirmed.
