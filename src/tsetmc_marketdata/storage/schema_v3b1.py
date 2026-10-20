"""Frozen additive source publication schema, migration 0004_outbox."""

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from tsetmc_marketdata.storage import schema_v1 as base

metadata = sa.MetaData()
STREAMS = ("tsetmc_coverage", "tsetmc_current", "tsetmc_daily", "tsetmc_status")


def scope() -> list[sa.Column[Any]]:
    return [
        sa.Column("ins_code", sa.Text, primary_key=True),
        sa.Column("source_epoch", UUID(as_uuid=True), primary_key=True),
    ]


datasets = sa.Table(
    "sync_datasets",
    metadata,
    sa.Column("ins_code", sa.Text, sa.ForeignKey(base.instruments.c.ins_code), primary_key=True),
    sa.Column("source_epoch", UUID(as_uuid=True), nullable=False, unique=True),
    sa.Column("installation_id", UUID(as_uuid=True), nullable=False),
    sa.Column("destination_id", UUID(as_uuid=True), nullable=False),
    sa.Column("producer_id", UUID(as_uuid=True), nullable=False),
    sa.Column("ownership_generation", sa.BigInteger, nullable=False),
    sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("enrolled", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("seed_id", UUID(as_uuid=True)),
    sa.UniqueConstraint("ins_code", "source_epoch"),
    sa.UniqueConstraint("ins_code", "source_epoch", "destination_id", "producer_id"),
    sa.CheckConstraint("ownership_generation > 0", name="sync_generation_positive"),
    sa.CheckConstraint("NOT enabled OR enrolled", name="sync_enrollment_required"),
    sa.CheckConstraint("enrolled = (seed_id IS NOT NULL)", name="sync_seed_required"),
)


def dataset_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["ins_code", "source_epoch"], [datasets.c.ins_code, datasets.c.source_epoch]
    )


clocks = sa.Table(
    "sync_stream_clocks",
    metadata,
    *scope(),
    sa.Column("stream", sa.Text, primary_key=True),
    sa.Column("head", sa.BigInteger, nullable=False, server_default="0"),
    sa.Column("acknowledged", sa.BigInteger, nullable=False, server_default="0"),
    sa.Column("used_rows", sa.BigInteger, nullable=False, server_default="0"),
    sa.Column("used_bytes", sa.BigInteger, nullable=False, server_default="0"),
    sa.Column("max_rows", sa.BigInteger, nullable=False, server_default="1000000"),
    sa.Column("max_bytes", sa.BigInteger, nullable=False, server_default="1073741824"),
    dataset_fk(),
    sa.CheckConstraint(
        "stream IN (" + ",".join(repr(v) for v in STREAMS) + ")", name="sync_stream_name"
    ),
    sa.CheckConstraint("0 <= acknowledged AND acknowledged <= head", name="sync_ack_prefix"),
    sa.CheckConstraint(
        "0 <= used_rows AND used_rows <= max_rows AND max_rows > 0 "
        "AND 0 <= used_bytes AND used_bytes <= max_bytes AND max_bytes > 0",
        name="sync_capacity",
    ),
)


def clock_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["ins_code", "source_epoch", "stream"],
        [clocks.c.ins_code, clocks.c.source_epoch, clocks.c.stream],
    )


