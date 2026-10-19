# Exact company Go contract

M3A preserves this adapter and both selection modes. Its explicit single-date
[operator confirmation](daily-finalization-policy.md) can make a reviewed hash
eligible for finalized selection; the scheduler never confirms automatically.
No live pilot records were finalized during M3A.

Milestone 2 uses this unchanged adapter for stored records via
`export-db-chartdata`. The default selects explicitly finalized records only;
source finality remains unverified, so use `--selection accepted-unverified`
explicitly to export accepted source observations. See
[operations](collector-operations.md) for the selection report and placeholder counts.

```go
type ChartData struct {
    Time   []int64   `json:"a"`
    Open   []float64 `json:"b"`
    Close  []float64 `json:"c"`
    High   []float64 `json:"d"`
    Low    []float64 `json:"e"`
    Count  []int64   `json:"f"`
    Volume []float64 `json:"g"`
    Value  []float64 `json:"h"`
}
```

| JSON | Meaning | Daily source |
|---|---|---|
| a | Unix timestamp in seconds | UTC midnight label for Gregorian dEven |
| b | Open | priceFirst |
| c | Official close | pClosing |
| d | High | priceMax |
| e | Low | priceMin |
| f | Trade count | zTotTran |
| g | Traded volume | qTotTran5J |
| h | Traded value | qTotCap |

The adapter never uses pDrCotVal for c. All arrays have equal lengths; each index
represents one record of the same instrument. Dates are strictly increasing.
Direct adapter calls reject duplicate dates by default; `duplicates="identical"`
permits only identical financial duplicates. Conflicting dates never resolve by
input order. The history parser supplies already deduplicated, validated records.

Empty canonical output is `{"a":[],"b":[],"c":[],"d":[],"e":[],"f":[],"g":[],"h":[]}`.
`to_json(legacy_sample=True)` / CLI `--legacy-sample` appends `"i":null`.
`i` has no financial meaning and is absent from the Go structure.

Null count, volume and value become zero placeholders only here, because the Go
arrays are nonnullable. CLI export reports the number of placeholders for each
array. Genuine source zeros remain genuine zeros. Missing OHLC prevents export;
no price is guessed. Source-supplied rows with zero trading activity and zero
open/high/low are exported as supplied; consumers should use count/volume to
distinguish these from executed-trade sessions. No absent calendar date is added.

Numeric JSON is mandatory. f is validated as signed int64; source counts beyond
that limit fail export. b–e/g/h convert to finite float64 with known binary rounding;
overflow and nonzero underflow fail. Integers above 2^53 may lose precision in
JavaScript consumers even when the Go int64/JSON value is exact. Exact Decimal and
integer values remain in the source model/raw body. The 14-column source model is
a separate precise interface; diagnostic decimal strings are not ChartData.

## Timestamp convention

Daily **a = 00:00:00 UTC on the canonical Gregorian trading date**, encoded as Unix
seconds. It is a date label, not a claim that an exchange event happened at midnight.
The frontend should format this label as a date (or convert its date to Jalali),
without assigning it a market-open or collector-receipt meaning.

For 2026-08-04: 1785801600 is 00:00 UTC; 1785814200 is 03:30 UTC. The latter cannot
be assumed to mean Tehran midnight (which is the previous UTC day at 20:30 under
the 2026 +03:30 offset). Existing frontend examples must be reconciled with this
explicit convention before integration. No compatibility heuristic reproduces
mixed timestamp conventions. This timezone interpretation is covered by tests.

Source-reported current dEven/hEven is interpreted using IANA Asia/Tehran and
converted to aware UTC, with historical DST handling. Ambiguous/nonexistent source
clocks retain the original fields but produce no invented source instant. Daily
hEven is preserved only as provenance. HTTP receipt timestamps are independent UTC
instants. Offline JSON without a receipt manifest has `received_at=null`.

Clearly labeled synthetic outputs are saved in
[synthetic-chartdata.json](../examples/synthetic-chartdata.json) and
[synthetic-chartdata-legacy.json](../examples/synthetic-chartdata-legacy.json).
The original genuine latest-day example and partial historical export remain
private locally; see [publication audit](publication-audit.md).
