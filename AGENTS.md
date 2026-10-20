# Repository instructions

Keep all work in this independent repository. Never modify TradingView projects,
connect to their databases, use their volumes, or reuse their runtime configuration.
Milestone 3A authorizes independent PostgreSQL 16.1 storage, additive migrations,
and explicitly activated, bounded foreground scheduling here only. No installed
service, auto-start policy or unattended deployment is authorized. Session inference
must remain UNKNOWN without qualified evidence; explicit operator windows require
provenance. Preserve source uncertainty and the default finalized export selection.
Only insCode `46348559193224090` (فولاد) may be enabled or fetched live. Reusable
storage and collection code must scope ownership, keys and provenance by instrument;
use invented identities for isolation tests. Do not implement synchronization,
company FastAPI integration, deployment or additional live instruments.
Do not commit, push, tag, or release without additional explicit authorization.
Preserve commit 87690cb1f03f2b3deecb122c58eb48c06dff4e06 and v0.1.0-milestone1.
Preserve published Milestone 2 commit 01a827be39bb48864d0b76c8e952f176a4904556.
Do not edit applied migration files or frozen schema metadata; add a new revision.

Milestone 3B-1 authorizes source-only transactional publication and local simulated
staging/receipt/ACK primitives, additive 0004_outbox, tests and documentation.
The original persistent pilot is read-only: no migration, enrollment, seed,
write-oriented smoke test or backup/restore there. All write tests must first
verify a newly isolated disposable PostgreSQL 16.1 endpoint. Do not start unrelated
Docker resources. Live delivery, worker/producer coordination, company changes,
credentials and collection remain unauthorized in this task. The owner subsequently
authorized committing and pushing the reviewed Milestone 3B-1 changes directly to
main; no tag, release or deployment is authorized.
Read docs/milestone-3b1-design.md and docs/source-outbox-operations.md.

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
PostgreSQL tests are opt-in with --postgres and use unique disposable
tsetmc_test_<hex> databases. Never delete a persistent database or Docker volume.
Collector startup must verify the schema, never migrate implicitly. Keep secrets,
database backups and live exports under ignored .local/ or output/ only.
