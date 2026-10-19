# Historical table: all 14 columns

The mappings were qualified during the original live pilot. The table below uses
**invented synthetic measurements** from `tests/fixtures/synthetic-history.json`,
not a redistributed source record. It proves transformation behavior when used in
deterministic tests; it does not prove prices, session existence or live API behavior.
Units are passed through without currency scaling or UI abbreviations.

| Column | Source / calculation | Synthetic sample |
|---|---|---:|
| Trading date / تاریخ | `dEven` → Gregorian date | 2026-03-21 |
| Trade count / تعداد معاملات | `zTotTran` → exact integer | 1234 |
| Traded volume / حجم معاملات | `qTotTran5J` | 7000000123.0 |
| Traded value / ارزش معاملات | `qTotCap` | 7154000125700.25 |
| Previous close / قیمت دیروز | `priceYesterday` | 1000.00 |
| Opening price / اولین قیمت | `priceFirst` | 1010.25 |
| Last traded price / آخرین قیمت | `pDrCotVal` | 1030.50 |
| Last-trade absolute change | `pDrCotVal - priceYesterday` | 30.50 |
| Last-trade percentage change | above / `priceYesterday * 100` | 3.05% |
| Highest price / بیشترین | `priceMax` | 1040.75 |
| Lowest price / کمترین | `priceMin` | 1005.00 |
| Official closing price / قیمت پایانی | `pClosing` | 1020.25 |
| Official-close absolute change | `pClosing - priceYesterday` | 20.25 |
| Official-close percentage change | above / `priceYesterday * 100` | 2.025% |

If previous close is absent, both changes are null. If it is zero, the absolute
change is still valid but percentage is null. No field is reconstructed from an
abbreviated screenshot or another financial measurement.

Additional raw fields: `insCode` is the string instrument identity; `hEven` is a
source local HHMMSS clock, not the daily candle timestamp. `last`, `iClose`, `yClose`
are booleans in the capture, and `id` is an integer (all zero in this history).
Their operational flag meanings are not established. **`last` is not a price.**
`priceChange` matches the last-trade delta in 4,348 of 4,661 list rows and the
official-close delta in only 1,044; it is not authoritative for our four calculated
columns. The current response has `priceChange=0` despite a nonzero price delta.
Every field remains in the raw payload; no speculative flag interpretation is used.

High must be at least low. Open/last must be within a positive executed-trade range
when trading activity is not explicitly zero. Official close has no such bound:
285 actual positive-trade rows violate it (e.g. 2024-10-26, min=max=3904,
official close=3891). This empirically rules out that validation constraint.
The exact exchange closing-price formula, historical base-volume effects and
corporate-action rules remain unqualified; no VWAP/base-volume formula is implemented.

The list row for 2025-07-29 has open=0 with positive activity and is quarantined.
The separately captured targeted endpoint reports open=2956. No silent replacement
is made. There are also 414 source-provided zero-count/zero-volume rows; their zeros
are preserved, not fabricated, and do not establish a market-wide session calendar.
