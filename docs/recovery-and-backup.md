# Recovery and backup

The persistent TSETMC Compose volume is retained. Never use `down -v`, global Docker
prune, or a database reset to recover a collector. No unrelated resource belongs
to this project. Owner and collector credentials are separate and must be backed
up privately; Compose initialization scripts run only on a fresh volume.

## Migration

```powershell
uv run python scripts/local_db.py start
uv run python scripts/local_db.py migrate
uv run python scripts/local_db.py run -- db-status
```

The helper performs explicit `alembic upgrade head` with the owner URL. Never stamp
a failed migration successful. If an upgrade fails, preserve its error privately,
inspect `alembic current` with the owner environment, restore/test the last backup
in a separate database, and fix/retry the specific migration. Transactional DDL
rolls back failed changes where PostgreSQL permits it. Collectors refuse an absent
or incompatible schema rather than modifying it.
Revisions are manually authored. `schema_v1.py` freezes the initial DDL rather
than declaring the current migration head; do not use Alembic autogenerate against
that historical metadata. Add explicit upgrade/downgrade operations in a new
revision and test them in disposable databases.

Actual integration tests upgrade from empty, downgrade to base **only in generated
disposable test databases**, upgrade again, and reject an incompatible revision.
Do not perform downgrade-to-base on the persistent collector database.

## Transaction and restart protocol

The running row commits before retrieval. Source evidence, financial rows,
revisions, quarantine, latest pointer, coverage and committed checkpoint commit
together. Before commit, process death rolls all data writes back and leaves a
truthful running attempt. A new owner marks that instrument's abandoned runs
interrupted. Repeating the job safely imports or rechecks the same dates.

After commit, process death or a lost acknowledgment does not undo data. Reusing
the same run UUID and identical job specification returns the saved committed
summary without a second retrieval. A new run ID performs a fresh idempotent
retrieval. Failure handling never relabels a successful commit failed. If the DB
connection itself is lost, it does not transparently reacquire the lock and keep
writing: restart with a new owner. Failure status may remain running until that
recovery because an unavailable DB cannot record its own failure.

Actual process-crash tests terminate child processes with `os._exit` immediately
before and after commit. Additional tests cover cancellation, lost acknowledgment,
concurrent history/current ownership, stale source positions, transaction rollback,
source failure and safe repeat. They do not kill any unrelated collector or DB.

## Private backups and isolated restore verification

```powershell
uv run python scripts/local_db.py backup --output .local/backups/qualification.dump
uv run python scripts/local_db.py restore-check .local/backups/qualification.dump
```

Backup uses PostgreSQL 16.1 `pg_dump --format=custom --no-owner --no-acl` inside only
the verified TSETMC Compose container. Python transports bytes directly, avoiding
PowerShell text-pipeline corruption. Existing backup paths are never overwritten;
backups must remain under ignored `.local`. Restrict filesystem permissions and
copy backups plus credentials to an owner-approved private backup location.

`restore-check` creates a random `tsetmc_test_<hex>` database, restores with
`pg_restore --exit-on-error`, verifies schema and counts, then removes only that
database. It never overwrites `tsetmc_marketdata` or deletes its volume. Tests also
verify restored raw SHA-256 evidence and financial reads on synthetic databases.

For an actual recovery, first stop only TSETMC collection commands. Keep the
damaged persistent database and volume intact for investigation. Validate the
chosen backup using restore-check, then restore to a separately provisioned local
TSETMC database/volume and explicitly select its verified configuration after
review. The helper deliberately does not offer a destructive in-place restore.
Do not edit `DatabaseSettings` isolation guards to point at company databases.

Docker container restart and persistent-data readback were tested on the independent
local TSETMC container. This verifies restart durability, not disaster recovery
against loss of the host or volume. Store private backups away from that same host
before relying on operational recovery.
