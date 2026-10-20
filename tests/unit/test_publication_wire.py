"""Published synthetic specification, exact hashes and invalid wire boundaries."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from tsetmc_marketdata.storage.publication_wire import (
    decode,
    encode,
    financial_hash,
    record_sha,
    validate,
)

DIRECTORY = Path(__file__).parents[2] / "docs/contracts/milestone3b"
MANIFEST = json.loads((DIRECTORY / "examples-manifest.json").read_text())


@pytest.mark.parametrize("entry", MANIFEST["examples"], ids=lambda e: e["file"])
def test_published_synthetic_contract(entry):
    body = (DIRECTORY / entry["file"]).read_bytes()
    assert hashlib.sha256(body).hexdigest() == entry["sha256"]
    value = decode(body)
    validate(value, entry["definition"])
    if entry["definition"] == "Batch":
        for record in value["records"]:
            assert len(record_sha(record)) == 64
            if "measurements" in record["observation"]:
                assert (
                    financial_hash(record["observation"]) == record["observation"]["financial_hash"]
                )


@pytest.mark.parametrize(
    "case",
    [
        "number",
        "scale",
        "exponent",
        "hash",
        "count",
        "unknown",
        "identity",
        "position",
        "epoch",
        "generation",
        "finality",
        "clock",
        "review",
        "range",
    ],
)
def test_invalid_batch_is_rejected(case):
    value = copy.deepcopy(decode((DIRECTORY / "examples/confirmation.request.json").read_bytes()))
    record = value["records"][0]
    observation = record["observation"]
    mutations = {
        "number": lambda: observation["measurements"].update(official_close=112),
        "scale": lambda: observation["measurements"].update(official_close="112.0"),
        "exponent": lambda: observation["measurements"].update(official_close="1e2"),
        "hash": lambda: observation.update(financial_hash="0" * 64),
        "count": lambda: observation["measurements"].update(trade_count="1.1"),
        "unknown": lambda: value.update(secret="synthetic"),
        "identity": lambda: observation.update(ins_code="900000000000000002"),
        "position": lambda: record.update(source_position=str(2**63)),
        "epoch": lambda: value.update(source_epoch="10000000-0000-4000-8000-000000000002"),
        "generation": lambda: value.update(session_generation=True),
        "finality": lambda: observation.update(upstream_finality="source_finalized"),
        "clock": lambda: observation["source"].update(received_at="2026-03-21T10:00:00"),
        "review": lambda: observation["review"].update(reviewed_financial_hash="0" * 64),
        "range": lambda: observation["measurements"].update(high="1"),
    }
    mutations[case]()
    with pytest.raises(ValueError):
        validate(value, "Batch")


@pytest.mark.parametrize("body", [b'{"x":1,"x":2}', b'{"x":1.0}', b'{"x":NaN}', b"[]", b"bad"])
def test_unsafe_json_rejected(body):
    with pytest.raises(ValueError):
        decode(body)


def test_record_hash_excludes_envelope_but_includes_quality():
    batch = decode((DIRECTORY / "examples/daily.request.json").read_bytes())
    record = batch["records"][0]
    original = record_sha(record)
    batch["session_generation"] = 2
    assert record_sha(record) == original
    record["observation"]["reconciliation"]["open_quarantine_count"] = 1
    assert record_sha(record) != original
    assert (
        encode({"price": "100.12345678901234567890123456789"})
        == b'{"price":"100.12345678901234567890123456789"}'
    )


@pytest.mark.parametrize(
    "case", ["calendar", "source_clock", "correction_reason", "current_version", "repeat_update"]
)
def test_current_cross_field_rules(case):
    value = decode((DIRECTORY / "examples/current.request.json").read_bytes())
    observation = value["records"][0]["observation"]
    if case == "calendar":
        observation["source"]["received_at"] = "2026-02-30T09:00:00Z"
    elif case == "source_clock":
        observation["source_reported_at"] = "2026-03-22T10:00:00Z"
    elif case == "correction_reason":
        observation["accepted_decision"] = "explicit_same_time_correction"
    elif case == "current_version":
        observation["state_version"] = "2"
    else:
        observation.update(accepted_decision="repeated_state", financial_change=False)
    with pytest.raises(ValueError):
        validate(value, "Batch")
