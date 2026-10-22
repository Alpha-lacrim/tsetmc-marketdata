# Native collector installation (no Docker or source database)

This is the default path for new installations. The collector sends available daily
history and latest observations directly to the shared company FastAPI service.
It keeps a small durable retry file instead of a local PostgreSQL database.

First install the company API using the companion repository's
[Ubuntu installation guide](https://github.com/alpha-lacrim/tradingview-marketdata/blob/main/docs/native-install.md).
Only that server needs PostgreSQL. On this collector host:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv python install 3.12
mkdir -p "$HOME/marketdata"
cd "$HOME/marketdata"
git clone https://github.com/alpha-lacrim/tsetmc-marketdata.git
cd tsetmc-marketdata
uv sync --frozen --no-dev --python 3.12
export COMPANY_API_URL='http://SERVER:8000'
uv run --no-sync tsetmc-simple
```

The command verifies Foolad's identity, polls current data every 15 seconds and
refreshes available daily history hourly. The default insCode is
`46348559193224090`. This does not expand live coverage beyond the qualified pilot.
Use `--poll-seconds`, `--history-seconds`, `--state-dir` or `--once` as needed.

Keep `.local/simple-tsetmc/` across restarts. A pending upload is retried before
new observations for that stream; malformed/conflicting history is reported and
not silently uploaded as complete. Source parsers, decimals and original timestamps
are preserved. Last trade and official close remain distinct. History finality and
source units are not promoted to verified status by successful delivery.

HTTP is accepted, no token is required by default, and company DB credentials are
never needed here. If the API operator sets `SIMPLE_UPLOAD_TOKEN`, set the same
environment variable on this collector. Anyone who can reach an API with no token
can upload records. Browser reads remain open.

For automatic startup, use `deploy/native/tsetmc-collector.service` and the user
systemd instructions in the company guide. The unit keeps retry files under
`$HOME/.local/share/marketdata/tsetmc/`. Stop the foreground copy before starting it.
No service is installed automatically by running the Python command.

The frontend uses the company API:

```text
GET /api/chart?market=tsetmc&symbol=46348559193224090&interval=1d
GET /api/latest?market=tsetmc&symbol=46348559193224090
```

Chart output is the supplied Go contract: a=time, b=open, c=official close,
d=high, e=low, f=count, g=volume, h=traded value, i=null. Unknown activity is a
zero placeholder only in that response. Exact records and nulls remain stored.
TSETMC does not supply native minute history in this collector.

Existing PostgreSQL collection/outbox/delivery commands remain available for old
installations. Their databases and the original pilot are preserved; the new API
does not automatically import their archived data. See [company-delivery.md](company-delivery.md)
only if continuing that older architecture.

## Failure handling and troubleshooting

Uploads retain the exact pending batch until a matching receipt arrives. Transient
network errors, HTTP 408/429 and server 5xx responses retry after 30 seconds,
doubling up to five minutes. A longer numeric or HTTP-date Retry-After is honored.
Logs identify the failure type/status, pending filename, retry delay and recovery.
Do not delete pending files. Bad receipts and permanent upload rejections stop
rather than silently discarding data; check the API URL/token/schema and restart
with the same state directory after resolving the cause.

If the API stops responding on Windows, press Esc in its terminal to clear any
console text selection, then check /health and /openapi.json. Selection can block
console output; it is not the only possible cause of a hang. HTTP access logging
is off by default to reduce terminal output; enable `marketdata-simple serve
--access-log` when diagnosing requests. Startup and error logs remain enabled.
Database pool waits are bounded at five seconds and native database operations at
20 seconds. Handled database/network/timeouts return HTTP 503 with Retry-After: 30.
An unresponsive process/network can still time out without returning JSON.
WebSockets close with code 1013 on temporary database failures; reconnect with
the last processed cursor. These changes do not alter the chart response format.

TSETMC drains already staged uploads before its startup identity lookup. Temporary
network/DNS/timeout/server lookup failures retry at 60 seconds, increasing to five
minutes. Invalid identities and access denials stop; they are never bypassed.
Normal polling reports the error category and status instead of only an exception
class. `--once` continues to exit unsuccessfully on source failures.

## Source validation

See [the 2026-10-22 behavior review](validation-review-2026-10-22.md) for live
Foolad endpoint comparisons and validation changes. Current responses can carry
an older source date even when polling succeeds. The source clock is not a
verified last-trade timestamp. Keep machine clocks synchronized: source event
times more than five minutes ahead of receipt are rejected by local policy.
