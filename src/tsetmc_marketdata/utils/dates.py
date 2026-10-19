"""Daily labels use UTC midnight, never receipt time or a presumed market open."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import jdatetime

TEHRAN = ZoneInfo("Asia/Tehran")


def parse_source_date(value: object) -> date:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("dEven must be Gregorian YYYYMMDD")
    text = str(value)
    if re.fullmatch(r"[0-9]{8}", text) is None:
        raise ValueError("dEven must be Gregorian YYYYMMDD")
    return date(int(text[:4]), int(text[4:6]), int(text[6:]))


def parse_source_time(value: object) -> time:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("hEven must be HHMMSS")
    text = str(value)
    if re.fullmatch(r"[0-9]{1,6}", text) is None:
        raise ValueError("hEven must be HHMMSS")
    number = int(text)
    return time(number // 10000, number // 100 % 100, number % 100)


def source_instant(day: date, source_time: time) -> datetime:
    """Interpret a source-reported local clock, not a proven trade timestamp.

    Reject historical ambiguous/nonexistent clocks instead of choosing a DST fold.
    """
    candidate = datetime.combine(day, source_time, tzinfo=TEHRAN)
    other = candidate.replace(fold=1)
    if candidate.utcoffset() != other.utcoffset():
        raise ValueError("ambiguous or nonexistent Tehran source clock")
    return candidate.astimezone(UTC)


def daily_unix_seconds(day: date) -> int:
    if isinstance(day, datetime):
        raise ValueError("daily candle requires a trading date, not an instant")
    return int(datetime.combine(day, time.min, tzinfo=UTC).timestamp())


def gregorian_to_jalali(day: date) -> str:
    return str(jdatetime.date.fromgregorian(date=day).strftime("%Y-%m-%d"))


def jalali_to_gregorian(value: str) -> date:
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError("Jalali date must be YYYY-MM-DD")
    year, month, day = map(int, value.split("-"))
    result: date = jdatetime.date(year, month, day).togregorian()
    return result


def calendar_gaps(days: list[date]) -> list[tuple[date, date, int]]:
    """Unobserved date ranges, not claims about missing trading sessions."""
    ordered = sorted(set(days))
    return [
        (a + timedelta(days=1), b - timedelta(days=1), (b - a).days - 1)
        for a, b in zip(ordered, ordered[1:], strict=False)
        if (b - a).days > 1
    ]
