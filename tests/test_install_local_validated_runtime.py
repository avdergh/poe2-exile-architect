from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

from server import paths
from scripts import install_local_validated_runtime as installer


CERTIFIED_COMMIT = "7d1aa43c8c938d7be150d197ed9cdec8a4c1c620"


def test_local_runtime_defaults_track_current_source_app_version():
    manifest = json.loads((installer.ROOT / "manifest.json").read_text(encoding="utf-8"))

    assert installer.DEFAULT_APP_VERSION == manifest["version"]
    assert installer.DEFAULT_VERSION == f"{manifest['version']}-local"


def make_runtime_source(root: Path, *, commit: str = CERTIFIED_COMMIT) -> None:
    (root / "data" / "compatibility").mkdir(parents=True)
    (root / "data" / "compatibility" / "pob.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "commit": commit,
                        "pob_version": "0.21.1-dev.20260625",
                        "game_patch": "0.5.4",
                        "passive_tree": "0_5",
                        "verified_by": ["golden-tests", "pob-dev-export"],
                        "verified_at": "2026-06-26T02:59:55Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "data").mkdir(exist_ok=True)
    (root / "data" / "corpus.sqlite").write_bytes(b"corpus")
    (root / "data" / "compatibility" / "corpus.json").write_text(json.dumps({
        "schemaVersion": 1, "sha256": hashlib.sha256(b"corpus").hexdigest(),
        "game_patch": "0.5.4", "passive_tree": "0_5",
    }), encoding="utf-8")
    (root / "pob" / "PathOfBuilding-PoE2" / "src").mkdir(parents=True)
    (root / "pob" / "PathOfBuilding-PoE2" / "runtime" / "lua").mkdir(parents=True)
    (root / "pob" / "PathOfBuilding-PoE2" / "src" / "Calc.lua").write_text("-- src")
    (root / "pob" / "PathOfBuilding-PoE2" / "src" / "Tree.png").write_bytes(b"art")
    (root / "pob" / "PathOfBuilding-PoE2" / "runtime" / "lua" / "dkjson.lua").write_text("-- lua")
    (root / "pob" / "pob_headless.lua").write_text("-- headless")
    (root / "pob" / "PINNED.md").write_text(f"| Pinned commit | `{commit}` |\n")


def test_install_local_runtime_copies_certified_engine_and_claims(tmp_path):
    root = tmp_path / "repo"
    target = tmp_path / "runtime"
    make_runtime_source(root)

    result = installer.install_local_runtime(
        root=root,
        target=target,
        version="0.1.39.1-local.20260626",
        app_version="0.1.39",
        pob_commit=CERTIFIED_COMMIT,
    )

    installed = json.loads((target / "installed.json").read_text())
    assert result["updated"] is True
    assert installed["version"] == "0.1.39.1-local.20260626"
    assert installed["app_version"] == "0.1.39"
    assert installed["engine_app_version"] == "0.1.39"
    assert installed["engine_contract"] == paths.POB_RUNTIME_CONTRACT
    assert installed["pob_commit"] == CERTIFIED_COMMIT
    assert installed["pob_version"] == "0.21.1-dev.20260625"
    assert installed["game_patch"] == "0.5.4"
    assert installed["passive_tree"] == "0_5"
    assert (target / "corpus.sqlite").read_bytes() == b"corpus"
    assert (target / "pob" / "pob_headless.lua").read_text() == "-- headless"
    assert (target / "pob" / "PathOfBuilding-PoE2" / "src" / "Calc.lua").exists()
    assert (target / "pob" / "PathOfBuilding-PoE2" / "runtime" / "lua" / "dkjson.lua").exists()
    assert not (target / "pob" / "PathOfBuilding-PoE2" / "src" / "Tree.png").exists()


def test_install_local_runtime_refuses_uncertified_commit(tmp_path):
    root = tmp_path / "repo"
    target = tmp_path / "runtime"
    make_runtime_source(root)

    with pytest.raises(installer.LocalRuntimeInstallError, match="not certified"):
        installer.install_local_runtime(
            root=root,
            target=target,
            version="0.1.39.1-local.20260626",
            app_version="0.1.39",
            pob_commit="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )


def test_install_local_runtime_refuses_repository_root_target(tmp_path):
    root = tmp_path / "repo"
    make_runtime_source(root)

    with pytest.raises(installer.LocalRuntimeInstallError, match="repository root"):
        installer.install_local_runtime(
            root=root,
            target=root,
            version="0.1.39.1-local.20260626",
            app_version="0.1.39",
            pob_commit=CERTIFIED_COMMIT,
        )


def test_cli_help_runs_from_repo_root():
    root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "scripts/install_local_validated_runtime.py", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--target" in result.stdout