outbox = sa.Table(
    "sync_outbox",
    metadata,
    *scope(),
    sa.Column("stream", sa.Text, primary_key=True),
    sa.Column("source_position", sa.BigInteger, primary_key=True),
    sa.Column("observation_id", UUID(as_uuid=True), nullable=False, unique=True),
    sa.Column("record", JSONB, nullable=False),
    sa.Column("record_bytes", sa.LargeBinary, nullable=False),
    sa.Column("record_sha256", sa.String(64), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    clock_fk(),
    sa.CheckConstraint(
        "stream IN ('tsetmc_daily','tsetmc_coverage') AND source_position > 0",
        name="sync_lossless_lane",
    ),
)
heads = sa.Table(
    "sync_daily_heads",
    metadata,
    *scope(),
    sa.Column("trading_date", sa.Date, primary_key=True),
    sa.Column("state_version", sa.BigInteger, nullable=False),
    sa.Column("semantic_sha256", sa.String(64), nullable=False),
    sa.Column("observation", JSONB, nullable=False),
    dataset_fk(),
    sa.ForeignKeyConstraint(
        ["ins_code", "trading_date"], [base.daily.c.ins_code, base.daily.c.trading_date]
    ),
    sa.CheckConstraint("state_version > 0", name="sync_day_version"),
)
latest = sa.Table(
    "sync_latest_pending",
    metadata,
    *scope(),
    sa.Column("stream", sa.Text, primary_key=True),
    sa.Column("version", sa.BigInteger, nullable=False),
    sa.Column("acknowledged_version", sa.BigInteger, nullable=False, server_default="0"),
    sa.Column("observation_id", UUID(as_uuid=True), nullable=False, unique=True),
    sa.Column("semantic_sha256", sa.String(64), nullable=False),
    sa.Column("record", JSONB, nullable=False),
    sa.Column("record_bytes", sa.LargeBinary, nullable=False),
    sa.Column("record_sha256", sa.String(64), nullable=False),
    clock_fk(),
    sa.CheckConstraint(
        "stream IN ('tsetmc_current','tsetmc_status') AND version > 0 "
        "AND 0 <= acknowledged_version AND acknowledged_version <= version",
        name="sync_latest_version",
    ),
)
evidence = sa.Table(
    "sync_evidence_refs",
    metadata,
    *scope(),
    sa.Column("local_observation_id", sa.BigInteger, primary_key=True),
    sa.Column("snapshot_id", sa.BigInteger),
    dataset_fk(),
    sa.ForeignKeyConstraint(
        ["local_observation_id", "ins_code"],
        [base.observations.c.observation_id, base.observations.c.ins_code],
    ),
    sa.ForeignKeyConstraint(
        ["snapshot_id", "ins_code"], [base.snapshots.c.snapshot_id, base.snapshots.c.ins_code]
    ),
)
batches = sa.Table(
    "sync_batches",
    metadata,
    sa.Column("destination_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("producer_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("batch_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("ins_code", sa.Text, nullable=False),
    sa.Column("source_epoch", UUID(as_uuid=True), nullable=False),
    sa.Column("stream", sa.Text, nullable=False),
    sa.Column("request_bytes", sa.LargeBinary, nullable=False),
    sa.Column("payload_sha256", sa.String(64), nullable=False),
    sa.Column("after_position", sa.BigInteger, nullable=False),
    sa.Column("through_position", sa.BigInteger, nullable=False),
    sa.Column("phase", sa.Text, nullable=False, server_default="staged"),
    sa.Column("receipt", JSONB),
    sa.Column("simulated", sa.Boolean, nullable=False, server_default=sa.true()),
    clock_fk(),
    sa.ForeignKeyConstraint(
        ["ins_code", "source_epoch", "destination_id", "producer_id"],
        [
            datasets.c.ins_code,
            datasets.c.source_epoch,
            datasets.c.destination_id,
            datasets.c.producer_id,
        ],
    ),
    sa.CheckConstraint(
        "simulated AND phase IN ('staged','received','acknowledged') "
        "AND 0 <= after_position AND after_position < through_position",
        name="sync_local_batch",
    ),
    sa.CheckConstraint("(phase = 'staged') = (receipt IS NULL)", name="sync_receipt_phase"),
)
sa.Index("sync_batch_pending", batches.c.ins_code, batches.c.stream, batches.c.phase)

# Composite relational scopes also agree with the immutable JSON identity.
for table, position in ((outbox, "source_position"), (latest, "version")):
    table.append_constraint(
        sa.CheckConstraint(
            "record->'observation'->>'ins_code' IS NOT NULL AND "
            "record->'observation'->>'ins_code'=ins_code AND "
            "record->>'observation_id'=observation_id::text AND "
            f"record->>'source_position'={position}::text AND "
            "record_sha256 ~ '^[0-9a-f]{64}$' AND octet_length(record_bytes)>0 AND "
            "convert_from(record_bytes,'UTF8')::jsonb=record",
            name=table.name + "_wire_identity",
        )
    )
heads.append_constraint(
    sa.CheckConstraint(
        "observation->>'ins_code' IS NOT NULL AND observation->>'ins_code'=ins_code AND "
        "observation->>'trading_date'=trading_date::text AND "
        "observation->>'state_version'=state_version::text",
        name="sync_head_wire_identity",
    )
)
batches.append_constraint(
    sa.CheckConstraint(
        "payload_sha256=encode(sha256(request_bytes),'hex') AND "
        "octet_length(request_bytes) BETWEEN 1 AND 2097152",
        name="sync_batch_byte_hash",
    )
)
