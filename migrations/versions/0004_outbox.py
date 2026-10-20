"""Add disabled, instrument-scoped local publication and simulated delivery state."""

from alembic import op

from tsetmc_marketdata.storage.schema_v3b1 import metadata

revision = "0004_outbox"
down_revision = "0003_scheduling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata.create_all(op.get_bind())
    op.execute("""CREATE FUNCTION sync_immutable() RETURNS trigger LANGUAGE plpgsql
    SET search_path=pg_catalog,public AS $$ BEGIN
      RAISE EXCEPTION 'immutable synchronization evidence'; END $$""")
    for table in ("sync_outbox", "sync_evidence_refs"):
        op.execute(
            f"CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION sync_immutable()"
        )
    op.execute("""CREATE FUNCTION sync_batch_guard() RETURNS trigger LANGUAGE plpgsql
    SET search_path=pg_catalog,public AS $$ BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'retained synchronization batch'; END IF;
      IF (to_jsonb(NEW)-'phase'-'receipt') IS DISTINCT FROM
         (to_jsonb(OLD)-'phase'-'receipt') OR
         (OLD.receipt IS NOT NULL AND NEW.receipt IS DISTINCT FROM OLD.receipt) OR
         NOT ((NEW.phase=OLD.phase) OR (OLD.phase='staged' AND NEW.phase='received') OR
              (OLD.phase='received' AND NEW.phase='acknowledged')) THEN
        RAISE EXCEPTION 'immutable batch or invalid lifecycle'; END IF;
      RETURN NEW; END $$""")
    op.execute(
        "CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON sync_batches "
        "FOR EACH ROW EXECUTE FUNCTION sync_batch_guard()"
    )
    op.execute("""CREATE FUNCTION sync_dataset_guard() RETURNS trigger LANGUAGE plpgsql
    SET search_path=pg_catalog,public AS $$ BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'retained dataset identity'; END IF;
      IF (to_jsonb(NEW)-'enabled'-'enrolled'-'seed_id') IS DISTINCT FROM
         (to_jsonb(OLD)-'enabled'-'enrolled'-'seed_id') OR
         (OLD.enrolled AND (NOT NEW.enrolled OR NEW.seed_id IS DISTINCT FROM OLD.seed_id)) OR
         (OLD.enabled AND NOT NEW.enabled)
      THEN RAISE EXCEPTION 'immutable dataset binding'; END IF;
      RETURN NEW; END $$""")
    op.execute(
        "CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON sync_datasets "
        "FOR EACH ROW EXECUTE FUNCTION sync_dataset_guard()"
    )
    # Existing installations may have this role; do not provision any login/secret.
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname='tsetmc_collector')
      THEN
        REVOKE ALL ON sync_datasets FROM tsetmc_collector;
        GRANT SELECT ON sync_datasets TO tsetmc_collector;
        GRANT SELECT,INSERT ON sync_outbox,sync_evidence_refs TO tsetmc_collector;
        REVOKE UPDATE,DELETE ON sync_outbox,sync_evidence_refs FROM tsetmc_collector;
        GRANT SELECT,INSERT,UPDATE ON sync_stream_clocks,sync_daily_heads,
             sync_latest_pending,sync_batches TO tsetmc_collector;
        REVOKE DELETE ON sync_stream_clocks,sync_daily_heads,sync_latest_pending,
             sync_batches FROM tsetmc_collector;
      END IF; END $$""")
    for function in ("sync_immutable", "sync_batch_guard", "sync_dataset_guard"):
        op.execute(f"REVOKE ALL ON FUNCTION {function}() FROM PUBLIC")


def downgrade() -> None:
    metadata.drop_all(op.get_bind())
    for function in ("sync_immutable", "sync_batch_guard", "sync_dataset_guard"):
        op.execute(f"DROP FUNCTION {function}()")
