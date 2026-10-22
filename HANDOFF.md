# Current state - native installation, 2026-10-22

The default is `tsetmc-simple`, documented in `docs/native-install.md`.
It reuses native TSETMC parsers and Foolad identity checks, sends daily history and
latest snapshots directly to the shared company API, and needs no source database.
History/current have independent durable pending files and one directory owner.
Receipts are verified before removing staged bytes; transport outages retry.
A failed one-shot provider fetch exits unsuccessfully instead of reporting success.

The company API lives in tradingview-marketdata: `marketdata-simple`, one new
PostgreSQL schema, `/api/chart`, latest, exact records and WebSockets. The chart
maps official close to c, volume to g and traded value to h; latest distinguishes
last trade from official close. Daily finality remains unverified. Only Foolad
is configured; no minute history or broader live coverage is claimed.

Validation: Ruff, formatting, strict mypy passed; pytest 263 passed / 119 skipped
(legacy PostgreSQL and opt-in live tests). Wheel build passed. Native regression
checks cover parser semantics, retry bytes, bad receipts, ownership and failure
reporting. Company integration tests and actual loopback HTTP smoke verified
TSETMC synthetic parser output through PostgreSQL/chart/latest/WebSocket delivery.
No genuine provider coverage or employer deployment is implied by those checks.

Ubuntu native instructions and a user systemd unit are supplied. Existing Windows
and Ubuntu unit CI remains automatic; legacy Docker PostgreSQL CI is manual.
Next: follow the linked company Ubuntu guide, set COMPANY_API_URL, start the
collector, and give the frontend team the shared API contract. No employer host
was available for deployment. Monitor pending files, freshness and database disk.

The original pilot, old database/outbox pipeline, migrations and frozen releases
are untouched. Native installation starts fresh; it does not import old databases.
Old README and handoff are archived in docs/history/; their deployment requirements
are historical. Existing workspace/checkpoint recovery remains in LOCAL_WORKSPACE.md.

## Recovery hardening

Native upload retries now show HTTP/transport causes, pending filenames, retry
delays and recovery. Backoff doubles from 30 to 300 seconds and honors longer
numeric or HTTP-date Retry-After. Malformed/non-object receipts and permanent
rejections retain the file and fail visibly. Shared helper matches company copy.
Staged uploads drain before source identity qualification; temporary network,
DNS, timeout and server errors during qualification retry at 60..300 seconds.
Invalid identities/access denials remain fatal. Source polling errors report
category and HTTP status; one-shot failures still exit unsuccessfully.

Ruff/format, strict mypy and full suite passed: 281 passed / 119 skipped.
New regressions cover HTTP-date backoff, exact replay bytes, malformed receipts,
permanent rejection, cancellation retention and startup identity recovery.
Company integration also verified native DB outage/recovery. No schema/pilot,
source permissions or live provider behavior changed; restart to load updates.
