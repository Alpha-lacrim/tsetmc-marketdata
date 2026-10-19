"""Frozen additive schema for Milestone 3A. Existing migration metadata is untouched."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from tsetmc_marketdata.storage import schema_v1 as base

metadata = sa.MetaData()
schedules = sa.Table(
    "scheduled_jobs",
    metadata,
    sa.Column("ins_code", sa.Text, sa.ForeignKey(base.instruments.c.ins_code), primary_key=True),
    sa.Column("schedule_key", sa.Text, primary_key=True),
    sa.Column("job", sa.Text, nullable=False),
    sa.Column("spec_hash", sa.String(64), nullable=False),
    sa.Column("next_due", sa.DateTime(timezone=True), nullable=False),
    sa.Column("active_slot", sa.DateTime(timezone=True)),
    sa.Column("active_run_id", UUID(as_uuid=True)),
    sa.Column("active_parameters", JSONB),
    sa.Column("last_completed_slot", sa.DateTime(timezone=True)),
    sa.Column("last_committed_at", sa.DateTime(timezone=True)),
    sa.Column("failure_category", sa.Text),
    sa.Column("failure_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("coalesced_slots", sa.BigInteger, nullable=False, server_default="0"),
    sa.CheckConstraint(
        "(active_slot IS NULL) = (active_run_id IS NULL)", name="active_schedule_identity"
    ),
    sa.CheckConstraint("failure_count >= 0 AND coalesced_slots >= 0", name="schedule_counts"),
)
runtime = sa.Table(
    "collector_runtime",
    metadata,
    sa.Column("ins_code", sa.Text, sa.ForeignKey(base.instruments.c.ins_code), primary_key=True),
    sa.Column("service_id", UUID(as_uuid=True), nullable=False),
    sa.Column("owner_backend_pid", sa.Integer, nullable=False),
    sa.Column("owner_backend_start", sa.DateTime(timezone=True), nullable=False),
    sa.Column("state", sa.Text, nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("ended_at", sa.DateTime(timezone=True)),
    sa.Column("config_hash", sa.String(64), nullable=False),
    sa.Column("last_financial_change_at", sa.DateTime(timezone=True)),
    sa.Column("session_expectation", sa.Text, nullable=False),
    sa.Column("session_confidence", sa.Text, nullable=False),
    sa.Column("session_provenance", JSONB, nullable=False),
    sa.Column("session_valid_until", sa.DateTime(timezone=True), nullable=False),
    sa.Column("failure_category", sa.Text),
    sa.Column("stop_reason", sa.Text),
    sa.Column("operating_state", sa.Text, nullable=False, server_default="waiting"),
    sa.CheckConstraint("state IN ('running','stopped','failed')", name="runtime_state"),
)
reviews = sa.Table(
    "daily_reviews",
    metadata,
    sa.Column("review_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("ins_code", sa.Text, nullable=False),
    sa.Column("trading_date", sa.Date, nullable=False),
    sa.Column("financial_hash", sa.String(64), nullable=False),
    sa.Column("action", sa.Text, nullable=False),
    sa.Column("actor", sa.Text, nullable=False),
    sa.Column("reason", sa.Text, nullable=False),
    sa.Column("session_end", sa.DateTime(timezone=True)),
    sa.Column("session_evidence", sa.Text),
    sa.Column("grace_seconds", sa.Integer),
    sa.Column("first_observation_id", sa.BigInteger),
    sa.Column("second_observation_id", sa.BigInteger),
    sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["ins_code", "trading_date"], [base.daily.c.ins_code, base.daily.c.trading_date]
    ),
    sa.CheckConstraint("action IN ('confirm','revoke')", name="review_action"),
)
for name in ("first_observation_id", "second_observation_id"):
    reviews.append_constraint(
        sa.ForeignKeyConstraint(
            [name, "ins_code"], [base.observations.c.observation_id, base.observations.c.ins_code]
        )
    )
sa.Index("schedule_due", schedules.c.ins_code, schedules.c.next_due)
sa.Index("reviews_instrument_day", reviews.c.ins_code, reviews.c.trading_date)
