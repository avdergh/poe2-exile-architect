"""Run Phase 1 judge against local, transient user-provided PoB samples.

The report deliberately omits raw codes, raw XML, full gear, passive paths, and gem links.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from server.compute.engine import PobEngine  # noqa: E402
from server.judge import evaluator, runner, sample_audit  # noqa: E402


def evaluate_source(source: str, snapshot_id: str) -> dict[str, Any]:
    source_hash = evaluator.compute_source_hash(source)

    def factory() -> PobEngine:
        engine = PobEngine()
        try:
            stripped = source.strip()
            if stripped.lstrip().startswith("<"):
                engine.load_build_xml(stripped, name=snapshot_id)
            elif stripped.lower().startswith(("http://", "https://")):
                engine.load_build_link(stripped, name=snapshot_id)
            else:
                engine.load_build_code(stripped, name=snapshot_id)
            return engine
        except Exception:
            engine.close()
            raise

    result = runner.safe_evaluate_active_build(
        factory,
        snapshot_id=snapshot_id,
        timeout_seconds=900.0,
        source_context="trusted_reference",
    )
    result["sourceHash"] = source_hash
    result["summary"] = _sanitize_summary(result.get("summary") or {})
    return _sanitize_evaluation(sample_audit.finalize_sample_classification(result))


def build_report(source_file: str | Path) -> dict[str, Any]:
    path = Path(source_file)
    content = path.read_text(encoding="utf-8")
    samples = _parse_samples(content)
    report_samples = []
    for idx, sample in enumerate(samples, start=1):
        report_samples.append(evaluate_source(sample, snapshot_id=f"user_sample_{idx:03d}"))
    return {
        "sampleCount": len(report_samples),
        "samples": report_samples,
        "regressionMatrix": [_matrix_row(sample) for sample in report_samples],
    }


def _parse_samples(content: str) -> list[str]:
    text = (content or "").strip()
    if not text:
        return []
    if _looks_like_xml(text):
        return [text]
    parsed = _parse_json_samples(text)
    if parsed is not None:
        return parsed
    if "\n---POB-SAMPLE---\n" in text:
        return [part.strip() for part in text.split("\n---POB-SAMPLE---\n") if part.strip()]
    return [line.strip() for line in text.splitlines() if line.strip()]


def _looks_like_xml(text: str) -> bool:
    return text.lstrip().startswith("<") and "PathOfBuilding" in text[:500]


def _parse_json_samples(text: str) -> list[str] | None:
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        loaded = None
    if isinstance(loaded, list):
        out = [_source_from_json_item(item) for item in loaded]
        return [sample for sample in out if sample]
    if isinstance(loaded, dict):
        rows = loaded.get("samples")
        if isinstance(rows, list):
            out = [_source_from_json_item(item) for item in rows]
            return [sample for sample in out if sample]
        sample = _source_from_json_item(loaded)
        return [sample] if sample else []

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or not all(line.startswith("{") for line in lines):
        return None
    out: list[str] = []
    try:
        for line in lines:
            sample = _source_from_json_item(json.loads(line))
            if sample:
                out.append(sample)
    except json.JSONDecodeError:
        return None
    return out


def _source_from_json_item(item: Any) -> str | None:
    if isinstance(item, str):
        return item.strip() or None
    if isinstance(item, dict):
        for key in ("code", "source", "xml", "url", "link"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-file", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(build_report(args.source_file), ensure_ascii=False, indent=2))
    return 0


def _sanitize_evaluation(result: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "snapshotId",
        "sourceHash",
        "summary",
        "levelBand",
        "scoreVector",
        "scoreBreakdown",
        "scoreScale",
        "scenarioFit",
        "qualityBand",
        "aggregateScore",
        "hardFailures",
        "physicalInvalidFailures",
        "legality",
        "modelability",
        "defenseModel",
        "caveats",
        "pass",
        "rewardEligible",
        "rewardStrength",
        "scoreReviewNeeded",
        "scoreReviewReasons",
        "finalClassification",
        "reproducibility",
        "errorKind",
    }
    return {k: v for k, v in result.items() if k in allowed and v is not None}


def _sanitize_summary(summary: dict[str, Any]) -> dict[str, Any]:
    sanitized = {
        "class": summary.get("class"),
        "ascendancy": summary.get("ascendancy"),
        "mainSkill": summary.get("mainSkill"),
        "level": summary.get("level"),
    }
    if summary.get("judgeSelectedSkill"):
        sanitized["judgeSelectedSkill"] = summary.get("judgeSelectedSkill")
    return sanitized


def _matrix_row(result: dict[str, Any]) -> dict[str, Any]:
    offense = (result.get("scoreBreakdown") or {}).get("offense") or {}
    offense_keys = {
        "provenance",
        "evidenceLevel",
        "skillName",
        "skillGroupIndex",
        "sourceMetricDetail",
        "isMinion",
        "activeSkillCount",
        "activeMinionLimit",
        "caveats",
    }
    defense_model = result.get("defenseModel") or {}
    defense_keys = {"poolModel", "confidence", "caveats"}
    return {
        "snapshotId": result.get("snapshotId"),
        "sourceHash": result.get("sourceHash"),
        "summary": _sanitize_summary(result.get("summary") or {}),
        "offense": {k: offense[k] for k in offense_keys if k in offense and offense[k] is not None},
        "defenseModel": {
            k: defense_model[k]
            for k in defense_keys
            if k in defense_model and defense_model[k] is not None
        },
        "hardFailures": list(result.get("hardFailures") or []),
        "physicalInvalidFailures": list(result.get("physicalInvalidFailures") or []),
        "caveats": list(result.get("caveats") or []),
        "pass": result.get("pass"),
        "rewardEligible": result.get("rewardEligible"),
        "rewardStrength": result.get("rewardStrength"),
        "scoreReviewNeeded": result.get("scoreReviewNeeded"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
