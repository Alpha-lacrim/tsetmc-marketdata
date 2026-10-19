# Synthetic ChartData examples

Both JSON files are generated exclusively from the invented measurements in
`tests/fixtures/synthetic-history.json`. They are not captured market data and do
not prove live prices or sessions. `synthetic-chartdata.json` contains exactly
a–h; `synthetic-chartdata-legacy.json` additionally contains i:null.

Reproduce from the repository root:

```powershell
uv run --offline python -m tsetmc_marketdata.cli export-chartdata --input tests/fixtures/synthetic-history.json --output examples/synthetic-chartdata.json
uv run --offline python -m tsetmc_marketdata.cli export-chartdata --input tests/fixtures/synthetic-history.json --output examples/synthetic-chartdata-legacy.json --legacy-sample
```
