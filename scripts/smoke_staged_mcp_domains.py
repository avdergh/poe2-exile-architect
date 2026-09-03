"""Verify that one staged bundle exposes the four disjoint MCP tool domains."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path
import sys


EXPECTED_TOTAL = 160
MODULES = (
    "server.mcp.knowledge_server",
    "server.mcp.build_server",
    "server.mcp.research_server",
    "server.mcp.learning_server",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    stage = args.stage.resolve()
    if not (stage / "server" / "main.py").is_file():
        raise FileNotFoundError(f"staged server is missing: {stage}")
    sys.path.insert(0, str(stage))
    domains: dict[str, set[str]] = {}
    for module_name in MODULES:
        module = importlib.import_module(module_name)
        names = {tool.__name__ for tool in module._TOOLS}
        if not names:
            raise RuntimeError(f"empty staged MCP domain: {module_name}")
        domains[module_name] = names
    seen: set[str] = set()
    for module_name, names in domains.items():
        duplicate = seen & names
        if duplicate:
            raise RuntimeError(f"staged MCP tools overlap in {module_name}: {sorted(duplicate)}")
        seen.update(names)
    if len(seen) != EXPECTED_TOTAL:
        raise RuntimeError(f"staged MCP tool count is {len(seen)}, expected {EXPECTED_TOTAL}")
    if "get_research_write_receipt" not in domains["server.mcp.knowledge_server"]:
        raise RuntimeError("staged knowledge MCP omitted get_research_write_receipt")
    print("STAGED FOUR-DOMAIN MCP SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
