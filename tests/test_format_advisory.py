from __future__ import annotations

import pytest

from scripts import check_format_advisory


@pytest.mark.parametrize(
    ("source", "expected_exit", "warning"),
    [
        ("value = 1\n", 0, False),
        ("value=1\n", 0, True),
        ("def broken(\n", 2, False),
    ],
    ids=["formatted", "formatting-differences", "invalid-python"],
)
def test_format_advisory_preserves_files_and_execution_errors(
    tmp_path, capfd, source, expected_exit, warning
):
    path = tmp_path / "example.py"
    path.write_text(source, encoding="utf-8")
    before = path.read_bytes()

    assert check_format_advisory.check_format([str(path)]) == expected_exit

    output = capfd.readouterr()
    assert ("::warning" in output.out) is warning
    assert path.read_bytes() == before


def test_missing_formatter_is_an_error(monkeypatch, capsys):
    monkeypatch.setattr(check_format_advisory.shutil, "which", lambda _name: None)

    assert check_format_advisory.check_format(["server"]) == 2
    assert "::error" in capsys.readouterr().err


def test_formatter_start_failure_is_an_error(monkeypatch, capsys):
    monkeypatch.setattr(check_format_advisory.shutil, "which", lambda _name: "ruff")

    def denied(*args, **kwargs):
        raise PermissionError("not executable")

    monkeypatch.setattr(check_format_advisory.subprocess, "run", denied)

    assert check_format_advisory.check_format(["server"]) == 2
    assert "::error" in capsys.readouterr().err
