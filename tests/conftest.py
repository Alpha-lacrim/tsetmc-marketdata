"""Default tests cannot open network sockets (pytest-socket in pyproject.toml)."""

import socket
from pathlib import Path

import pytest

from tsetmc_marketdata.jsonio import loads_source


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", help="explicitly opt into bounded live tests")
    parser.addoption(
        "--postgres", action="store_true", help="use disposable local PostgreSQL databases"
    )


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "postgres" in item.keywords and not config.getoption("--postgres"):
            item.add_marker(pytest.mark.skip(reason="PostgreSQL integration requires --postgres"))
        elif "postgres" in item.keywords:
            item.add_marker(pytest.mark.allow_hosts(["127.0.0.1", "::1", "postgres"]))
        if "live" in item.keywords and not config.getoption("--live"):
            item.add_marker(pytest.mark.skip(reason="live API tests require explicit --live"))
        elif "live" in item.keywords:
            item.add_marker(pytest.mark.allow_hosts(["127.0.0.1", "::1", "cdn.tsetmc.com"]))


@pytest.fixture(autouse=True)
def block_external_dns(request, monkeypatch):
    if request.node.get_closest_marker("live") and request.config.getoption("--live"):
        return
    original = socket.getaddrinfo

    def guarded(host, *args, **kwargs):
        local = {"127.0.0.1", "::1", "localhost", None}
        if request.node.get_closest_marker("postgres") and request.config.getoption("--postgres"):
            local.add("postgres")
        if host not in local:
            raise AssertionError("external DNS/network access forbidden in offline tests")
        return original(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded)


@pytest.fixture
def history_payload():
    return loads_source((Path(__file__).parent / "fixtures/synthetic-history.json").read_bytes())


@pytest.fixture
def daily_raw(history_payload):
    return history_payload["closingPriceDaily"][0]


@pytest.fixture
def current_payload():
    return loads_source((Path(__file__).parent / "fixtures/synthetic-current.json").read_bytes())


@pytest.fixture
def instrument_payload():
    return loads_source((Path(__file__).parent / "fixtures/synthetic-instrument.json").read_bytes())
