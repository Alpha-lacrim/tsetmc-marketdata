# Source outbox operations — local only

Milestone 3B-1 implements local source primitives, **no network delivery**. The
original pilot is protected: do not run migrate, seed/enrollment, restore, write
tests or new-code collector commands against it during this milestone. No company
host, DSN, credential, real producer or automatic service belongs in these steps.

## Safe inspection and disposable qualification

First inspect Git status, available DB/Docker resources and process ownership.
Never print URL passwords or container environments. A name containing test/local
does not prove isolation. Verify the exact host/port, PostgreSQL server_version_num
(160001), data_directory, task ownership, role and database before permitting writes.
Do not start unrelated services merely to obtain a test database.

The task used a portable PostgreSQL 16.1 cluster under ignored .local, loopback
only, with no Windows service or Docker startup. Binaries are private tooling,
not application dependencies or published fixtures. The server is stopped after
verification. Linux may use a newly isolated postgres:16.1 instance with no old
volumes or auto-start; that path was not executed locally in this milestone.

After safely provisioning an independent disposable instance, supply its private
admin URL to `TSETMC_TEST_ADMIN_URL`, then:

```powershell
uv sync --locked
uv run --offline pytest
uv run --offline pytest tests/integration --postgres
uv run --offline ruff check .
uv run --offline ruff format --check .
uv run --offline mypy
```

The test fixture creates/drops only newly generated tsetmc_test_<hex> databases.
The task's private runner additionally verified its exact data directory/port and
server version before launching that fixture. `TSETMC_TEST_PG_BIN`, when explicitly
set to trusted pg_dump/pg_restore binaries, enables the synthetic dump/restore test.
The old Docker-exec backup regression needs its separately configured disposable
container; it is skipped on the portable instance, never redirected to the pilot.

Read-only `collection-status` now includes source_publication: disabled/enrolled,
stream heads/ACKs, conservative usage/limits and capacity alerts. It never enables
publication. `publication_report(conn, ins_code)` also works in Database.read()
without creating an instrument or acquiring write ownership. The new checkout
expects source schema 0004; use the older checkout for the unupgraded pilot rather
than weakening schema checks or applying a migration implicitly.

## Explicit source-only seed API

There is deliberately no live enrollment/seed CLI or environment auto-activation.
Only an administrator's reviewed program may configure the storage API. A toy
disposable-only harness follows; UUID inputs are chosen once and retained, never
rotated after a conflict/restore:

```python
# db must already be verified as a task-owned disposable PostgreSQL 16.1 database.
async with db.owner(synthetic_ins_code) as conn:
    repo = Repository(conn, synthetic_ins_code)
    async with repo.atomic():
        box = SourceOutbox(repo)
        await box.configure(
            source_epoch=chosen_epoch,
            installation_id=chosen_installation,
            destination_id=synthetic_destination,
            producer_id=synthetic_producer,
        )  # still disabled; these UUIDs do not provision any company entity
        report = await box.enroll(
            seed_id=chosen_seed,
            allow_local_publication=True,
            max_daily_rows=10_000,
            max_bytes=32 * 1024 * 1024,
        )
```

This seeds only already committed local synthetic data. It never fetches TSETMC,
changes prices/revisions/reviews/finality, moves current_latest or uploads. Limits
include retained revision evidence and coverage/current records, and roll back
the whole seed on refusal. A repeated committed seed ID returns replayed=true.
Other seed IDs or modified bindings fail closed. No real pilot seed was run.

## Local simulated delivery and recovery

stage(..., simulate=True), receive(..., simulate=True) and
acknowledge(..., simulate=True) are storage test interfaces, each inside its own
Repository.atomic transaction. Save exact staged BYTEA before any simulated reply.
Require the same session envelope on repeated staging; never edit old bytes or
reuse a batch ID for changed content. A receipt is validated before being stored;
ACK may occur after a process restart by reading that saved phase.

No synthetic receipt proves company commit. All batches are explicitly simulated;
no production worker should call these methods as an authenticated receipt path.
Real lease rotation, secure receipt retrieval, old-generation fencing, external
anchor persistence and administrator handover require the later worker stage.
Never mint a new epoch, rewind ACKs or silently re-enroll after a mismatch.

Capacity alerts occur at 70/85% of configured per-stream publication/staging budgets.
At capacity, pause affected collection and review storage; failed publication must
not commit its financial mutation. Disk/WAL/backup usage needs separate monitoring.
No sync cleanup command exists: retain unacknowledged data and all referenced raw
bodies/snapshots/reviews. New cumulative budgets do not automatically reclaim space
when a latest head coalesces or a simulated ACK arrives.

## Backups and original pilot boundaries

For a **future separately authorized** pilot upgrade: inventory the running head,
stop only approved TSETMC writers, make a private consistent pg_dump with matching
tools, restore into a separately provisioned disposable database, verify all raw
hashes and canonical/revision/review/latest/scheduler fingerprints, then qualify
0003→0004 on that copy. Only a separate owner instruction may authorize applying
the migration to the original. Preserve existing volume, config and backup files.

This task performed dump/restore only on invented disposable data. It did not
restore an actual archive backup or prove the real 4,662-row pilot fingerprint.
Backup restoration can regress heads/batches; continuity proof from outside that
backup must fence such a rollback before future delivery. A perfectly cloned
DB+anchor+credentials cannot identify two machines; administration is required.
Never use downgrade, reset, prune, volume removal or broad cleanup on the pilot.
