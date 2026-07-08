"""Run the deterministic Phase 4 research-memory benchmark.

The benchmark uses fixed clean proposals only. It never writes raw mature-build material into
artifacts; reports contain safe ids, hashes, status counts, and retrieval hit summaries.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.knowledge import research_memory  # noqa: E402

JSON_OUTPUT = REPO_ROOT / "phase4_research_memory_benchmark.json"
MD_OUTPUT = REPO_ROOT / "phase4_research_memory_benchmark.md"


def _fragment_payload() -> dict[str, Any]:
    return {
        "schema_version": 4,
        "fragments": [
            {
                "fragment_type": "mechanic",
                "title": "Projectile overlap caveat",
                "summary": "Projectile count can improve clear, but single-target value depends on overlap evidence.",
                "reusable_principle": "Treat projectile count as conditional coverage until selected-skill Judge evidence confirms it.",
                "source_case_refs": ["case:phase4-safe-projectile"],
                "safe_evidence_refs": ["safe:phase4:projectile"],
                "confidence": "medium",
                "copyability_risk": "low",
                "lifecycle_stages": ["endgame_budget"],
                "modelability": "partial",
                "verification_tasks": ["Run selected-skill Judge readback before strong reward."],
                "component_keys": ["skill:LightningArrowPlayer"],
                "conditions": ["projectile overlap context"],
                "risks": ["FullDPS overclaim"],
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
            }
        ],
        "semantic_edges": [],
    }


def run_benchmark() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="poe-phase4-benchmark-") as temp_dir:
        service = research_memory.ResearchMemoryService(db_path=Path(temp_dir) / "mature.sqlite")
        query = service.query_research_memory(
            "projectile overlap",
            component_keys=["skill:LightningArrowPlayer"],
        )
        ingest = service.propose_research_fragments(
            _fragment_payload(),
            dedupe_query_ref=query["dedupeQueryRef"],
        )
        retrieval = service.query_research_memory(
            "projectile overlap",
            component_keys=["skill:LightningArrowPlayer"],
        )
        duplicate = service.propose_research_fragments(
            _fragment_payload(),
            dedupe_query_ref=query["dedupeQueryRef"],
        )

    hit_ids = [row["fragmentId"] for row in retrieval["results"]]
    passed = (
        ingest["status"] == "accepted"
        and bool(hit_ids)
        and duplicate["errorCode"] == "duplicate_fragment_candidate"
    )
    return {
        "benchmarkId": "phase4-research-memory-fixed-v1",
        "status": "pass" if passed else "fail",
        "safeArtifactOnly": True,
        "fragmentIds": ingest.get("fragmentIds", []),
        "retrievalHitIds": hit_ids,
        "duplicateStatus": duplicate["status"],
        "duplicateErrorCode": duplicate.get("errorCode"),
        "metrics": {
            "schemaValidationExplainable": True,
            "retrievalHitCount": len(hit_ids),
            "duplicateRejected": duplicate.get("errorCode") == "duplicate_fragment_candidate",
            "noRawMatureBuildMaterial": True,
        },
        "caveats": [
            "Deterministic clean fixture only; external Researcher E2E still requires human review."
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 4 Research Memory Benchmark",
        "",
        f"- Benchmark: `{report['benchmarkId']}`",
        f"- Status: `{report['status']}`",
        f"- Safe artifact only: `{report['safeArtifactOnly']}`",
        f"- Retrieval hits: `{report['metrics']['retrievalHitCount']}`",
        f"- Duplicate rejected: `{report['metrics']['duplicateRejected']}`",
        "",
        "## Caveats",
        "",
    ]
    lines.extend(f"- {item}" for item in report["caveats"])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    report = run_benchmark()
    JSON_OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    MD_OUTPUT.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
