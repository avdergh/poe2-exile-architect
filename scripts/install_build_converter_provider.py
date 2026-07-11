"""Install the pinned Build Planner converter into writable user data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "providers" / "poe2-build-converter"
PROVIDER_ID = "praedythxiv-poe2-build-converter"
sys.path.insert(0, str(ROOT))

from server import paths  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        default=str(paths.user_data_dir() / "providers" / "poe2-build-converter"),
    )
    args = parser.parse_args()
    target = Path(args.target).resolve()
    staging = target.parent / f".{target.name}.{uuid4().hex}.tmp"
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        print(json.dumps({"status": "error", "errorCode": "npm_runtime_missing"}))
        return 1
    if target.exists() and not _replaceable_provider_dir(target):
        print(json.dumps({"status": "error", "errorCode": "provider_target_not_owned"}))
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    for name in (
        "package.json",
        "package-lock.json",
        "provider.json",
        "runner.ts",
        "README.md",
        "UPSTREAM_LICENSE.txt",
    ):
        shutil.copy2(SOURCE / name, staging / name)
    try:
        subprocess.run([npm, "ci"], cwd=staging, check=True, timeout=180)
        subprocess.run([npm, "run", "build"], cwd=staging, check=True, timeout=120)
        subprocess.run([npm, "audit", "--audit-level=high"], cwd=staging, check=True, timeout=60)
        subprocess.run([npm, "prune", "--omit=dev"], cwd=staging, check=True, timeout=120)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        shutil.rmtree(staging, ignore_errors=True)
        print(json.dumps({"status": "error", "errorCode": "provider_install_failed"}))
        return 1
    marker = json.loads((staging / "provider.json").read_text(encoding="utf-8"))
    license_path = staging / marker["licensePath"]
    runner_path = staging / marker["runnerPath"]
    if not license_path.is_file() or not runner_path.is_file():
        shutil.rmtree(staging, ignore_errors=True)
        print(json.dumps({"status": "error", "errorCode": "provider_install_incomplete"}))
        return 1
    if target.exists():
        shutil.rmtree(target)
    staging.replace(target)
    print(
        json.dumps(
            {
                "status": "installed",
                "providerId": marker["providerId"],
                "providerVersion": marker["providerVersion"],
                "providerCommit": marker["providerCommit"],
                "target": str(target),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _replaceable_provider_dir(target: Path) -> bool:
    marker_path = target / "provider.json"
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(marker, dict) and marker.get("providerId") == PROVIDER_ID


if __name__ == "__main__":
    raise SystemExit(main())
