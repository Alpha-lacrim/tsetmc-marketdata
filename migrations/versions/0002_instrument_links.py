"""Enforce instrument identity for metadata, status, runs and reconciliation decisions."""

from alembic import op

revision = "0002_instrument_links"
down_revision = "0001_tsetmc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_foreign_key(
        "run_instrument", "collection_runs", "instruments", ["ins_code"], ["ins_code"]
    )
    op.create_foreign_key(
        "metadata_instrument_identity",
        "instruments",
        "source_observations",
        ["metadata_observation_id", "ins_code"],
        ["observation_id", "ins_code"],
    )
    op.create_unique_constraint(
        "run_instrument_job", "collection_runs", ["run_id", "ins_code", "job"]
    )
    op.create_foreign_key(
        "status_run_instrument_job",
        "collection_status",
        "collection_runs",
        ["last_run_id", "ins_code", "job"],
        ["run_id", "ins_code", "job"],
    )
    op.create_foreign_key(
        "decision_run_identity",
        "reconciliation_decisions",
        "collection_runs",
        ["run_id", "ins_code"],
        ["run_id", "ins_code"],
    )
    op.create_check_constraint(
        "quarantine_record_kind", "quarantined_records", "record_kind IN ('daily','current')"
    )


def downgrade() -> None:
    op.drop_constraint("quarantine_record_kind", "quarantined_records", type_="check")
    op.drop_constraint("decision_run_identity", "reconciliation_decisions", type_="foreignkey")
    op.drop_constraint("status_run_instrument_job", "collection_status", type_="foreignkey")
    op.drop_constraint("run_instrument_job", "collection_runs", type_="unique")
    op.drop_constraint("metadata_instrument_identity", "instruments", type_="foreignkey")
    op.drop_constraint("run_instrument", "collection_runs", type_="foreignkey")
