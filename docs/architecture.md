# Milestone 1 architecture

Milestone 3A extends the M2 collector through [durable scheduling](milestone-3a-design.md),
without replacing the source/parsing/presentation boundary below. No company
integration or synchronization has been added.

Milestone 2 adds independent local PostgreSQL storage and collectors. See
[current design](milestone-2-design.md), [schema](database-schema.md), and
[operations](collector-operations.md). The exclusions below describe the original
Milestone 1 scope; its pure source/model/presentation boundary remains in use.

`HTTP JSONResponse → pure parsers → typed DailyRecord / CurrentPrice / Instrument`

`validated DailyRecord sequence → pure ChartData adapter → a–h JSON`

The layers are deliberately small. `providers/http_client.py` owns a reusable
httpx AsyncClient, per-phase timeouts, total deadline, start pacing, bounded retries,
backoff/jitter, Retry-After and safe errors. Endpoint services restrict live access
to the authorized pilot. Pure parsers/models can support future instruments without
an instrument registry. The CLI is an explicit orchestration boundary.

Financial measurements are Decimal, counts are arbitrary-precision Python integers,
and identifiers are strings. Lossless JSON decoding uses Decimal for fractional and
exponent numbers, with ordinary exact integers. Binary floats, NaN, duplicate object
keys, abbreviated measurements, bad dates, identity mismatches and invalid ranges
are rejected. Missing measurement keys/null remain unknown. Percentages use at
least 50 significant decimal digits; recurring ratios are rounded only in the
computed percentage. Source decimals are not rounded. No price adjustment is applied.

History parsing retains the complete raw envelope. Malformed rows are quarantined
with their source index, payload and reason; unrelated valid days survive. Identical
financial duplicates retain one record plus a diagnostic; conflicting duplicates
quarantine the whole date. Added fields survive unchanged and produce informational
diagnostics. No arbitrary 'latest row wins' rule exists.

Successful HTTP bodies are available verbatim alongside decoded payloads. Capture
manifests record endpoint, aware UTC receipt, bytes and SHA-256. Model diagnostic
serialization uses exact decimal strings; raw captures keep original numeric JSON.
No database credentials, authentication or company runtime configuration is needed.
Genuine captures and derived evidence under docs/evidence/ are ignored local artifacts,
not public fixtures. Synthetic examples are the public reproducibility boundary.
See [publication audit](publication-audit.md).

Transport errors are separate from SourceDataError. HTTP 429 and 500/502/503/504,
network failures, DNS failures and phase timeouts retry within the configured bound.
Other HTTP errors, access denial, invalid JSON and schema errors do not retry.
Retry-After is honored; a delay beyond the configured cap stops the probe rather
than retrying early. An outer deadline includes pacing, retries and body receipt.
External cancellation propagates and context-manager exit closes resources. HTTP
redirects are not followed. Environment proxies/cookies/credentials are not inherited.
DNS classification requires an underlying socket.gaierror; an opaque connect error
is classified as network failure. Generic HTTP 404 is not proof an instrument is
absent; a null instrument/current envelope is the explicit not-found signal.

Only independent local files were created. No TradingView code, configuration,
database, Docker volume or collector is consumed. There is no PostgreSQL dependency,
ORM, migration, scheduler, synchronization worker or FastAPI application in this
milestone. Future stages are specified in [next-milestones.md](next-milestones.md).
