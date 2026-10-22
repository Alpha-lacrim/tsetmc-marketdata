# TSETMC collector

Collect native Iranian daily history and latest observations, then send them
directly to the shared company FastAPI. No Docker or local PostgreSQL is needed.

**Start here: [native installation](docs/native-install.md).** The company API and
its PostgreSQL database are installed from the companion
[TradingView/company repository](https://github.com/alpha-lacrim/tradingview-marketdata).

```bash
uv sync --frozen --no-dev --python 3.12
export COMPANY_API_URL='http://SERVER:8000'
uv run --no-sync tsetmc-simple
```

The collector verifies Foolad (`46348559193224090`), polls current observations
every 15 seconds and available daily history hourly. Two pending-upload files
preserve interrupted HTTP transfers. Keep `.local/simple-tsetmc/` across restarts.
Use `--once`, `--poll-seconds`, `--history-seconds` and `--state-dir` as needed.

The dashboard reads from the **same company API** as international markets:

```text
/api/chart?market=tsetmc&symbol=46348559193224090&interval=1d
/api/latest?market=tsetmc&symbol=46348559193224090
```

ChartData matches a=time, b=open, c=official close, d=high, e=low, f=count,
g=volume, h=traded value, i=null. Last trade and official close remain separate.
Source decimals, original timestamps, missing values and unverified finality are
preserved. This collector does not manufacture minute history or claim all-market
coverage. HTTP/open company access is the default; an upload token is optional.

[Current state/checks](HANDOFF.md) | [Workspace/checkpoints](docs/workspace.md)

Original pilot databases, captures and the old PostgreSQL/outbox pipeline are
preserved. They are not used or migrated by the native command. The new API does
not automatically import old database archives. For older installations see the
[previous README](docs/history/readme-before-native-install.md) and
[legacy delivery guide](docs/company-delivery.md).
