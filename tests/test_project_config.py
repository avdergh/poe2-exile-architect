from __future__ import annotations

import tomllib
from pathlib import Path


def test_pytest_timeout_is_enabled_for_certification_gate():
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    pytest_options = config["tool"]["pytest"]["ini_options"]
    assert pytest_options["timeout"] == 300


def test_verification_script_exposes_layered_profiles():
    script = Path("scripts/verify.ps1").read_text(encoding="utf-8")

    assert 'ValidateSet("quick", "noncompute", "compute", "full", "lint")' in script
    assert "tests/test_lifecycle.py" in script
    assert "tests/test_server.py" in script
    assert "--ignore=tests/test_compute.py" in script
    assert "tests/test_compute.py" in script
