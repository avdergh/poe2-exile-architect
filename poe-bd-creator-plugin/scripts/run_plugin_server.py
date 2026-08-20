"""Start self-contained Exile Architect MCP servers or the Research CLI.

With no ``--server`` argument this runs the legacy aggregate ``server.main`` entry (backwards
compatible with old host configurations). With ``--server <domain>`` it runs one of the four
split domain servers: knowledge / build / research / learning. ``--research-cli`` reuses the
same packaged Python runtime for the internal Research Controller/Worker command surface.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
for entry in (PLUGIN_ROOT / "lib", PLUGIN_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

SERVER_MODULES = {
    "knowledge": "server.mcp.knowledge_server",
    "build": "server.mcp.build_server",
    "research": "server.mcp.research_server",
    "learning": "server.mcp.learning_server",
}


def _check() -> int:
    from server import paths

    checks = {
        "server": (PLUGIN_ROOT / "server" / "main.py").is_file(),
        "splitEntries": all(
            (PLUGIN_ROOT / "server" / "mcp" / f"{name}_server.py").is_file()
            for name in SERVER_MODULES
        ),
        "corpus": paths.corpus_path().is_file(),
        "researchSeed": paths.mature_learning_release_seed_path().is_file(),
        "graphSeed": paths.physical_graph_seed_manifest_path().is_file(),
        "pobSource": paths.pob_src_dir().is_dir(),
        "pobHeadless": paths.pob_headless_script().is_file(),
    }
    print(json.dumps({"ok": all(checks.values()), "checks": checks}, sort_keys=True))
    return 0 if all(checks.values()) else 1


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["--research-cli"]:
        from scripts.research_mature_builds import main as run_research_cli

        return run_research_cli(args[1:])
    if "--check" in args:
        return _check()
    server_arg = None
    if "--server" in args:
        idx = args.index("--server")
        if idx + 1 < len(args):
            server_arg = args[idx + 1]
        else:
            print("--server requires a domain (knowledge|build|research|learning)", file=sys.stderr)
            return 2
    if server_arg:
        module = SERVER_MODULES.get(server_arg)
        if module is None:
            print(
                json.dumps({"ok": False, "error": f"unknown server domain: {server_arg}"}),
                file=sys.stderr,
            )
            return 2
        importlib.import_module(module).mcp.run()
        return 0
    from server.main import main as run_server

    run_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
