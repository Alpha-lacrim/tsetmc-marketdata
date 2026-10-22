# TSETMC behavior and validation review - 2026-10-22

## Bounded source observation

Only Foolad (insCode 46348559193224090) was queried, read-only. The initial
metadata/current/full-history/recent-history probes timed out with no retry.
After the owner disabled the VPN, all five checks below returned HTTP 200,
with one attempt each and one-second minimum pacing. This temporal association
does not by itself isolate the VPN's technical failure mechanism.

Successful probe started at 13:41:35 UTC (17:11:35 Asia/Tehran), 22 October 2026.
The ordinary project HTTP client was used, without proxy/identity rotation or
access-control workarounds. Genuine bodies, SHA256 hashes and receipt times stay
private under ignored `.local/validation-20261022/`; no database writes occurred.

| Official source path under https://cdn.tsetmc.com/api/ | Observation |
|---|---|
| Instrument/GetInstrumentInfo/46348559193224090 | Foolad identity verified |
| ClosingPrice/GetClosingPriceInfo/46348559193224090 | Current envelope is an object; top-level insCode is the string 0; nested instrument is null |
| ClosingPrice/GetClosingPriceDailyList/46348559193224090/0 | 4,666 accepted dates, 2007-03-11 through 2026-10-21; no parser errors |
| ClosingPrice/GetClosingPriceDailyList/46348559193224090/2 | Exactly matches the newest two records of the full list |
| ClosingPrice/GetClosingPriceDaily/46348559193224090/20261021 | Matches the latest list record on all normalized historical measurements |

The current source date remained 2026-10-21 with a source-reported Tehran clock
12:30:02. A successful request today is not evidence of a trade today. Last trade
and official close differed. The state code was preserved, not interpreted as
proof of an active session. `lastHEven` and `finalLastDate` were retained as raw
fields, not used to invent a more recent event time.

The full history contains 415 rows with both count and volume zero, and 285 rows
whose official close is outside a positive executed high/low range. All-null
measurement records were not observed. These findings reinforce the existing
policy: preserve zero-activity records and do not apply the last-trade OHLC range
rule to official close. No adjustment, price reconstruction or holiday inference
was performed. The boolean `last` field is not a price; pDrCotVal supplies last trade.

The homepage retrieval tool timed out before VPN removal; the successful API
checks above, not a visual browser inspection, are the basis of this report.
One observation window and endpoint agreement do not establish finality, complete
history, live-market cadence, a session calendar or continued access guarantees.
Prior list/dated discrepancies remain documented in api-research.md.

## Validation changes

- Placeholder identities and clocks accept only null, integer 0 or string "0".
  Python False and Decimal/float zero can no longer pass as source placeholders.
- Current nested instrument and instrumentState objects must have compatible
  identity when supplied. Non-object values and conflicting identities are rejected.
  Observed null/zero placeholders remain supported after endpoint qualification.
- Empty records with no observed measurements are rejected; explicit zero activity
  and legitimately missing individual optional fields remain supported.
- Current source timestamps more than five minutes ahead of received_at are
  rejected. This is a local integrity tolerance, not a claimed TSETMC guarantee.
  Keep system clocks synchronized. Old timestamps and corrections are preserved.
- The company native upload API now enforces nonnegative TSETMC prices, insCode
  length, nonempty measurements, open/last executed-range checks with zero-activity
  exemptions, and equality of daily close/official_close when both are provided.
  It deliberately does not constrain official close to the executed price range.
- The company boundary applies the same five-minute future event-time tolerance.
  Invalid batches return 422 atomically. No stored history was rewritten.
- Native quote metadata now exposes instrument state and explicitly labels
  dEven/hEven as the source-reported Tehran clock, not verified last-trade time.

Exact Decimal parsing, duplicate JSON-key rejection, conflicting-date quarantine,
wrong dated-endpoint rejection and UTC-aware receipt validation were already in
place and remain intact. Precision is not reduced to fit the dashboard.

## Evidence and checks

The captured 4,666 historical records plus one current observation were replayed
through the updated source parser, native adapter and company Batch validation:
all 4,667 accepted, with no HTTP upload or database modification. Existing private
2026-10-19 capture regressions also pass, including their known quarantined row.
Synthetic tests exercise bad placeholders/nested identities, empty data, future
clocks, negative prices, inconsistent daily closing fields, stale observations,
zero activity and out-of-range official closes. Frozen releases and original
pilot databases are untouched. Broader instruments and a full market session
remain outside this qualification.
