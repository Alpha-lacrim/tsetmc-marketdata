# Fixture provenance

Every `synthetic-*.json` file in this directory contains invented test measurements.
They are not captured TSETMC responses or copied third-party examples. Dates,
prices, volumes, values and metadata are test inputs, not evidence that a session
or trade occurred. `synthetic-daily.json` is the dated-object form of the first
synthetic history row. The pilot identifier/name provides instrument context only.

The original Milestone 1 genuine captures and derived evidence remain locally in
ignored `docs/evidence/`; they are excluded from Git, source distributions and
wheels because redistribution permission has not been established. They have not
been replaced or relabeled as synthetic. `test_captured_pilot.py` still checks those
original captures when the complete local set exists, otherwise its seven tests
are explicitly skipped with the `private_capture` marker. A public clone does not
reproduce the historical live qualification from these synthetic fixtures.

Public examples in `examples/` are generated only from synthetic fixtures.
See [publication audit](../../docs/publication-audit.md) and
[historical qualification findings](../../docs/pilot-verification.md).
