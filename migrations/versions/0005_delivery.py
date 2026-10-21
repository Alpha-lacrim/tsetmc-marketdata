"""Durable producer coordinator and explicitly authenticated delivery batches."""

from alembic import op

revision = "0005_delivery"
down_revision = "0004_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sync_batches DROP CONSTRAINT sync_local_batch")
    op.execute("""ALTER TABLE sync_batches ADD CONSTRAINT sync_delivery_batch CHECK (
        phase IN ('staged','received','acknowledged') AND
        0 <= after_position AND after_position < through_position)""")
    op.execute("""CREATE TABLE sync_delivery_state (
        producer_id UUID PRIMARY KEY,
        destination_id UUID NOT NULL,
        owner_token UUID NOT NULL,
        backend_pid INTEGER NOT NULL,
        state JSONB NOT NULL DEFAULT '{}'
      )""")
    op.execute("REVOKE ALL ON sync_delivery_state FROM PUBLIC")


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT FROM sync_batches WHERE NOT simulated) THEN
      RAISE EXCEPTION 'cannot discard real delivery evidence'; END IF; END $$""")
    op.execute("DROP TABLE sync_delivery_state")
    op.execute("ALTER TABLE sync_batches DROP CONSTRAINT sync_delivery_batch")
    op.execute("""ALTER TABLE sync_batches ADD CONSTRAINT sync_local_batch CHECK (
        simulated AND phase IN ('staged','received','acknowledged') AND
        0 <= after_position AND after_position < through_position);
    """)
