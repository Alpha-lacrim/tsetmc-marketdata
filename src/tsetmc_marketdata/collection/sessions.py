"""Dated session evidence, never a guessed exchange holiday calendar."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from tsetmc_marketdata.config import validate_ins_code


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("an explicit aware instant is required")
    return value.astimezone(UTC)


class Expectation(StrEnum):
    EXPECTED = "EXPECTED"
    NOT_EXPECTED = "NOT_EXPECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SessionEvidence:
    ins_code: str
    start: datetime
    end: datetime
    expectation: Expectation
    provenance: str
    confidence: str = "operator"
    priority: int = 0

    def __post_init__(self) -> None:
        validate_ins_code(self.ins_code)
        if aware(self.end) <= aware(self.start) or not self.provenance.strip():
            raise ValueError("session evidence requires a positive window and provenance")
        if self.confidence not in {"operator", "verified_rule", "source_state"}:
            raise ValueError("unsupported evidence confidence")


@dataclass(frozen=True)
class SessionDecision:
    expectation: Expectation
    confidence: str
    provenance: tuple[str, ...]


def session_expectation(
    now: datetime, ins_code: str, evidence: tuple[SessionEvidence, ...] = ()
) -> SessionDecision:
    now = aware(now)
    active = [
        e for e in evidence if e.ins_code == ins_code and aware(e.start) <= now < aware(e.end)
    ]
    if not active:
        return SessionDecision(Expectation.UNKNOWN, "unqualified", ())
    priority = max(e.priority for e in active)
    selected = [e for e in active if e.priority == priority]
    if len({e.expectation for e in selected}) != 1:
        return SessionDecision(
            Expectation.UNKNOWN, "conflicting_evidence", tuple(e.provenance for e in selected)
        )
    return SessionDecision(
        selected[0].expectation, selected[0].confidence, tuple(e.provenance for e in selected)
    )
