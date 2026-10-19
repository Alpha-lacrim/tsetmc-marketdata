import io
import json
import socket
from pathlib import Path

import pytest

from tsetmc_marketdata.cli import main

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_offline_cli_export(tmp_path, capsys):
    output = tmp_path / "chart.json"
    assert (
        main(
            [
                "export-chartdata",
                "--input",
                str(FIXTURES / "synthetic-history.json"),
                "--output",
                str(output),
                "--legacy-sample",
            ]
        )
        == 0
    )
    chart = json.loads(output.read_text())
    assert list(chart) == list("abcdefghi") and chart["i"] is None
    assert chart["f"] == [2345, 1234] and chart["g"][-1] == 7000000123
    assert "unknown_activity_zero_placeholders" in capsys.readouterr().out


@pytest.mark.parametrize(
    "command,fixture,expected",
    [
        ("probe-history", "synthetic-history.json", "valid_records"),
        ("probe-current", "synthetic-current.json", "source_reported_at"),
        ("probe-instrument", "synthetic-instrument.json", "symbol"),
        ("inspect-fields", "synthetic-history.json", "fields"),
    ],
)
def test_offline_probes(command, fixture, expected, capsys):
    assert main([command, "--input", str(FIXTURES / fixture)]) == 0
    assert expected in json.loads(capsys.readouterr().out)


def test_partial_history_requires_explicit_export(tmp_path, capsys):
    payload = json.loads((FIXTURES / "synthetic-history.json").read_text())
    payload["closingPriceDaily"].append({"bad": True})
    source, output = tmp_path / "source.json", tmp_path / "chart.json"
    source.write_text(json.dumps(payload))
    args = ["export-chartdata", "--input", str(source), "--output", str(output)]
    assert main(args) == 2 and not output.exists()
    assert main(args + ["--allow-partial"]) == 0
    assert len(json.loads(output.read_text())["a"]) == 2


def test_error_report_and_invalid_source(tmp_path, capsys):
    source, report = tmp_path / "bad.json", tmp_path / "report.json"
    source.write_text("not json")
    assert main(["probe-history", "--input", str(source), "--report", str(report)]) == 1
    assert json.loads(report.read_text())["error"] == "invalid_json"
    assert "invalid_json" in capsys.readouterr().err


def test_cli_pilot_only(capsys):
    assert main(["probe-current", "--ins-code", "123"]) == 1
    assert "Milestone 1" in capsys.readouterr().err


def test_offline_raw_copy_has_no_fabricated_receipt(tmp_path):
    source = FIXTURES / "synthetic-current.json"
    target = tmp_path / "copy.json"
    assert main(["probe-current", "--input", str(source), "--raw-output", str(target)]) == 0
    assert target.read_bytes() == source.read_bytes()
    assert json.loads(target.with_suffix(".json.metadata.json").read_text())["received_at"] is None


def test_external_dns_blocked():
    with pytest.raises(AssertionError, match="offline"):
        socket.getaddrinfo("cdn.tsetmc.com", 443)


def test_dated_cli_offline(capsys):
    source = FIXTURES / "synthetic-daily.json"
    assert main(["probe-daily", "--date", "20260321", "--input", str(source)]) == 0
    assert json.loads(capsys.readouterr().out)["table_14_columns"]["opening_price"] == "1010.25"


def test_persian_diagnostics_on_windows_legacy_encoding(monkeypatch):
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="cp1252")
    monkeypatch.setattr("sys.stdout", stream)
    assert main(["probe-instrument", "--input", str(FIXTURES / "synthetic-instrument.json")]) == 0
    stream.flush()
    assert json.loads(buffer.getvalue().decode("cp1252"))["symbol"] == "فولاد"
