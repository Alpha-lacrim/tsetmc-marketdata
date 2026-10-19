"""Safe errors: diagnostics never include headers, response bodies, or full URLs."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorKind(StrEnum):
    NETWORK = "network_failure"
    DNS = "dns_failure"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limited"
    ACCESS_DENIED = "access_denied"
    SERVER = "http_5xx"
    HTTP = "http_error"
    INVALID_JSON = "invalid_json"
    SCHEMA = "unexpected_schema"
    NOT_FOUND = "instrument_not_found"
    INVALID_RECORD = "invalid_record"


class TSETMCError(Exception):
    def __init__(
        self, kind: ErrorKind, message: str, *, status: int | None = None, attempts: int = 1
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.attempts = attempts

    def as_dict(self) -> dict[str, Any]:
        return {
            "error": self.kind.value,
            "message": str(self),
            "status": self.status,
            "attempts": self.attempts,
        }


class TransportError(TSETMCError):
    """Connection or HTTP status failure; retry policy belongs to transport."""


class SourceDataError(TSETMCError):
    """Response received but JSON/schema/financial measurements are unusable."""


class RecordError(SourceDataError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorKind.INVALID_RECORD, message)
