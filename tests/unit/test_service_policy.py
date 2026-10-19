"""Synthetic calendar, freshness and budget policies; no live source claims."""

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from tsetmc_marketdata.cli import main
from tsetmc_marketdata.collection.budget import BudgetSource, RequestBudgetError
from tsetmc_marketdata.collection.service import eligible
from tsetmc_marketdata.collection.service_config import (
    ScheduledJob,
    ServiceConfig,
    load_service_config,
)
from tsetmc_marketdata.collection.sessions import (
    Expectation,
    SessionEvidence,
    aware,
    session_expectation,
)
from tsetmc_marketdata.storage.health import age, freshness
from tsetmc_marketdata.utils.dates import TEHRAN, gregorian_to_jalali, jalali_to_gregorian

CODE = "900000000000000001"
NOW = datetime(2026, 3, 21, 10, tzinfo=UTC)


@pytest.mark.parametrize(
    "expectation,expected",
    [
        (Expectation.EXPECTED, "unexpectedly_stale"),
        (Expectation.NOT_EXPECTED, "unchanged_updates_not_expected"),
        (Expectation.UNKNOWN, "stale_session_unknown"),
    ],
)
def test_freshness_context_distinguishes_connection_from_source(expectation, expected):
    assert freshness(3600, expectation, 180) == expected
    assert freshness(10, expectation, 180) == "recent_source_observation"
    assert freshness(None, expectation, 180) == "unknown_source_time"
    assert freshness(-1, expectation, 180) == "source_clock_ahead"
    assert age(NOW, NOW - timedelta(seconds=1)) == 1
    assert age(NOW, None) is None


def test_session_open_close_exception_unknown_and_instrument_isolation():
    active = SessionEvidence(
        CODE, NOW, NOW + timedelta(hours=1), Expectation.EXPECTED, "Invented session evidence"
    )
    holiday = replace(
        active,
        expectation=Expectation.NOT_EXPECTED,
        priority=10,
        provenance="Invented exceptional closure",
    )
    assert (
        session_expectation(NOW - timedelta(seconds=1), CODE, (active,)).expectation
        == Expectation.UNKNOWN
    )
    assert session_expectation(NOW, CODE, (active,)).expectation == Expectation.EXPECTED
    assert (
        session_expectation(NOW + timedelta(hours=1), CODE, (active,)).expectation
        == Expectation.UNKNOWN
    )
    assert session_expectation(NOW, CODE, (active, holiday)).expectation == Expectation.NOT_EXPECTED
    assert (
        session_expectation(NOW, CODE, (active, replace(holiday, priority=0))).expectation
        == Expectation.UNKNOWN
    )
    assert (
        session_expectation(NOW, "900000000000000002", (active,)).expectation == Expectation.UNKNOWN
    )


@pytest.mark.parametrize(
    "day", [date(2025, 12, 31), date(2026, 1, 1), date(2026, 3, 20), date(2026, 3, 21)]
)
def test_dated_policy_crosses_calendar_years_without_guessing_sessions(day):
    assert jalali_to_gregorian(gregorian_to_jalali(day)) == day
    instant = datetime(day.year, day.month, day.day, 9, tzinfo=TEHRAN)
    assert aware(instant).astimezone(TEHRAN) == instant
    assert session_expectation(instant, CODE).expectation == Expectation.UNKNOWN


def test_current_tehran_offset_does_not_replace_historical_rules():
    assert datetime(2026, 7, 1, tzinfo=TEHRAN).utcoffset() == timedelta(hours=3, minutes=30)
    assert datetime(2021, 7, 1, tzinfo=TEHRAN).utcoffset() == timedelta(hours=4, minutes=30)
    with pytest.raises(ValueError, match="aware"):
        aware(datetime(2026, 1, 1))


@pytest.mark.parametrize("expectation", list(Expectation))
def test_manual_observation_does_not_override_confirmed_closure(expectation):
    job = ScheduledJob(
        "test",
        "observe-current",
        NOW,
        30,
        eligibility="OPERATOR_WINDOW",
        provenance="Explicit synthetic approval",
    )
    assert eligible(job, expectation) == (expectation != Expectation.NOT_EXPECTED)
    assert eligible(replace(job, eligibility="EXPECTED"), expectation) == (
        expectation == Expectation.EXPECTED
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"request_budget": 0},
        {"request_budget": True},
        {"max_jobs": 1.5},
        {"catchup_per_turn": 2},
        {"metadata_ttl": 0},
        {"http": {"max_retries": 3}},
        {"http": {"pacing_seconds": 0}},
        {"end": NOW + timedelta(days=2)},
        {"enabled": 1},
        {"http": {"unknown": True}},
        {"http": []},
    ],
)
def test_service_limits_are_explicit_and_conservative(changes):
    job = ScheduledJob("test", "observe-current", NOW, 30, provenance="synthetic")
    config = ServiceConfig(CODE, NOW, NOW + timedelta(hours=1), (job,))
    assert not config.enabled
    with pytest.raises((ValueError, TypeError)):
        replace(config, **changes)


def test_disabled_example_and_cli_validation_do_not_connect_to_db(capsys):
    assert main(["validate-collector-config", "--config", "config/collector.example.json"]) == 0
    assert json.loads(capsys.readouterr().out)["enabled"] is False
    assert main(["run-collector", "--config", "config/collector.example.json"]) == 1
    assert "--activate" in capsys.readouterr().err


def test_environment_cannot_weaken_scheduled_request_pacing(monkeypatch):
    job = ScheduledJob("test", "observe-current", NOW, 30, provenance="synthetic")
    config = ServiceConfig(CODE, NOW, NOW + timedelta(hours=1), (job,))
    monkeypatch.setenv("TSETMC_PACING_SECONDS", "0")
    with pytest.raises(ValueError, match="pacing"):
        config.http_settings()
    assert replace(config, http={"pacing_seconds": 2}).http_settings().pacing_seconds == 2
    monkeypatch.setenv("TSETMC_PACING_SECONDS", "3")
    assert config.http_settings().pacing_seconds == 3
    assert config.http_settings().max_retries == 0


@pytest.mark.parametrize(
    "bad", [{}, {"enabled": True, "jobs": [{"unknown": 1}]}, {"enabled": "yes"}]
)
def test_config_schema_errors_are_clear(tmp_path, bad):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        load_service_config(path)


async def test_request_budget_enforces_identity_and_captures_failures(tmp_path):
    from tsetmc_marketdata.errors import ErrorKind, TransportError

    class FailingSource:
        calls = 0

        async def get_json(self, path):
            self.calls += 1
            raise TransportError(ErrorKind.ACCESS_DENIED, "synthetic denial", status=403)

    upstream = FailingSource()
    source = BudgetSource(upstream, CODE, 1, tmp_path)
    with pytest.raises(ValueError, match="scope"):
        await source.get_json("ClosingPrice/GetClosingPriceInfo/900000000000000002")
    with pytest.raises(TransportError):
        await source.get_json(f"ClosingPrice/GetClosingPriceInfo/{CODE}")
    with pytest.raises(RequestBudgetError):
        await source.get_json(f"ClosingPrice/GetClosingPriceInfo/{CODE}")
    assert upstream.calls == 1 and source.requests == 1
    assert json.loads((tmp_path / "events.jsonl").read_text())["error"] == "access_denied"
    with pytest.raises(ValueError, match="new or empty"):
        BudgetSource(upstream, CODE, 1, tmp_path)
