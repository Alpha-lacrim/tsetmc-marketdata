"""Conservative source-position ordering. A new receipt is not a new trade."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tsetmc_marketdata.models.current import CurrentPrice


@dataclass(frozen=True)
class LatestDecision:
    update: bool
    state_change: bool
    code: str
    review: bool = False


def choose_latest(
    old: Mapping[str, Any] | None,
    new: CurrentPrice,
    new_hash: str,
    *,
    correction_reason: str | None = None,
) -> LatestDecision:
    if old is None:
        return LatestDecision(True, True, "initial_observation")
    same = old["financial_hash"] == new_hash
    old_day, day = old["source_date"], new.source_date
    old_time, clock = old["source_time"], new.source_time
    if old_day is not None and day is not None and day != old_day:
        return LatestDecision(
            day > old_day,
            day > old_day and not same,
            "newer_session" if day > old_day else "older_session",
        )
    if day is None or old_day is None or clock is None or old_time is None:
        if same and day is not None and clock is not None and old_day in (None, day):
            return LatestDecision(True, False, "same_state_more_precise_position")
        return LatestDecision(False, False, "unknown_source_position", not same)
    if clock != old_time:
        return LatestDecision(
            clock > old_time,
            clock > old_time and not same,
            "newer_source_clock" if clock > old_time else "older_source_clock",
        )
    if same:
        newer_receipt = new.received_at is not None and new.received_at >= old["received_at"]
        return LatestDecision(newer_receipt, False, "repeated_state")
    if correction_reason and correction_reason.strip():
        return LatestDecision(True, True, "explicit_same_time_correction")
    return LatestDecision(False, False, "same_timestamp_conflict", True)
