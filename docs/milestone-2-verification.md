# Milestone 2 verification — 2026-10-19

This report records local implementation qualification before publication. The
owner subsequently authorized committing and pushing Milestone 2 directly to
`main`. Baseline commit
`87690cb1f03f2b3deecb122c58eb48c06dff4e06` and annotated tag
`v0.1.0-milestone1` remain unchanged. No new tag, release, company API change,
remote synchronization or deployment is included in Milestone 2 publication.

## Environment and database

Windows PowerShell, Python 3.12.7, uv and Docker Desktop were used. A second run
uses Linux Python 3.12.15 in a disposable container on the independent local
TSETMC Docker network. PostgreSQL reports **16.1 (Debian 16.1-1.pgdg120+1)**.
The implementation uses SQLAlchemy 2.0.55, asyncpg 0.32.0 and Alembic 1.20.0,
pinned by uv.lock. Migration head is `0002_instrument_links`, 11 application tables
plus Alembic's version table.

The independent Compose project is `tsetmc-m2-local`, service postgres, persistent
volume `tsetmc-m2-local_pgdata`, database `tsetmc_marketdata`, loopback host port
5542, owner `tsetmc_owner` and restricted collector `tsetmc_collector`. Existing
Docker projects/volumes and listeners were inspected first. No unrelated Docker
resource was altered. Only this project's container was restarted/recreated, with
the volume preserved and successful schema/data readback afterwards.

## Live pilot evidence

Only `46348559193224090` was requested live. Metadata resolves to فولاد / فولاد
مبارکه اصفهان / `IRO1FOLD0001`, checked against the configured identifier.
Four one-shot jobs made **eight logical HTTP requests**, with retries disabled,
35-second per-request total deadlines and one-second start pacing:

| Job | Result |
|---|---|
| backfill-history | 4,662 source rows, 4,662 accepted/inserted, zero quarantine |
| observe-current | One stored current snapshot and latest pointer |
| reconcile-history --date 20250729 | Valid dated source agrees with stored list; one recorded confirmation |
| audit-history | 4,662 unchanged, zero inserted/corrected/conflicting records |

Canonical range is **2007-03-11 through 2026-10-18**. No archive-completeness claim
is made. Coverage has 4,247 observed, 414 explicitly zero-activity, and one
reconciled date. Zero-activity observations do not prove exchange holidays. There
are zero live canonical revisions and zero live quarantines in this fresh database.
All **285** positive-trade official closes outside the executed range were preserved.
The complete 14-column models and exact NUMERIC values were read back through the
same DailyRecord model; four change fields remain model calculations, not rounded
stored frontend values.

Milestone 1's private capture had 4,661 rows, 4,660 accepted and one zero-opening
anomaly. The later live list now has July 29 opening 2956, matching the target.
The upstream reason for the archive change is unknown. The original capture was
replayed separately in a disposable database: 4,660 accepted + one quarantine;
target reconciliation produced 4,661 canonical dates and one resolved quarantine,
retaining both sources. Repeating reconciliation created zero revisions. This
separate replay made **zero HTTP requests** and did not overwrite live history.

The current source date/time was 2026-10-19 12:29:59 Asia/Tehran, interpreted as
08:59:59 UTC; HTTP receipt was 09:54:56.412570 UTC. Both survive independently in
PostgreSQL. The response's zero insCode was bound to the verified request identity
using the existing parser. A successful snapshot is not a new-trade or complete
market-session qualification. No continuous live polling was started.

Raw source bodies, hashes, exact readback, run summaries, replay reports, live
exports and database backups remain in ignored `.local/`, `output/` and the local
database, not in public Git or distributions. Redistribution permission remains
unresolved. Public tests and this illustrative JSON use synthetic values only.

## Frontend verification

Read-only database export with `accepted-unverified` produced 4,662 values in each
of a–h, ordered by date, with genuine f/count, g/volume and h/value; zero unknown
activity placeholders were needed. Optional legacy i:null was included deliberately.
Default finalized selection produced eight empty arrays and reported 4,662
source-unverified exclusions. No quarantine/provisional row was silently finalized.
Timestamp policy remains date-midnight UTC, not Tehran market time or receipt time.

Synthetic PostgreSQL round-trip example (2025-07-29; not a live financial extract):

```json
{"a":[1753747200],"b":[1010.0],"c":[1020.0],"d":[1040.0],"e":[1000.0],"f":[1234],"g":[7000000123.0],"h":[7154000125700.0]}
```

## Automated verification

Final results (zero failures in each completed check):

