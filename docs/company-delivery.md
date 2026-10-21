# Opt-in delivery to the shared company API

This source checkout adds migration `0005_delivery` and an explicitly activated
HTTPS worker. It uses the existing `tsetmc.v1` contract. Acquisition remains an
independent TSETMC process and database; no company DB password belongs here.
The matching `tradingview-main-consolidation` checkout contains the company
receiver, schema `0011`, one READ application, and `docs/unified-dashboard-flow.md`
with the complete installation sequence and frontend routes.

The original persistent Foolad pilot was not migrated, enrolled, or written during
this work. Tests use invented records in newly created PostgreSQL 16.1 databases.
Neither this integration nor the preceding live pilot proves all-market coverage.

## Connect an approved source database

1. Back up and restore-check that database; stop its writers for the upgrade.
   Set its private `TSETMC_MIGRATION_URL` and run `uv run alembic upgrade head`.
   Apply `scripts/delivery_grants.sql` as the owner. Existing applied migrations
   remain unchanged. The collector now requires `0005_delivery` at startup.
2. Use the company's `scripts/prepare_tsetmc_connection.py` to create matching
   identities and private credentials. Provision its company plan and credential
   hash on the company host first. Copy only `source-binding.json`, `worker.json`
   and `producer.token` to this host. Update absolute paths in `worker.json` if
   moving between hosts. Use the actual HTTPS origin and verified CA.
3. Set `TSETMC_DATABASE_URL` to the local collector principal's database URL.
   Pause collection briefly and enroll stored observations; this does not fetch
   the provider or declare the archive complete:

   ```powershell
   uv run python -m tsetmc_marketdata.enrollment --binding C:/private/tsetmc-connection/source-binding.json --activate
   uv run python -m tsetmc_marketdata.delivery --config C:/private/tsetmc-connection/worker.json --seconds 3600 --activate
   ```

   Reuse the binding and seed on retry. Enrollment is bounded to 10,000 daily rows
   and 32 MiB. `--drain` exits when the present backlog is empty; otherwise the
   worker polls within the requested window. Keep using the collector's bounded
   scheduler independently. No service or autostart is installed.

## Delivery and recovery

One advisory-lock coordinator owns a producer. Short source transactions also use
the existing instrument fence; HTTPS never holds that instrument lock. Exact
request bytes are stored before sending. The worker checks for an existing
company receipt, validates and stores it, then acknowledges the source position.
Daily and coverage records preserve order; current and status heads may coalesce.
Simulated local batches cannot be mixed with authenticated delivery.

After an expired session, the worker uses the company's fenced recovery protocol.
An uncommitted old-session request may receive a new envelope with identical
observations; original bytes remain stored. Lost responses are resolved by receipt
lookup. Neither a retry nor a newer receipt makes an old price fresh.

Keep the external continuity anchor outside database backups and preserve it on
restart. A restored source behind that evidence, a lost company receipt, changed
ownership, destination identity, epoch, or manifest stops delivery for review.
Do not reset cursors or invent new identities to bypass that stop. The company's
stored REST and WebSocket data remain available during source outages.

## Limits before unattended operation

The worker uses the trusted local collector principal. A dedicated restricted
SQL-function worker role is not implemented. Startup audits up to 10,000 retained
batches; source budgets and this audit ceiling fail closed. No automatic pruning
or company journal retention is supplied. Startup receipt audit time is additional
to the bounded delivery loop. Operators must qualify storage, restart duration,
backup/restore and retention for their workload before unattended deployment.

Only Foolad has earlier genuine pilot evidence. This change does not expand live
instruments, verify units or upstream finality, add minute history, or assert
real-time delivery. Default finalized history may be empty; accepted-unverified
history must remain explicitly labeled.
