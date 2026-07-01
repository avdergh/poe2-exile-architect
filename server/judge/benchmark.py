"""Synthetic judge benchmark writer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from server import paths

from . import evaluator, fixtures, models

FIXTURE_SET_ID = "phase1_judge_synthetic_v1"


def run_judge_benchmark(engine: Any = None, *, persist: bool = True) -> dict[str, Any]:
    del engine  # Synthetic baseline does not import raw PoB material.
    cases = []
    for case in sorted(fixtures.FIXTURES, key=lambda c: c["snapshotId"]):
        cases.append(
            evaluator.evaluate_readback(
                case["build"],
                case["metrics"],
                case["defenses"],
                snapshot_id=case["snapshotId"],
            )
        )
    report = {
        "fixtureSetId": FIXTURE_SET_ID,
        "generatedAt": datetime.now(UTC).isoformat(),
        "reproducibility": {
            "evaluatorVersion": models.EVALUATOR_VERSION,
            "pobPinnedCommit": "unknown",
            "treeVersion": _first_tree_version(cases),
        },
        "cases": cases,
    }
    if persist:
        out = paths.user_data_dir() / "runtime" / "judge_baseline_phase1.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _first_tree_version(cases: list[dict[str, Any]]) -> str | None:
    for case in cases:
        version = (case.get("reproducibility") or {}).get("treeVersion")
        if version:
            return str(version)
    return None
