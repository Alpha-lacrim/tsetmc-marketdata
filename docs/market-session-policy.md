# Session expectations

The implementation does not ship a guessed Iranian market calendar. Reliable
exchange rules, holidays, exceptional closures, symbol suspensions, pre-opening,
continuous trading, additional sessions and publication hours remain unqualified
for automatic inference in this environment. Clock time or a weekday alone never
establishes a closed session. The default is UNKNOWN.

| Expectation | Meaning | Scheduling consequence |
|---|---|---|
| EXPECTED | Qualified or explicitly supplied dated evidence supports ordinary relevant market observations | Current collection is eligible; full audits defer |
| NOT_EXPECTED | Dated closure, suspension or session evidence establishes that live trading updates are not expected | Current polling pauses; closure-eligible history jobs may run |
| UNKNOWN | No applicable reliable evidence, expired evidence or conflicting equal-priority evidence | No implicit market activation; only explicitly approved observation/maintenance windows may run |

Session evidence includes string ins_code, aware start/end, expectation, provenance,
confidence (`operator`, `verified_rule`, `source_state`) and priority. Windows are
start-inclusive/end-exclusive. A higher-priority exceptional closure can override
a normal window. Equal-priority contradictions become UNKNOWN. Evidence for one
instrument never affects another. These are caller-supplied evidence classes, not
a claim that exchange rules or state-code mappings are already verified.

`OPERATOR_WINDOW` job eligibility explicitly permits source investigation during
UNKNOWN within the configured operating window and with recorded provenance. It
does not turn UNKNOWN into EXPECTED. It never overrides NOT_EXPECTED for current
prices, and never permits a full audit during an eligible current-price window.
Other job eligibility requires the matching EXPECTED/NOT_EXPECTED state.

The observed current-price state label `A / مجاز` expresses permission in the
captured response. It does not establish active trading, fresh state timestamps,
session completion or daily finality. The nested state timestamps observed here
are not sufficient for automatic session transitions. No state-code activation
mapping is enabled. Operators may supply independently verified state evidence
with a bounded validity interval and provenance once qualified.

All comparisons use aware instants; source exchange-local interpretation uses
Asia/Tehran. The [IANA Asia database](https://data.iana.org/time-zones/tzdb/asia)
retains Iran's historical daylight-saving rules, ending in 2022. Tests distinguish
modern +03:30 from historical summer +04:30 and retain ambiguous-clock rejection.
Daily date labels remain UTC midnight; Jalali conversion is presentation only.

On 2026-10-19 the official [Tehran Stock Exchange site](https://tse.ir/) timed out
through the research tool, and official-domain searches did not provide a usable,
instrument-specific session/holiday rule set. General secondary schedules were
not promoted to operational authority. A full active-session qualification and
verified current exchange notices are required before unattended activation.
