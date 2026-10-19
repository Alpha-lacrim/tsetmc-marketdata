"""Small immutable configuration; no database or company configuration."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, fields
from urllib.parse import urlsplit

PILOT_INS_CODE = "46348559193224090"


def validate_ins_code(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{1,30}", value) is None:
        raise ValueError("insCode must be a string of ASCII digits")
    return value


def require_pilot(value: str) -> str:
    validate_ins_code(value)
    if value != PILOT_INS_CODE:
        raise ValueError("Milestone 1 permits only insCode 46348559193224090")
    return value


@dataclass(frozen=True)
class Settings:
    base_url: str = "https://cdn.tsetmc.com/api/"
    connect_timeout: float = 5
    read_timeout: float = 15
    write_timeout: float = 5
    pool_timeout: float = 5
    total_timeout: float = 90
    max_retries: int = 2
    pacing_seconds: float = 1
    backoff_seconds: float = 0.5
    max_backoff_seconds: float = 10

    def __post_init__(self) -> None:
        url = urlsplit(self.base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("base URL must be HTTP(S), without credentials, query or fragment")
        if not self.base_url.endswith("/"):
            raise ValueError("base URL must end with /")
        if type(self.max_retries) is not int or not 0 <= self.max_retries <= 5:
            raise ValueError("max_retries must be between 0 and 5")
        for field in fields(self):
            if field.name in {"base_url", "max_retries"}:
                continue
            value = getattr(self, field.name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{field.name} must be finite and nonnegative")
            if field.name.endswith("timeout") and value == 0:
                raise ValueError(f"{field.name} must be positive")

    @classmethod
    def from_env(cls) -> Settings:
        defaults = cls()
        values: dict[str, str | float | int] = {}
        for field in fields(cls):
            value = os.getenv(f"TSETMC_{field.name.upper()}")
            if value is not None:
                default = getattr(defaults, field.name)
                values[field.name] = type(default)(value)
        return cls(**values)  # type: ignore[arg-type]
