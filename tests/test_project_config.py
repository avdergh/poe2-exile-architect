from __future__ import annotations

import tomllib
from pathlib import Path


def test_pytest_timeout_is_enabled_for_certification_gate():
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    pytest_options = config["tool"]["pytest"]["ini_options"]
    assert pytest_options["timeout"] == 300
