"""Verify that one staged bundle exposes the four disjoint MCP tool domains."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys


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
    manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
    declarations = [item["name"] for item in manifest["tools"]]
    expected = set(declarations)
    if not expected or len(expected) != len(declarations):
        raise RuntimeError("staged manifest has an empty or duplicate tool declaration")
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
    if seen != expected:
        raise RuntimeError(
            "staged MCP tools do not match the staged manifest: "
            f"missing={sorted(expected - seen)}, undeclared={sorted(seen - expected)}"
        )
    if "get_research_write_receipt" not in domains["server.mcp.knowledge_server"]:
        raise RuntimeError("staged knowledge MCP omitted get_research_write_receipt")
    print("STAGED FOUR-DOMAIN MCP SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
