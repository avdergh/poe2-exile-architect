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
    assert "scripts/validate_mcpb_manifest.py" in script
    assert "& npx" not in script
    assert "tests/test_lifecycle.py" in script
    assert "tests/test_server.py" in script
    assert "--ignore=tests/test_compute.py" in script
    assert "tests/test_compute.py" in script
    full_block = script.split('"full" {', maxsplit=1)[1].split('"lint" {', maxsplit=1)[0]
    assert "--ignore=tests/test_compute.py" in full_block
    assert "ComputePytestTimeoutSeconds" not in full_block


def test_format_checks_are_advisory_but_lint_remains_blocking():
    script = Path("scripts/verify.ps1").read_text(encoding="utf-8")

    assert 'Invoke-Uv "ruff check"' in script
    assert 'Invoke-UvAdvisory "ruff format --check"' in script
    assert "formatting is advisory" in script
    for workflow in ("ci.yml", "release.yml"):
        content = Path(".github", "workflows", workflow).read_text(encoding="utf-8")
        assert "uv run ruff check server scripts pipeline tests" in content
        format_block = content.split("- name: Format advisory", maxsplit=1)[1]
        assert "continue-on-error: true" in format_block
        assert "uv run ruff format --check server scripts pipeline tests" in format_block


def test_compute_profile_documents_long_runtime_timeout_budget():
    script = Path("scripts/verify.ps1").read_text(encoding="utf-8")

    assert "$ComputePytestTimeoutSeconds = 1800" in script
    assert "$ComputeMinimumOuterTimeoutMs = 1800000" in script
    assert "--timeout=$ComputePytestTimeoutSeconds" in script
