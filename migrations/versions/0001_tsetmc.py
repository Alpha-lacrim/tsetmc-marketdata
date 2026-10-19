"""Independent TSETMC Milestone 2 schema. Frozen versioned metadata, no runtime DDL."""

from alembic import op

from tsetmc_marketdata.storage.schema_v1 import metadata

revision = "0001_tsetmc"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata.create_all(op.get_bind())


def downgrade() -> None:
    metadata.drop_all(op.get_bind())