| Environment / command | Passed | Failed | Skipped |
|---|---:|---:|---:|
| Windows default offline pytest, original private captures present | 167 | 0 | 37 |
| Windows full suite with --postgres, original private captures present | 201 | 0 | 3 |
| Linux public checkout, default offline pytest | 160 | 0 | 44 |
| Linux public checkout with --postgres | 193 | 0 | 11 |

There are 204 collected cases. Windows executed all 34 PostgreSQL integration
cases, including backup/restore. Linux executed 33; the Docker-exec-specific
backup case was skipped because the verification container has no Docker socket.
It was executed successfully from Windows against the same PostgreSQL 16.1
service. The public checkout skips seven private-capture cases. Three opt-in live
pytest cases were **not executed** on either platform to avoid redundant traffic;
the eight-request qualification above exercised real persistence separately.

`uv sync --locked`, Ruff lint, Ruff formatting and strict mypy passed. Mypy checks
all source and operation scripts (34 files). Wheel and source-distribution builds
passed on Windows and Linux. A separate Windows virtual environment installed
the exact runtime dependencies exported from uv.lock and the built wheel, then
verified bundled instrument config, packaged fresh migrations in another disposable
database, original offline CLI, restricted DB CLI and a 4,662-record stored export
from outside the checkout. An initial offline dependency install lacked cached
registry metadata; installing the locked runtime requirements with network access
resolved it. Automated tests themselves remain offline.

An actual private backup of the qualified local database restored to a disposable
database with 4,662 daily records, one current snapshot and eight observations.
Container restart/recreation retained the volume and every exported financial value.
The stored ChartData export was compared against typed database reads at all
4,662 indices, including optional i:null and the default empty-finalized result.
Integration tests use actual PostgreSQL with uniquely created disposable databases;
source data is synthetic and the default suite requires no DB or internet. No
SQLite substitute is used. Private-capture regressions remain optional.

## Change inventory and compatibility

The final publishable project inventory contains **89 files**: 54 baseline files
and 35 new files; 16 existing files are modified. Private artifacts remain excluded
from the publication commit.
New files cover `storage/`, `collection/`, `db_cli.py`, two Alembic revisions and
configuration, independent Compose/init/config files, the local operations helper,
PostgreSQL tests, policy unit tests and seven Milestone 2 documents. Existing changes
cover dependency/lock files, ignore/environment policy, repository instructions,
README/design/frontend/API documentation, CLI routing, test opt-in controls and CI.

Original source models, parsers, calendars and ChartData adapter remain unchanged.
All Milestone 1 test cases are retained; conftest adds opt-in database controls.
HTTP changes expose configurable pool size and actual attempt
start time. A small pre-existing environment-conversion bug was corrected: fractional
timeout/pacing values now parse as floats even when their default literal was an
integer. A regression verifies fractional pacing. No financial semantics were
redesigned or replaced.

Verified scenarios include fresh upgrade/downgrade/re-upgrade, absent/incompatible
schema refusal, exact large NUMERIC and Decimal hashes, int64 export rejection,
idempotent run replay and archive repeat, genuine corrections/no fake revisions,
malformed/duplicate quarantine, original-anomaly equivalent, target conflicts,
official close outside range, zero versus missing activity, raw bytes/hash,
cancellation/rollback, actual process death before/after commit, lost acknowledgment,
abandoned-run recovery, concurrent history/current ownership, arrivals during a
transaction, lost ownership fencing, older/equal/unknown current position, explicit
same-time correction, two synthetic instrument isolation including composite-FK
rejections, source failure categories/restart, PostgreSQL errors, dry-run safety,
retention protection and isolated pg_dump/pg_restore.

The scheduler is verified with an injected clock for manual windows, slow jobs,
non-overlap, cancellation, denial stops and bounded transient retries. It does not
claim qualified session hours. GitHub Actions configuration adds isolated
PostgreSQL tests without TSETMC access. The results above are local verification;
GitHub Actions runs and their results are reported separately by GitHub.

## Security and isolation

Secrets and genuine data remain ignored, and source/distribution scans check both
old and newly added files. A test failure exposed a local-only URL in tool output;
both local role passwords were immediately rotated, configuration updated and
test fixture/config repr redacted. No real secret was written to public files.
Only explicit synthetic CI credentials appear in the workflow. No software license
or source-data redistribution permission has been added.

TradingView worktree diff/status fingerprints, including pre-existing untracked
file contents, are compared with the pre-implementation snapshot. Neither those
repositories nor their configuration, databases, volumes, services or company
FastAPI were touched. Baseline commit/tag and origin remain unchanged. See
[operations](collector-operations.md), [recovery](recovery-and-backup.md) and
[next milestone](next-milestones.md) for supported procedures and remaining limits.
