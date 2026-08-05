"""Start the self-contained Exile Architect MCP server from the installed plugin root."""

from __future__ import annotations

import json
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
for entry in (PLUGIN_ROOT / "lib", PLUGIN_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))


def _check() -> int:
    from server import paths

    checks = {
        "server": (PLUGIN_ROOT / "server" / "main.py").is_file(),
        "corpus": paths.corpus_path().is_file(),
        "researchSeed": paths.mature_learning_release_seed_path().is_file(),
        "graphSeed": paths.physical_graph_seed_manifest_path().is_file(),
        "pobSource": paths.pob_src_dir().is_dir(),
        "pobHeadless": paths.pob_headless_script().is_file(),
    }
    print(json.dumps({"ok": all(checks.values()), "checks": checks}, sort_keys=True))
    return 0 if all(checks.values()) else 1


def main() -> int:
    if "--check" in sys.argv[1:]:
        return _check()
    from server.main import main as run_server

    run_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
