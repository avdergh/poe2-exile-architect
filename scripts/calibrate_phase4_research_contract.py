from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.knowledge import research_maintenance  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan or apply the Phase 4 research-contract calibration."
    )
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--backup-path", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = research_maintenance.calibrate_research_contract_v1(
        db_path=args.db_path,
        apply=args.apply,
        backup_path=args.backup_path,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
