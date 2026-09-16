"""Report Ruff formatting differences as warnings without hiding execution errors."""

from __future__ import annotations

import shutil
import subprocess
import sys


def check_format(paths: list[str]) -> int:
    executable = shutil.which("ruff")
    if executable is None:
        print("::error title=Format check failed::Ruff was not found on PATH.", file=sys.stderr)
        return 2
    try:
        result = subprocess.run([executable, "format", "--check", *paths], check=False)
    except OSError:
        print("::error title=Format check failed::Could not start Ruff.", file=sys.stderr)
        return 2
    if result.returncode == 1:
        print(
            "::warning title=Formatting differences::Ruff found files that would be reformatted; "
            "formatting is advisory. No files were changed."
        )
        return 0
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(check_format(sys.argv[1:] or ["server", "scripts", "pipeline", "tests"]))
