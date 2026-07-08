"""Accept one Phase 4.5 Researcher review through the existing gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import run_phase4_deep_review_acceptance as acceptance  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    print(
        "deprecated: use `python scripts/research_mature_builds.py accept` "
        "or the /poe-bd-research skill instead of phase45_accept_single_review.py",
        file=sys.stderr,
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-file", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--db-path", default=str(REPO_ROOT / "phase4_real_research_memory.sqlite"))
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / ".phase45_runs" / "user_first10_queue" / "acceptance"),
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    review_file = Path(args.review_file)
    if not review_file.is_absolute():
        review_file = output_dir / review_file
    slug = str(args.case_id).replace(":", "-")
    report = acceptance.accept_deep_review_candidates(
        db_path=Path(args.db_path),
        json_output=output_dir / f"{slug}-acceptance.json",
        md_output=output_dir / f"{slug}-acceptance.md",
        review_file=review_file,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "acceptedPatternCount": report.get("acceptedPatternCount", 0),
                "deferredCandidateCount": report.get("deferredCandidateCount", 0),
                "patternWrite": report.get("patternWrite", {}),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
