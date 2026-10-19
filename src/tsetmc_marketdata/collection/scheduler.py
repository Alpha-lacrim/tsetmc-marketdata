"""Explicit bounded manual operating windows; no inferred exchange holiday calendar."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from tsetmc_marketdata.errors import ErrorKind, TSETMCError


class Clock(Protocol):
    def now(self) -> datetime: ...
    async def sleep(self, seconds: float) -> None: ...
    def monotonic(self) -> float: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


@dataclass(frozen=True)
class PollPolicy:
    until: datetime
    interval: float = 30
    max_failures: int = 3

    def __post_init__(self) -> None:
        if self.until.tzinfo is None or self.until.utcoffset() is None:
            raise ValueError("polling window requires an aware instant")
        if not 30 <= self.interval <= 3600 or not 1 <= self.max_failures <= 5:
            raise ValueError("poll interval is 30..3600 seconds; failure bound is 1..5")


async def poll(
    job: Callable[[], Awaitable[dict[str, Any]]], policy: PollPolicy, *, clock: Clock | None = None
) -> dict[str, Any]:
    clock = clock or SystemClock()
    failures, observations = 0, 0
    if policy.until - clock.now() > timedelta(days=1):
        raise ValueError("manual polling window cannot exceed one day")
    while clock.now() < policy.until:
        delay = policy.interval
        try:
            await job()
            observations += 1
            failures = 0
        except TSETMCError as exc:
            failures += 1
            if exc.kind == ErrorKind.ACCESS_DENIED or failures >= policy.max_failures:
                return {
                    "status": "stopped",
                    "observations": observations,
                    "failure_category": exc.kind.value,
                }
            delay = min(300, policy.interval * 2**failures)
        remaining = (policy.until - clock.now()).total_seconds()
        if remaining > 0:
            await clock.sleep(min(delay, remaining))
    return {
        "status": "manual_window_ended",
        "observations": observations,
        "market_session_claimed": False,
    }
