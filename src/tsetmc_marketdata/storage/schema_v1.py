"""Immutable schema for migration 0001. Future schema changes require new migrations."""

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

SCHEMA_REVISION = "0001_tsetmc"
metadata = sa.MetaData()
MEASUREMENTS = (
    "previous_close",
    "opening_price",
    "last_traded_price",
    "high",
    "low",
    "official_close",
    "trade_count",
    "traded_volume",
    "traded_value",
)


def measurements() -> list[sa.Column[Any]]:
    return [sa.Column(name, sa.Numeric(), nullable=True) for name in MEASUREMENTS]


def measurement_checks(prefix: str) -> list[sa.CheckConstraint]:
    checks = [
        sa.CheckConstraint(f"{n} IS NULL OR {n} >= 0", name=f"{prefix}_{n}_positive")
        for n in MEASUREMENTS
    ]
    checks += [
        sa.CheckConstraint(
            "trade_count IS NULL OR trade_count = trunc(trade_count)",
            name=f"{prefix}_count_integral",
        ),
        sa.CheckConstraint("high IS NULL OR low IS NULL OR high >= low", name=f"{prefix}_range"),
    ]
    for name in ("opening_price", "last_traded_price"):
        checks.append(
            sa.CheckConstraint(
                f"{name} IS NULL OR low IS NULL OR high IS NULL OR low <= 0 OR "
                f"trade_count = 0 OR traded_volume = 0 OR {name} BETWEEN low AND high",
                name=f"{prefix}_{name}_range",
            )
        )
    return checks


