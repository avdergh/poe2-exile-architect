"""Inspect or apply the exact, fingerprint-bound 2026-08-22 Research repair."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.knowledge import mature_learning, research_known_repairs  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=mature_learning.mature_learning_path())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = (
        research_known_repairs.apply_known_repair(args.db)
        if args.apply
        else research_known_repairs.inspect_known_repair(args.db)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"ready", "applied", "already_applied"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
