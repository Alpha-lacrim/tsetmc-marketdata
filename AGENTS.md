# Repository instructions

Keep all work in this independent repository. Never modify TradingView projects,
connect to their databases, use their volumes, or reuse their runtime configuration.
Milestone 1 supports only insCode `46348559193224090` (فولاد).
Do not implement persistence, migrations, polling loops, synchronization, FastAPI,
deployment, or other instruments without a later explicit task.
Do not publish, push, or release without explicit user authorization.

Use Python 3.12+, async httpx, Decimal source measurements, aware instants, and
Gregorian trading dates. Preserve raw payloads. Never conflate pDrCotVal and pClosing,
or ChartData g (volume) and h (value). Tests must run offline; live probes are opt-in,
paced, read-only, and bounded. Label fixture provenance honestly.
Genuine captures under docs/evidence/ and audit backups under .local/ are private
local artifacts, excluded from Git and distributions. Do not force-stage them.
Public examples must be synthetic and clearly labeled. No software license has
been selected by the owner; do not add one without instruction.

Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, and
`uv run pytest` after changes. Follow the conventions documented in docs/.
