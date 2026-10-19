"""Add durable schedules, collector health and auditable single-date operator reviews."""

from alembic import op

from tsetmc_marketdata.storage.schema_v3a import metadata

revision = "0003_scheduling"
down_revision = "0002_instrument_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata.create_all(op.get_bind())


def downgrade() -> None:
    metadata.drop_all(op.get_bind())
