"""Explicit operator budgets and dated eligibility; disabled unless activated."""

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from tsetmc_marketdata.collection.sessions import Expectation, SessionEvidence, aware
from tsetmc_marketdata.config import Settings, validate_ins_code

JOBS = {"observe-current", "refresh-history", "reconcile-history", "audit-history"}


@dataclass(frozen=True)
class ScheduledJob:
    key: str
    job: str
    first_due: datetime
    interval: float
    source_limit: int = 20
    eligibility: str = "NOT_EXPECTED"
    provenance: str = ""

    def __post_init__(self) -> None:
        aware(self.first_due)
        if not self.key or len(self.key) > 80 or self.job not in JOBS:
            raise ValueError("invalid scheduled job identity")
        minimum = 30 if self.job == "observe-current" else 60
        if not math.isfinite(self.interval) or not minimum <= self.interval <= 31 * 86400:
            raise ValueError("schedule interval is outside conservative limits")
        if self.eligibility not in {"EXPECTED", "NOT_EXPECTED", "OPERATOR_WINDOW"}:
            raise ValueError("schedule eligibility must be explicit")
        if (
            not self.provenance.strip()
            or type(self.source_limit) is not int
            or not 1 <= self.source_limit <= 100000
        ):
            raise ValueError("schedule provenance and valid row limit are required")


@dataclass(frozen=True)
class ServiceConfig:
    ins_code: str
    start: datetime
    end: datetime
    jobs: tuple[ScheduledJob, ...]
    sessions: tuple[SessionEvidence, ...] = ()
    enabled: bool = False
    expected_instrument_id: str | None = None
    request_budget: int = 8
    max_jobs: int = 100
    catchup_per_turn: int = 1
    metadata_ttl: float = 900
    job_timeout: float = 180
    max_failures: int = 3
    http: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_ins_code(self.ins_code)
        if type(self.enabled) is not bool or any(
            type(v) is not int
            for v in (self.request_budget, self.max_jobs, self.catchup_per_turn, self.max_failures)
        ):
            raise ValueError("enabled must be boolean; budgets and failure bounds must be integers")
        length = (aware(self.end) - aware(self.start)).total_seconds()
        if not 0 < length <= 86400:
            raise ValueError("explicit operating window must be positive and at most one day")
        if len({j.key for j in self.jobs}) != len(self.jobs) or not 1 <= len(self.jobs) <= 10:
            raise ValueError("one to ten unique scheduled jobs are required")
        if sum(j.job == "observe-current" for j in self.jobs) > 1:
            raise ValueError("only one current-price schedule is permitted per instrument")
        if not 1 <= self.request_budget <= 10000 or not 1 <= self.max_jobs <= 10000:
            raise ValueError("explicit request and job budgets are required")
        if self.catchup_per_turn != 1 or not 1 <= self.max_failures <= 5:
            raise ValueError("catch-up is limited to one history job per turn; failures 1..5")
        if not 60 <= self.metadata_ttl <= 86400 or not 5 <= self.job_timeout <= 600:
            raise ValueError("metadata TTL or job timeout is outside validated limits")
        if any(e.ins_code != self.ins_code for e in self.sessions):
            raise ValueError("session evidence belongs to another instrument")
        if not isinstance(self.http, dict) or set(self.http) - Settings.__dataclass_fields__.keys():
            raise ValueError("unsupported HTTP configuration keys")
        if self.http.get("max_retries", 0) not in {0, 1, 2}:
            raise ValueError("service HTTP retries must be 0..2")
        Settings(**self.http)
        if self.http.get("pacing_seconds", 1) < 1:
            raise ValueError("scheduled service request pacing must be at least one second")

    def http_settings(self) -> Settings:
        settings = Settings(**{**asdict(Settings.from_env()), "max_retries": 0, **self.http})
        if settings.pacing_seconds < 1:
            raise ValueError("scheduled service request pacing must be at least one second")
        return settings


def _load(path: Path) -> ServiceConfig:
    raw = json.loads(path.read_text(encoding="utf8"))
    if not isinstance(raw, dict) or type(raw.get("enabled")) is not bool:
        raise ValueError("service configuration requires explicit enabled boolean")
    jobs = tuple(
        ScheduledJob(**{**j, "first_due": datetime.fromisoformat(j["first_due"])})
        for j in raw.pop("jobs", [])
    )
    sessions = tuple(
        SessionEvidence(
            **{
                **e,
                "start": datetime.fromisoformat(e["start"]),
                "end": datetime.fromisoformat(e["end"]),
                "expectation": Expectation(e["expectation"]),
            }
        )
        for e in raw.pop("sessions", [])
    )
    return ServiceConfig(
        **{
            **raw,
            "start": datetime.fromisoformat(raw["start"]),
            "end": datetime.fromisoformat(raw["end"]),
            "jobs": jobs,
            "sessions": sessions,
        }
    )


def load_service_config(path: Path) -> ServiceConfig:
    try:
        return _load(path)
    except (TypeError, KeyError, AttributeError) as exc:
        raise ValueError(
            "malformed service configuration; check required fields and types"
        ) from exc
