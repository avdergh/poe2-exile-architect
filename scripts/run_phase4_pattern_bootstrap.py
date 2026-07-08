"""Accept a safe Phase 4.5 mature-pattern bootstrap proposal.

This is a manifest-driven gate for the first 20-30 mature BD bootstrap batch.
It does not fetch builds, decode PoB, or call an LLM provider. External agents
must submit clean BuildDesignObservation / BuildPattern proposals; this script
only verifies source coverage, manifest diversity, evidence counts, copy-safety,
and the existing research-memory service gate before writing durable patterns.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server import paths  # noqa: E402
from server.knowledge import copy_safety, graph_tools, research_memory  # noqa: E402

MANIFEST = REPO_ROOT / "phase4_pattern_bootstrap_manifest.json"
PROPOSAL = REPO_ROOT / "phase4_pattern_bootstrap_external_proposal.json"
SOURCE_COVERAGE_REPORT = REPO_ROOT / "phase4_local_physical_graph_snapshot_report.json"
JSON_OUTPUT = REPO_ROOT / "phase4_pattern_bootstrap_report.json"
MD_OUTPUT = REPO_ROOT / "phase4_pattern_bootstrap_report.md"

RAW_MARKERS = (
    "eNrt",
    "rawXml",
    "rawImportCode",
    "PathOfBuilding",
    "<Build",
    "<Skills",
    "nameSpec",
    "transientPacketPath",
    "transientPromptPath",
    "pobb.in/",
    "poe.ninja/",
)
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
DEFAULT_MIN_SAMPLES = 20
DEFAULT_MAX_SAMPLES = 30
DEFAULT_MIN_FAMILIES = 4
DEFAULT_MAX_FAMILIES = 6
DEFAULT_MIN_SAMPLES_PER_FAMILY = 3


def build_phase4_pattern_bootstrap_report(
    *,
    manifest_file: str | Path = MANIFEST,
    proposal_file: str | Path = PROPOSAL,
    source_coverage_report: str | Path = SOURCE_COVERAGE_REPORT,
    db_path: str | Path | None = None,
    graph_snapshot_index: str | Path | None = None,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    max_samples: int = DEFAULT_MAX_SAMPLES,
    min_families: int = DEFAULT_MIN_FAMILIES,
    max_families: int = DEFAULT_MAX_FAMILIES,
    min_samples_per_family: int = DEFAULT_MIN_SAMPLES_PER_FAMILY,
) -> dict[str, Any]:
    try:
        manifest = json.loads(Path(manifest_file).read_text(encoding="utf-8"))
        proposal = json.loads(Path(proposal_file).read_text(encoding="utf-8"))
        coverage = json.loads(Path(source_coverage_report).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _terminal_report(
            "rejected_invalid_input_artifact",
            error_code="invalid_input_artifact",
            caveats=[_safe_text(str(exc))],
        )

    try:
        _assert_safe_report(manifest)
        _assert_safe_report(proposal)
        _assert_safe_report(coverage)
    except ValueError as exc:
        del exc
        return _terminal_report(
            "rejected_unsafe_bootstrap_manifest",
            error_code="unsafe_bootstrap_artifact",
            caveats=["bootstrap artifact contains raw or copyable mature-build markers"],
        )

    manifest_validation = _validate_manifest(
        manifest,
        min_samples=min_samples,
        max_samples=max_samples,
        min_families=min_families,
        max_families=max_families,
        min_samples_per_family=min_samples_per_family,
    )
    if manifest_validation["status"] != "ok":
        return _blocked_or_rejected_report(
            status=str(manifest_validation["status"]),
            error_code=str(manifest_validation["errorCode"]),
            manifest_summary=manifest_validation["manifestSummary"],
            coverage=coverage,
            caveats=manifest_validation.get("caveats", []),
        )

    coverage_gate = coverage.get("coverageGate") if isinstance(coverage, dict) else {}
    if (
        not isinstance(coverage_gate, dict)
        or coverage_gate.get("readyForMaturePatternBootstrap") is not True
    ):
        report = _blocked_or_rejected_report(
            status="blocked_source_coverage_gap",
            error_code="source_coverage_not_ready",
            manifest_summary=manifest_validation["manifestSummary"],
            coverage=coverage,
            caveats=[
                "Passive/notable/keystone/ascendancy/unique/support coverage must be ready before mature pattern bootstrap."
            ],
        )
        _assert_safe_report(report)
        return report

    evidence_gate = _proposal_evidence_gate(proposal, manifest_validation)
    if evidence_gate["status"] != "ok":
        report = _blocked_or_rejected_report(
            status="rejected_bootstrap_evidence_mismatch",
            error_code=str(evidence_gate["errorCode"]),
            manifest_summary=manifest_validation["manifestSummary"],
            coverage=coverage,
            caveats=evidence_gate.get("caveats", []),
        )
        _assert_safe_report(report)
        return report

    index_path = (
        Path(graph_snapshot_index)
        if graph_snapshot_index is not None
        else paths.user_data_dir() / "physical_graph" / "snapshot_index.sqlite"
    )
    try:
        graph_service = graph_tools.service_from_snapshot_index(str(index_path))
    except Exception as exc:  # pragma: no cover - platform/path dependent
        report = _blocked_or_rejected_report(
            status="blocked_graph_snapshot_unavailable",
            error_code="graph_snapshot_unavailable",
            manifest_summary=manifest_validation["manifestSummary"],
            coverage=coverage,
            caveats=[_safe_text(str(exc))],
        )
        _assert_safe_report(report)
        return report

    service = research_memory.ResearchMemoryService(
        db_path=Path(db_path) if db_path else None,
        graph_service=graph_service,
    )
    pattern_write = service.propose_build_patterns(proposal)
    report = {
        "reportId": "phase4-pattern-bootstrap-v1",
        "status": "accepted"
        if pattern_write.get("status") == "accepted"
        else "rejected_by_pattern_gate",
        "safeArtifactOnly": True,
        "manifestReportId": _safe_text(manifest.get("reportId")),
        "sourceCoverageReportId": _safe_text(coverage.get("reportId")),
        "coverageGate": _safe_json(coverage_gate),
        "sampleCount": manifest_validation["sampleCount"],
        "familyCount": manifest_validation["familyCount"],
        "sourceDiversityCount": manifest_validation["sourceDiversityCount"],
        "familySampleCounts": manifest_validation["familySampleCounts"],
        "patternWrite": _safe_service_summary(pattern_write),
        "metrics": {
            "observationProposalCount": len(proposal.get("build_design_observations", []))
            if isinstance(proposal.get("build_design_observations"), list)
            else 0,
            "patternProposalCount": len(proposal.get("patterns", []))
            if isinstance(proposal.get("patterns"), list)
            else 0,
            "acceptedPatternCount": len(pattern_write.get("patternIds", []))
            if pattern_write.get("status") == "accepted"
            else 0,
            "commonPatternCount": _pattern_tier_count(proposal, "common_within_archetype"),
            "plannerHintCount": _pattern_type_count(proposal, "planner_hint"),
        },
        "patternConfidenceTiers": _pattern_tier_counts(proposal),
        "patternTypes": _pattern_type_counts(proposal),
        "caveats": [
            "This bootstrap report is safe-only and stores no raw mature-build material.",
            "Pattern confidence remains advisory and must be verified by Phase 5 planner and Judge.",
        ],
        "noRawMatureBuildMaterial": True,
    }
    _assert_safe_report(report)
    return report


def write_phase4_pattern_bootstrap_report(
    *,
    manifest_file: str | Path = MANIFEST,
    proposal_file: str | Path = PROPOSAL,
    source_coverage_report: str | Path = SOURCE_COVERAGE_REPORT,
    db_path: str | Path | None = None,
    graph_snapshot_index: str | Path | None = None,
    json_output: str | Path = JSON_OUTPUT,
    md_output: str | Path = MD_OUTPUT,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    max_samples: int = DEFAULT_MAX_SAMPLES,
    min_families: int = DEFAULT_MIN_FAMILIES,
    max_families: int = DEFAULT_MAX_FAMILIES,
    min_samples_per_family: int = DEFAULT_MIN_SAMPLES_PER_FAMILY,
) -> dict[str, Any]:
    report = build_phase4_pattern_bootstrap_report(
        manifest_file=manifest_file,
        proposal_file=proposal_file,
        source_coverage_report=source_coverage_report,
        db_path=db_path,
        graph_snapshot_index=graph_snapshot_index,
        min_samples=min_samples,
        max_samples=max_samples,
        min_families=min_families,
        max_families=max_families,
        min_samples_per_family=min_samples_per_family,
    )
    Path(json_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(md_output).write_text(_markdown(report), encoding="utf-8")
    return report


def _validate_manifest(
    manifest: dict[str, Any],
    *,
    min_samples: int,
    max_samples: int,
    min_families: int,
    max_families: int,
    min_samples_per_family: int,
) -> dict[str, Any]:
    samples = manifest.get("samples")
    if manifest.get("safeArtifactOnly") is not True or not isinstance(samples, list):
        return _manifest_error("invalid_bootstrap_manifest", "safe manifest must contain samples")

    sample_ids: set[str] = set()
    family_counts: dict[str, int] = {}
    source_keys: set[str] = set()
    variant_keys: set[str] = set()
    sample_index: dict[str, dict[str, str]] = {}
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            return _manifest_error("invalid_bootstrap_manifest", f"samples[{index}] must be object")
        sample_id = _safe_token(sample.get("sampleId"), f"samples[{index}].sampleId")
        family = _safe_token(sample.get("buildFamilyKey"), f"samples[{index}].buildFamilyKey")
        source = _safe_token(
            sample.get("sourceDiversityKey"), f"samples[{index}].sourceDiversityKey"
        )
        variant = _safe_token(
            sample.get("guideVariantKey") or sample_id,
            f"samples[{index}].guideVariantKey",
        )
        if sample_id in sample_ids:
            return _manifest_error("duplicate_sample_id", sample_id)
        sample_ids.add(sample_id)
        source_keys.add(source)
        variant_keys.add(variant)
        family_counts[family] = family_counts.get(family, 0) + 1
        sample_index[sample_id] = {
            "buildFamilyKey": family,
            "sourceDiversityKey": source,
            "guideVariantKey": variant,
        }

    sample_count = len(sample_ids)
    family_count = len(family_counts)
    if sample_count < min_samples or sample_count > max_samples:
        return _manifest_error(
            "bootstrap_sample_count_out_of_range",
            f"sample_count={sample_count}, required={min_samples}-{max_samples}",
            manifest_summary=_manifest_summary(sample_ids, family_counts, source_keys),
        )
    if family_count < min_families or family_count > max_families:
        return _manifest_error(
            "bootstrap_family_count_out_of_range",
            f"family_count={family_count}, required={min_families}-{max_families}",
            manifest_summary=_manifest_summary(sample_ids, family_counts, source_keys),
        )
    underfilled = {
        family: count for family, count in family_counts.items() if count < min_samples_per_family
    }
    if underfilled:
        return _manifest_error(
            "bootstrap_family_underfilled",
            "each family must have enough independent samples",
            manifest_summary=_manifest_summary(sample_ids, family_counts, source_keys),
            facts={"underfilledFamilies": underfilled},
        )
    if len(variant_keys) < sample_count:
        return _manifest_error(
            "bootstrap_duplicate_guide_variant",
            "same guide variants cannot be counted as independent samples",
            manifest_summary=_manifest_summary(sample_ids, family_counts, source_keys),
        )
    return {
        "status": "ok",
        "sampleIds": sample_ids,
        "sampleCount": sample_count,
        "familyCount": family_count,
        "sourceDiversityCount": len(source_keys),
        "familySampleCounts": dict(sorted(family_counts.items())),
        "manifestSummary": _manifest_summary(sample_ids, family_counts, source_keys),
        "sampleIndex": sample_index,
    }


def _proposal_evidence_gate(
    proposal: dict[str, Any], manifest_validation: dict[str, Any]
) -> dict[str, Any]:
    sample_ids = set(manifest_validation["sampleIds"])
    for index, pattern in enumerate(proposal.get("patterns", [])):
        if not isinstance(pattern, dict):
            return _evidence_error("invalid_pattern_shape", f"patterns[{index}] must be object")
        refs = {str(ref) for ref in pattern.get("source_case_refs", []) if str(ref).strip()}
        outside = sorted(refs - sample_ids)
        if outside:
            return _evidence_error(
                "pattern_source_case_ref_not_in_manifest",
                "pattern references cases outside the bootstrap manifest",
                facts={"outsideSourceCaseRefs": outside},
            )
        ref_stats = _source_ref_stats(refs, manifest_validation)
        observation_ref_error = _supporting_observation_ref_error(
            pattern, proposal, sample_ids, refs
        )
        if observation_ref_error is not None:
            return observation_ref_error
        if int(pattern.get("sample_count", 0)) > ref_stats["sampleCount"]:
            return _evidence_error(
                "pattern_sample_count_exceeds_pattern_refs",
                "pattern sample_count must be supported by its own source_case_refs",
            )
        if int(pattern.get("sample_count", 0)) > len(refs):
            return _evidence_error(
                "pattern_sample_count_exceeds_pattern_refs",
                "pattern sample_count must be supported by its own source_case_refs",
            )
        if int(pattern.get("family_count", 0)) > ref_stats["familyCount"]:
            return _evidence_error(
                "pattern_family_count_exceeds_pattern_refs",
                "pattern family_count must be supported by its own source_case_refs",
            )
        if int(pattern.get("source_diversity_count", 0)) > ref_stats["sourceDiversityCount"]:
            return _evidence_error(
                "pattern_source_diversity_exceeds_pattern_refs",
                "pattern source_diversity_count must be supported by its own source_case_refs",
            )
    return {"status": "ok"}


def _source_ref_stats(refs: set[str], manifest_validation: dict[str, Any]) -> dict[str, int]:
    sample_index = manifest_validation.get("sampleIndex", {})
    families = {
        str(sample_index.get(ref, {}).get("buildFamilyKey"))
        for ref in refs
        if sample_index.get(ref, {}).get("buildFamilyKey")
    }
    sources = {
        str(sample_index.get(ref, {}).get("sourceDiversityKey"))
        for ref in refs
        if sample_index.get(ref, {}).get("sourceDiversityKey")
    }
    return {
        "sampleCount": len(refs),
        "familyCount": len(families),
        "sourceDiversityCount": len(sources),
    }


def _supporting_observation_ref_error(
    pattern: dict[str, Any],
    proposal: dict[str, Any],
    sample_ids: set[str],
    pattern_refs: set[str],
) -> dict[str, Any] | None:
    pattern_keys = {str(key) for key in pattern.get("component_keys", []) if str(key).strip()}
    matching_observations = [
        observation
        for observation in proposal.get("build_design_observations", [])
        if isinstance(observation, dict)
        and _observation_matches_pattern_payload(observation, pattern, pattern_keys)
    ]
    if not matching_observations:
        return _evidence_error(
            "pattern_missing_supporting_observation",
            "pattern must have a same-batch observation containing all component keys",
        )
    for observation in matching_observations:
        observation_refs = {
            str(ref) for ref in observation.get("source_case_refs", []) if str(ref).strip()
        }
        outside = sorted(observation_refs - sample_ids)
        if outside:
            return _evidence_error(
                "observation_source_case_ref_not_in_manifest",
                "supporting observation references cases outside the bootstrap manifest",
                facts={"outsideSourceCaseRefs": outside},
            )
        if pattern_refs and not pattern_refs.issubset(observation_refs):
            return _evidence_error(
                "pattern_refs_not_covered_by_supporting_observation",
                "supporting observation source_case_refs must cover pattern source_case_refs",
            )
    return None


def _observation_matches_pattern_payload(
    observation: dict[str, Any],
    pattern: dict[str, Any],
    pattern_keys: set[str],
) -> bool:
    observation_keys = {
        str(component.get("component_key"))
        for component in observation.get("components", [])
        if isinstance(component, dict) and str(component.get("component_key")).strip()
    }
    return (
        pattern_keys.issubset(observation_keys)
        and observation.get("visibility") == pattern.get("visibility")
        and observation.get("split") == pattern.get("split")
        and observation.get("knowledge_scope") == pattern.get("knowledge_scope")
        and observation.get("game_patch") == pattern.get("game_patch")
        and observation.get("passive_tree_version") == pattern.get("passive_tree_version")
        and observation.get("pob_version_or_commit") == pattern.get("pob_version_or_commit")
    )


def _safe_token(value: Any, field: str) -> str:
    token = _safe_text(value)
    if not token or not SAFE_TOKEN_RE.fullmatch(token):
        raise ValueError(f"{field} must be a safe token")
    return token


def _manifest_error(
    error_code: str,
    caveat: str,
    *,
    manifest_summary: dict[str, Any] | None = None,
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = manifest_summary or {
        "sampleCount": 0,
        "familyCount": 0,
        "sourceDiversityCount": 0,
        "familySampleCounts": {},
    }
    return {
        "status": "rejected_bootstrap_manifest",
        "errorCode": error_code,
        "caveats": [_safe_text(caveat)],
        "manifestSummary": summary,
        "facts": facts or {},
    }


def _evidence_error(
    error_code: str, caveat: str, *, facts: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "status": "error",
        "errorCode": error_code,
        "caveats": [_safe_text(caveat)],
        "facts": _safe_json(facts or {}),
    }


def _manifest_summary(
    sample_ids: set[str],
    family_counts: dict[str, int],
    source_keys: set[str],
) -> dict[str, Any]:
    return {
        "sampleCount": len(sample_ids),
        "familyCount": len(family_counts),
        "sourceDiversityCount": len(source_keys),
        "familySampleCounts": dict(sorted(family_counts.items())),
    }


def _blocked_or_rejected_report(
    *,
    status: str,
    error_code: str,
    manifest_summary: dict[str, Any],
    coverage: dict[str, Any],
    caveats: list[str],
) -> dict[str, Any]:
    report = {
        "reportId": "phase4-pattern-bootstrap-v1",
        "status": status,
        "safeArtifactOnly": True,
        "errorCode": error_code,
        "coverageGate": _safe_json(coverage.get("coverageGate", {})),
        "sampleCount": manifest_summary.get("sampleCount", 0),
        "familyCount": manifest_summary.get("familyCount", 0),
        "sourceDiversityCount": manifest_summary.get("sourceDiversityCount", 0),
        "familySampleCounts": manifest_summary.get("familySampleCounts", {}),
        "patternWrite": {"attempted": False},
        "metrics": {
            "acceptedPatternCount": 0,
            "commonPatternCount": 0,
            "plannerHintCount": 0,
        },
        "caveats": [_safe_text(caveat) for caveat in caveats],
        "noRawMatureBuildMaterial": True,
    }
    _assert_safe_report(report)
    return report


def _terminal_report(status: str, *, error_code: str, caveats: list[str]) -> dict[str, Any]:
    report = {
        "reportId": "phase4-pattern-bootstrap-v1",
        "status": status,
        "safeArtifactOnly": True,
        "errorCode": error_code,
        "sampleCount": 0,
        "familyCount": 0,
        "sourceDiversityCount": 0,
        "familySampleCounts": {},
        "patternWrite": {"attempted": False},
        "metrics": {"acceptedPatternCount": 0, "commonPatternCount": 0, "plannerHintCount": 0},
        "caveats": [_safe_text(caveat) for caveat in caveats],
        "noRawMatureBuildMaterial": True,
    }
    _assert_safe_report(report)
    return report


def _safe_service_summary(result: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "attempted": True,
        "status": result.get("status"),
        "observationIds": result.get("observationIds", []),
        "patternIds": result.get("patternIds", []),
        "errorCode": result.get("errorCode"),
        "caveats": result.get("caveats", []),
        "noRawMatureBuildMaterial": result.get("noRawMatureBuildMaterial"),
    }
    return _safe_json(summary)


def _pattern_tier_count(proposal: dict[str, Any], tier: str) -> int:
    return sum(
        1
        for pattern in proposal.get("patterns", [])
        if isinstance(pattern, dict) and pattern.get("confidence_tier") == tier
    )


def _pattern_tier_counts(proposal: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pattern in proposal.get("patterns", []):
        if not isinstance(pattern, dict):
            continue
        tier = _safe_text(pattern.get("confidence_tier"))
        if tier:
            counts[tier] = counts.get(tier, 0) + 1
    return dict(sorted(counts.items()))


def _pattern_type_count(proposal: dict[str, Any], pattern_type: str) -> int:
    return sum(
        1
        for pattern in proposal.get("patterns", [])
        if isinstance(pattern, dict) and pattern.get("pattern_type") == pattern_type
    )


def _pattern_type_counts(proposal: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pattern in proposal.get("patterns", []):
        if not isinstance(pattern, dict):
            continue
        pattern_type = _safe_text(pattern.get("pattern_type"))
        if pattern_type:
            counts[pattern_type] = counts.get(pattern_type, 0) + 1
    return dict(sorted(counts.items()))


def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(_safe_text(key)): _safe_json(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_safe_json(child) for child in value]
    if isinstance(value, str):
        return _safe_text(value)
    if value is None or isinstance(value, bool | int | float):
        return value
    return _safe_text(value)


def _safe_text(value: Any) -> str:
    text = " ".join(str(value or "").split())[:320]
    _reject_copyable(text)
    return text


def _reject_copyable(text: str) -> None:
    lower = text.lower()
    if any(marker.lower() in lower for marker in RAW_MARKERS):
        raise ValueError("copy-safety marker detected")
    if re.search(
        r"(?:https?://|www\.|pobb\.in|pastebin\.com|poe\.ninja|pathofexile\.com)",
        lower,
    ):
        raise ValueError("copy-safety URL marker detected")
    flags = set(copy_safety.copyability_flags(text))
    flags.discard("full_gem_link_like")
    if flags:
        raise ValueError(f"copy-safety flags detected: {', '.join(sorted(flags))}")


def _assert_safe_report(report: dict[str, Any]) -> None:
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    leaks = [marker for marker in RAW_MARKERS if marker in serialized]
    if leaks:
        raise ValueError(f"unsafe durable report markers detected: {', '.join(leaks)}")
    flags = set(copy_safety.copyability_flags(report))
    flags.discard("full_gem_link_like")
    if flags:
        raise ValueError(f"durable report failed copy-safety scan: {', '.join(sorted(flags))}")
    forbidden = copy_safety.find_forbidden_paths(report)
    if forbidden:
        raise ValueError("durable report contains forbidden raw fields")


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 4.5 Pattern Bootstrap",
        "",
        f"- Status: `{report['status']}`",
        f"- Samples: `{report.get('sampleCount', 0)}`",
        f"- Families: `{report.get('familyCount', 0)}`",
        f"- Source diversity: `{report.get('sourceDiversityCount', 0)}`",
        f"- Pattern write: `{report.get('patternWrite', {}).get('status', 'not_attempted')}`",
        "",
        "## Family Sample Counts",
        "",
    ]
    for family, count in sorted(report.get("familySampleCounts", {}).items()):
        lines.append(f"- `{family}`: `{count}`")
    lines.extend(["", "## Metrics", ""])
    for key, value in sorted(report.get("metrics", {}).items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Pattern Confidence Tiers", ""])
    for tier, count in sorted(report.get("patternConfidenceTiers", {}).items()):
        lines.append(f"- `{tier}`: `{count}`")
    lines.extend(["", "## Pattern Types", ""])
    for pattern_type, count in sorted(report.get("patternTypes", {}).items()):
        lines.append(f"- `{pattern_type}`: `{count}`")
    lines.extend(["", "## Caveats", ""])
    lines.extend(f"- {item}" for item in report.get("caveats", []))
    lines.append("")
    text = "\n".join(lines)
    for marker in RAW_MARKERS:
        if marker in text:
            raise ValueError(f"unsafe markdown marker detected: {marker}")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-file", default=str(MANIFEST))
    parser.add_argument("--proposal-file", default=str(PROPOSAL))
    parser.add_argument("--source-coverage-report", default=str(SOURCE_COVERAGE_REPORT))
    parser.add_argument("--db-path", default=None)
    parser.add_argument(
        "--graph-snapshot-index",
        default=str(paths.user_data_dir() / "physical_graph" / "snapshot_index.sqlite"),
    )
    parser.add_argument("--json-output", default=str(JSON_OUTPUT))
    parser.add_argument("--md-output", default=str(MD_OUTPUT))
    parser.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    parser.add_argument("--max-samples", type=int, default=DEFAULT_MAX_SAMPLES)
    parser.add_argument("--min-families", type=int, default=DEFAULT_MIN_FAMILIES)
    parser.add_argument("--max-families", type=int, default=DEFAULT_MAX_FAMILIES)
    parser.add_argument(
        "--min-samples-per-family", type=int, default=DEFAULT_MIN_SAMPLES_PER_FAMILY
    )
    args = parser.parse_args(argv)
    report = write_phase4_pattern_bootstrap_report(
        manifest_file=args.manifest_file,
        proposal_file=args.proposal_file,
        source_coverage_report=args.source_coverage_report,
        db_path=args.db_path,
        graph_snapshot_index=args.graph_snapshot_index,
        json_output=args.json_output,
        md_output=args.md_output,
        min_samples=args.min_samples,
        max_samples=args.max_samples,
        min_families=args.min_families,
        max_families=args.max_families,
        min_samples_per_family=args.min_samples_per_family,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
