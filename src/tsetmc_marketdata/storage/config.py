"""Local-only database configuration. URLs and database errors are never logged verbatim."""

import os
import re
from dataclasses import dataclass, field

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


class StorageError(Exception):
    category = "postgres_write_failure"


class SchemaError(StorageError):
    category = "schema_incompatible"


class OwnershipError(StorageError):
    category = "collector_already_owned"


@dataclass(frozen=True)
class DatabaseSettings:
    url: str = field(repr=False)

    def validated_url(self) -> URL:
        try:
            url = make_url(self.url)
        except (ValueError, ArgumentError):
            # SQLAlchemy's URL parser can include the original input in its exception text.
            raise ValueError("invalid database URL; value withheld") from None
        if (
            url.drivername != "postgresql+asyncpg"
            or url.host not in {"127.0.0.1", "localhost", "::1", "postgres"}
            or not url.database
            or not (
                url.database == "tsetmc_marketdata"
                or re.fullmatch(r"tsetmc_test_[a-f0-9]+", url.database)
            )
            or not url.username
            or not url.username.startswith("tsetmc_")
        ):
            raise ValueError("database must be an independent local TSETMC PostgreSQL database")
        return url

    @classmethod
    def from_env(cls, *, migration: bool = False) -> "DatabaseSettings":
        name = "TSETMC_MIGRATION_URL" if migration else "TSETMC_DATABASE_URL"
        value = os.getenv(name)
        if not value:
            raise ValueError(f"{name} is required; no database is selected implicitly")
        settings = cls(value)
        settings.validated_url()
        return settings
