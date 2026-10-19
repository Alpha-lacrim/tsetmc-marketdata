# TSETMC source behavior qualification

This aggregate engineering assessment does not redistribute a market-data
capture. Exact responses, financial values, source clocks, hashes, per-request
traces and the detailed live report remain in ignored `.local/milestone3a/`.
Public tests use synthetic observations. Neither those tests nor this short
experiment establishes complete archive coverage or unattended readiness.

## Bounded observation on 2026-10-19

The explicitly activated experiment ran 11:04:13.985647–11:05:21.783396 UTC
(14:34:13.985647–14:35:21.783396 Asia/Tehran). Session expectation was UNKNOWN;
no verified evidence established an active session or completed session.

Eight logical requests, eight wire attempts, zero retries and eight HTTP 200
responses: one metadata lookup, three current observations, two recent-history
lists with limit 20, and two dated inspections. The service itself stopped after
six requests/five committed jobs; two separately budgeted, inspection-only dated
requests completed the experiment. Nothing was left running.

| Question | Observation | Limit of inference |
|---|---|---|
| Current request cadence | Receipt gaps 32.515703 and 31.616880 seconds | Completion-relative scheduling includes HTTP/commit time |
| Financial publication cadence | Three identical financial states, no source-clock advancement | No active-market cadence measured; no new trade inferred |
| Source age | About 124–125 minutes behind receipt | Source age is not network or first-publication latency |
| HTTP latency | 0.184502–1.428310 seconds across eight calls | Small sample, one access environment |
| Latest-state decisions | Three repeated-state observations, latest pointer preserved | Successful receipts do not supersede financial-state ordering |
| Recent daily list | Both responses contained 20 valid records and excluded the current date | Only the positive-limit endpoint was checked; `/0` was not requested |
| Dated previous-day result | Valid, agreed exactly with the recent list | Agreement at one instant does not prove finality |
| Dated current-day result | Available despite absence from the recent list; all nine measurements agreed with current-price output | Publication time and the cause of the list/daily difference remain unknown |
| Clock field coverage | Current output supplied additional original clock fields absent from the dated result | Field names alone do not establish an event's meaning |

No current-day candle was added by the inspection. The 4,662 canonical daily
records, financial hashes, revisions and finalization states remained unchanged.
There were no financial revisions, quarantines or operator finalizations in the
persistent pilot database during this experiment.

## Evidence and unresolved questions

| Topic | Confidence and action |
|---|---|
| Last trade versus official close | Separate source measurements and established mappings preserved |
| Different list and dated publication | Observed in this window; do not infer first appearance, universal ordering or temporary omission |
| Clock advancing without a price change | Not observed; tested synthetically, not a live finding |
| Financial change at unchanged clock | Not observed here; explicit correction/ambiguity handling remains tested |
| Older-session current response | No transition observed here; existing source-position ordering remains |
| Delayed publication/provisional changes | Deterministic tests only in M3A; multi-window live study pending |
| Later historical correction | Prior discrepancy remains in [the M2 report](milestone-2-verification.md); M3A did not refetch the full archive |
| Missing history dates | Not a session calendar or proof of missing candles; no rows synthesized |
| `iClose`, `yClose`, `last` | Not qualified as finality signals; raw fields retained |
| Instrument state | Permission/state alone does not prove an active, closed or suspended session with known validity interval |
| Holidays, exceptional closure, pre-opening and extra phases | No complete authoritative calendar or instrument-specific mapping qualified; default UNKNOWN |

The [TSE official site](https://tse.ir/) could not be retrieved by the research
tool during this task. Searches of exchange/regulator sites did not produce a
usable, current, instrument-specific calendar rule. This access failure is not
evidence that no such documentation exists. Conflicting secondary schedule
descriptions were not adopted as rules. No fixed weekday/hour activation exists.

[IANA's Asia zone source](https://data.iana.org/time-zones/tzdb/asia) supports the
timezone interpretation; installed tzdata handles historical offsets as well as
modern Tehran time. [The client-maintainer example](https://github.com/5j9/tsetmc)
shows historical state/clock response structures, including possibly unusable
nested clocks. It is third-party evidence, not an upstream schema guarantee. No
third-party client code was copied.

## Next source experiment

A separately approved full-session window should declare date, session evidence,
request cap and 30–60 second interval before activation. Observe before/during/
after transitions, occasional dated/list reconciliation, and a later grace-period
recheck. Measure first visibility only when bracketed by actual observations.
Keep exact evidence private and stop at the declared boundary. Do not wait for a
future session or enable a supervisor automatically.

See [session policy](market-session-policy.md), [finalization policy](daily-finalization-policy.md)
and [verification](milestone-3a-verification.md).
