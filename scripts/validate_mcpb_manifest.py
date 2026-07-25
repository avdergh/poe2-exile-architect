"""Validate manifest.json with an available host Node package runner."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.runtime.node import (  # noqa: E402
    resolve_node_executable,
    resolve_package_runner,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", nargs="?", default="manifest.json")
    args = parser.parse_args()
    manifest = Path(args.manifest).resolve()
    if not manifest.is_file():
        return _error("manifest_missing", manifest=str(manifest))

    node = resolve_node_executable()
    if node is None:
        return _error("node_runtime_missing")
    runner = resolve_package_runner(node_executable=node)
    if runner is None:
        return _error("node_package_runner_missing")

    runner_args = (
        ["--yes", "@anthropic-ai/mcpb", "validate", str(manifest)]
        if runner.kind == "npx"
        else ["dlx", "@anthropic-ai/mcpb", "validate", str(manifest)]
    )
    command = _platform_command(runner.executable, runner_args)
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(node.parent), env.get("PATH", "")]).rstrip(os.pathsep)
    try:
        completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    except OSError:
        return _error(
            "manifest_validator_launch_failed",
            runnerKind=runner.kind,
        )
    return completed.returncode


def _platform_command(executable: Path, args: list[str]) -> list[str]:
    if os.name != "nt" or executable.suffix.lower() not in {".cmd", ".bat"}:
        return [str(executable), *args]
    command_shell = os.environ.get("COMSPEC") or shutil.which("cmd.exe")
    if not command_shell:
        return [str(executable), *args]
    return [
        command_shell,
        "/d",
        "/s",
        "/c",
        subprocess.list2cmdline([str(executable), *args]),
    ]


def _error(error_code: str, **details: str) -> int:
    print(
        json.dumps(
            {"status": "error", "errorCode": error_code, **details},
            ensure_ascii=False,
        )
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