runs = sa.Table(
    "collection_runs",
    metadata,
    sa.Column("run_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("ins_code", sa.Text, nullable=False),
    sa.Column("job", sa.Text, nullable=False),
    sa.Column("request_spec", JSONB, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("ended_at", sa.DateTime(timezone=True)),
    sa.Column("failure_category", sa.Text),
    sa.Column("summary", JSONB, nullable=False, server_default="{}"),
    sa.Column("checkpoint", JSONB, nullable=False, server_default="{}"),
    sa.CheckConstraint(
        "status IN ('running','success','partial','failed','interrupted')", name="run_status"
    ),
)
instruments = sa.Table(
    "instruments",
    metadata,
    sa.Column("ins_code", sa.Text, primary_key=True),
    sa.Column("ownership_key", sa.Integer, sa.Identity(), nullable=False, unique=True),
    sa.Column("active", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("symbol", sa.Text),
    sa.Column("company_name", sa.Text),
    sa.Column("instrument_id", sa.Text),
    sa.Column("isin", sa.Text),
    sa.Column("source", sa.Text, nullable=False, server_default="tsetmc"),
    sa.Column("verified_at", sa.DateTime(timezone=True)),
    sa.Column("raw_metadata", JSONB),
    sa.Column(
        "metadata_observation_id",
        sa.BigInteger,
        sa.ForeignKey(
            "source_observations.observation_id",
            use_alter=True,
            name="instrument_metadata_evidence",
        ),
    ),
    sa.CheckConstraint("ins_code ~ '^[0-9]+$'", name="instrument_code_digits"),
)
observations = sa.Table(
    "source_observations",
    metadata,
    sa.Column("observation_id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey(runs.c.run_id), nullable=False),
    sa.Column("ins_code", sa.Text, sa.ForeignKey(instruments.c.ins_code), nullable=False),
    sa.Column("endpoint", sa.Text, nullable=False),
    sa.Column("request_parameters", JSONB, nullable=False, server_default="{}"),
    sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("received_at", sa.DateTime(timezone=True)),
    sa.Column("http_status", sa.Integer),
    sa.Column("raw_body", sa.LargeBinary),
    sa.Column("raw_sha256", sa.String(64)),
    sa.Column("body_pruned_at", sa.DateTime(timezone=True)),
    sa.Column("parser_version", sa.Text, nullable=False),
    sa.Column("source_kind", sa.Text, nullable=False),
    sa.Column("processing_status", sa.Text, nullable=False),
    sa.Column("failure_category", sa.Text),
    sa.CheckConstraint(
        "raw_body IS NULL OR (received_at IS NOT NULL AND raw_sha256 IS NOT NULL)",
        name="body_requires_receipt_and_hash",
    ),
)
daily = sa.Table(
    "daily_records",
    metadata,
    sa.Column("ins_code", sa.Text, sa.ForeignKey(instruments.c.ins_code), primary_key=True),
    sa.Column("trading_date", sa.Date, primary_key=True),
    *measurements(),
    sa.Column("source_d_even", sa.Text),
    sa.Column("source_h_even", sa.Text),
    sa.Column("raw_row", JSONB, nullable=False),
    sa.Column(
        "observation_id",
        sa.BigInteger,
        sa.ForeignKey(observations.c.observation_id),
        nullable=False,
    ),
    sa.Column("financial_hash", sa.String(64), nullable=False),
    sa.Column("revision", sa.Integer, nullable=False),
    sa.Column("acceptance", sa.Text, nullable=False),
    sa.Column("finalization_state", sa.Text, nullable=False, server_default="source_unverified"),
    sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("revision >= 1", name="daily_revision_positive"),
    sa.CheckConstraint("acceptance IN ('observed','reconciled')", name="daily_acceptance"),
    sa.CheckConstraint(
        "finalization_state IN ('source_unverified','operator_finalized')",
        name="daily_finalization",
    ),
    *measurement_checks("daily"),
)
revisions = sa.Table(
    "daily_revisions",
    metadata,
    sa.Column("revision_id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("ins_code", sa.Text, nullable=False),
    sa.Column("trading_date", sa.Date, nullable=False),
    sa.Column("revision", sa.Integer, nullable=False),
    sa.Column("old_state", JSONB, nullable=False),
    sa.Column("new_state", JSONB, nullable=False),
    sa.Column("old_hash", sa.String(64), nullable=False),
    sa.Column("new_hash", sa.String(64), nullable=False),
    sa.Column(
        "old_observation_id",
        sa.BigInteger,
        sa.ForeignKey(observations.c.observation_id),
        nullable=False,
    ),
    sa.Column(
        "new_observation_id",
        sa.BigInteger,
        sa.ForeignKey(observations.c.observation_id),
        nullable=False,
    ),
    sa.Column("reason", sa.Text, nullable=False),
    sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(["ins_code", "trading_date"], [daily.c.ins_code, daily.c.trading_date]),
    sa.UniqueConstraint("ins_code", "trading_date", "revision", name="revision_per_day"),
    sa.CheckConstraint("old_hash <> new_hash", name="revision_requires_change"),
)
snapshots = sa.Table(
    "current_snapshots",
    metadata,
    sa.Column("snapshot_id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("ins_code", sa.Text, sa.ForeignKey(instruments.c.ins_code), nullable=False),
    sa.Column(
        "observation_id",
        sa.BigInteger,
        sa.ForeignKey(observations.c.observation_id),
        nullable=False,
        unique=True,
    ),
    *measurements(),
    sa.Column("source_date", sa.Date),
    sa.Column("source_time", sa.Time),
    sa.Column("source_reported_at", sa.DateTime(timezone=True)),
    sa.Column("source_d_even", sa.Text),
    sa.Column("source_h_even", sa.Text),
    sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("instrument_state", sa.Text),
    sa.Column("instrument_state_title", sa.Text),
    sa.Column("raw_row", JSONB, nullable=False),
    sa.Column("financial_hash", sa.String(64), nullable=False),
    sa.Column("decision", sa.Text, nullable=False),
    sa.Column("decision_reason", sa.Text),
    sa.Column("is_state_change", sa.Boolean, nullable=False),
    *measurement_checks("current"),
)
latest = sa.Table(
    "current_latest",
    metadata,
    sa.Column("ins_code", sa.Text, sa.ForeignKey(instruments.c.ins_code), primary_key=True),
    sa.Column("snapshot_id", sa.BigInteger, sa.ForeignKey(snapshots.c.snapshot_id), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)
quarantine = sa.Table(
    "quarantined_records",
    metadata,
    sa.Column("quarantine_id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("ins_code", sa.Text, sa.ForeignKey(instruments.c.ins_code), nullable=False),
    sa.Column("trading_date", sa.Date),
    sa.Column("record_kind", sa.Text, nullable=False, server_default="daily"),
    sa.Column(
        "observation_id",
        sa.BigInteger,
        sa.ForeignKey(observations.c.observation_id),
        nullable=False,
    ),
    sa.Column(
        "last_observation_id",
        sa.BigInteger,
        sa.ForeignKey(observations.c.observation_id),
        nullable=False,
    ),
    sa.Column("row_index", sa.Integer, nullable=False),
    sa.Column("raw_row", JSONB, nullable=False),
    sa.Column("reason", sa.Text, nullable=False),
    sa.Column("fingerprint", sa.String(64), nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default="open"),
    sa.Column("sightings", sa.Integer, nullable=False, server_default="1"),
    sa.Column(
        "resolution_observation_id", sa.BigInteger, sa.ForeignKey(observations.c.observation_id)
    ),
    sa.Column("resolution_hash", sa.String(64)),
    sa.Column("resolved_at", sa.DateTime(timezone=True)),
    sa.Column("resolution_method", sa.Text),
    sa.UniqueConstraint("ins_code", "fingerprint", name="quarantine_fingerprint"),
    sa.CheckConstraint("status IN ('open','resolved')", name="quarantine_status"),
)
decisions = sa.Table(
    "reconciliation_decisions",
    metadata,
    sa.Column("decision_id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey(runs.c.run_id), nullable=False),
    sa.Column("ins_code", sa.Text, nullable=False),
    sa.Column("trading_date", sa.Date, nullable=False),
    sa.Column(
        "candidate_observation_id",
        sa.BigInteger,
        sa.ForeignKey(observations.c.observation_id),
        nullable=False,
    ),
    sa.Column(
        "previous_observation_id", sa.BigInteger, sa.ForeignKey(observations.c.observation_id)
    ),
    sa.Column("accepted", sa.Boolean, nullable=False),
    sa.Column("reason", sa.Text, nullable=False),
    sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
)
status = sa.Table(
    "collection_status",
    metadata,
    sa.Column("ins_code", sa.Text, sa.ForeignKey(instruments.c.ins_code), primary_key=True),
    sa.Column("job", sa.Text, primary_key=True),
    sa.Column("last_run_id", UUID(as_uuid=True), sa.ForeignKey(runs.c.run_id), nullable=False),
    sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_success_at", sa.DateTime(timezone=True)),
    sa.Column("failure_category", sa.Text),
    sa.Column("failure_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("retry_after", sa.DateTime(timezone=True)),
)
coverage = sa.Table(
    "data_coverage",
    metadata,
    sa.Column("ins_code", sa.Text, sa.ForeignKey(instruments.c.ins_code), primary_key=True),
    sa.Column("trading_date", sa.Date, primary_key=True),
    sa.Column("state", sa.Text, nullable=False),
    sa.Column(
        "observation_id",
        sa.BigInteger,
        sa.ForeignKey(observations.c.observation_id),
        nullable=False,
    ),
    sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "state IN ('observed','quarantined','reconciled','confirmed_no_trade','unknown')",
        name="coverage_state",
    ),
)
sa.Index(
    "observations_instrument_receipt", observations.c.ins_code, observations.c.received_at.desc()
)
sa.Index("observations_run", observations.c.run_id)
sa.Index("runs_instrument_started", runs.c.ins_code, runs.c.started_at.desc())
sa.Index("snapshots_instrument_receipt", snapshots.c.ins_code, snapshots.c.received_at.desc())
sa.Index("snapshots_retention", snapshots.c.received_at)
sa.Index(
    "quarantine_open_date", quarantine.c.ins_code, quarantine.c.status, quarantine.c.trading_date
)
sa.Index("coverage_state_date", coverage.c.ins_code, coverage.c.state, coverage.c.trading_date)

# Composite provenance constraints prevent cross-instrument links even in direct SQL writes.
for table, key in ((runs, "run_id"), (observations, "observation_id"), (snapshots, "snapshot_id")):
    table.append_constraint(sa.UniqueConstraint(key, "ins_code", name=f"{table.name}_identity"))
observations.append_constraint(
    sa.ForeignKeyConstraint(
        ["run_id", "ins_code"], [runs.c.run_id, runs.c.ins_code], name="observation_run_identity"
    )
)
latest.append_constraint(
    sa.ForeignKeyConstraint(
        ["snapshot_id", "ins_code"],
        [snapshots.c.snapshot_id, snapshots.c.ins_code],
        name="latest_snapshot_identity",
    )
)
for table, columns in (
    (daily, ["observation_id"]),
    (revisions, ["old_observation_id", "new_observation_id"]),
    (snapshots, ["observation_id"]),
    (quarantine, ["observation_id", "last_observation_id", "resolution_observation_id"]),
    (coverage, ["observation_id"]),
    (decisions, ["candidate_observation_id", "previous_observation_id"]),
):
    for column in columns:
        table.append_constraint(
            sa.ForeignKeyConstraint(
                [column, "ins_code"],
                [observations.c.observation_id, observations.c.ins_code],
                name=f"{table.name}_{column}_identity",
            )
        )
