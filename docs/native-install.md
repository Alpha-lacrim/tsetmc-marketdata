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
