"""Export data.uniques.generated (Generated.lua) into a static block file.

The physical-graph unique ingestion only parses static `[[...]]` blocks. Six 0.5.4
Time-Lost / generated uniques live in Data/Uniques/Special/Generated.lua as Lua-built
text (never ingested). This script boots the headless engine once and dumps the
generated texts into data/physical_graph/uniques/generated_uniques.lua so the graph
builder can ingest them without re-evaluating Lua.

Usage: uv run python scripts/export_generated_uniques.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.compute.engine import PobEngine  # noqa: E402

OUT_FILE = REPO_ROOT / "data" / "physical_graph" / "uniques" / "generated_uniques.lua"


def main() -> int:
    out_file = OUT_FILE
    out_file.parent.mkdir(parents=True, exist_ok=True)
    engine = PobEngine(
        script=REPO_ROOT / "pob" / "pob_headless.lua",
        src_dir=REPO_ROOT / "pob" / "PathOfBuilding-PoE2" / "src",
    )
    try:
        result = engine.call("dump_generated_uniques")
    finally:
        engine.close()
    uniques = result.get("uniques") or []
    if not isinstance(uniques, list) or not uniques:
        print(f"export failed: no generated uniques returned ({result})", file=sys.stderr)
        return 1
    expected = int(result.get("uniqueCount") or 0)
    if expected and len(uniques) != expected:
        print(
            f"export mismatch: expected {expected} blocks, got {len(uniques)}",
            file=sys.stderr,
        )
        return 1
    lines: list[str] = []
    for text in uniques:
        text = str(text)
        if "[[" in text or "]]" in text:
            print(
                "export abort: a unique text contains [[ or ]] and would break block parsing",
                file=sys.stderr,
            )
            return 1
        lines.append("[[")
        lines.append(text)
        lines.append("]],")
    header = (
        "-- Exported from data.uniques.generated (Data/Uniques/Special/Generated.lua) by\n"
        "-- scripts/export_generated_uniques.py; static blocks for physical_graph.ingest_uniques.\n"
        "-- Generated.lua remains authoritative; re-run this script after engine data updates.\n"
        "local generated_uniques = {\n"
    )
    out_file.write_text(
        header + "\n".join(lines) + "\n}\nreturn generated_uniques\n", encoding="utf-8"
    )
    names = []
    for text in uniques:
        first = next((ln for ln in str(text).splitlines() if ln.strip()), "")
        names.append(first)
    print(json.dumps({"exported": len(uniques), "file": str(out_file), "names": names}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
