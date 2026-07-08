"""Run Phase 4 Researcher tool-call acceptance from a safe packet report.

This script does not run an LLM and does not read transient packet files. It exercises the same
ResearchMemoryService paths that MCP tools use for query-before-propose, duplicate rejection, and
safe evidence append. Semantic edge ingestion is reported as blocked when the local Phase 3 graph
snapshot index is missing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server import paths  # noqa: E402
from server.knowledge import copy_safety, physical_graph, research_memory  # noqa: E402

JSON_OUTPUT = REPO_ROOT / "phase4_researcher_toolcall_e2e_report.json"
MD_OUTPUT = REPO_ROOT / "phase4_researcher_toolcall_e2e_report.md"
PACKET_REPORT = REPO_ROOT / "phase4_researcher_e2e_report.json"
RAW_MARKERS = (
    "eNrt",
    "rawXml",
    "rawImportCode",
    "PathOfBuilding",
    "<Build",
    "<Skills",
    "nameSpec",
)
TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


def build_toolcall_acceptance_report(
    *,
    input_report: str | Path = PACKET_REPORT,
    db_path: str | Path | None = None,
    graph_snapshot_index_path: str | Path | None = None,
) -> dict[str, Any]:
    source_report = json.loads(Path(input_report).read_text(encoding="utf-8"))
    _validate_input_report(source_report)
    db_file = Path(db_path) if db_path is not None else _ephemeral_db_path()
    service = research_memory.ResearchMemoryService(db_path=db_file)
    graph_status, graph_caveats = _graph_snapshot_status(graph_snapshot_index_path)
    samples: list[dict[str, Any]] = []
    accepted_fragment_count = 0
    duplicate_rejection_count = 0
    appended_evidence_count = 0

    for sample in source_report.get("samples", []):
        if not isinstance(sample, dict) or sample.get("status") != "packet_ready":
            continue
        metadata = (
            sample.get("safeMetadata") if isinstance(sample.get("safeMetadata"), dict) else {}
        )
        sample_id = _safe_token(sample.get("sampleId") or metadata.get("case_id") or "unknown")
        query_text = _query_text(metadata)
        query_result = service.query_research_memory(query_text, component_keys=[], limit=5)
        dedupe_ref = str(query_result["dedupeQueryRef"])
        payload = _fragment_payload(sample, metadata)

        initial = service.propose_research_fragments(payload, dedupe_query_ref=dedupe_ref)
        fragment_id = _accepted_or_existing_fragment_id(initial)
        if initial.get("status") == "accepted":
            accepted_fragment_count += len(initial.get("fragmentIds") or [])

        duplicate = service.propose_research_fragments(payload, dedupe_query_ref=dedupe_ref)
        if duplicate.get("errorCode") == "duplicate_fragment_candidate":
            duplicate_rejection_count += 1
            fragment_id = fragment_id or _accepted_or_existing_fragment_id(duplicate)

        append_result: dict[str, Any] = {
            "status": "skipped",
            "errorCode": "missing_fragment_id",
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }
        if fragment_id:
            append_result = service.append_evidence_to_fragment(
                fragment_id=fragment_id,
                source_case_refs=[f"case:{sample_id}:toolcall-acceptance"],
                safe_evidence_refs=[
                    _safe_ref("packet-safe-hash", sample.get("packetSafeHash")),
                    _safe_ref("source-hash", sample.get("sourceHash")),
                    "toolcall-acceptance:duplicate-evidence",
                ],
                game_patch=_metadata_value(metadata, "gamePatch", "unknown"),
                passive_tree_version=_metadata_value(metadata, "passiveTreeVersion", "unknown"),
                pob_version_or_commit="unknown",
                visibility=_metadata_value(metadata, "visibility", "creator_visible"),
                split=_metadata_value(metadata, "split", "train_context"),
                knowledge_scope=_metadata_value(metadata, "knowledgeScope", "global_seed"),
                confidence="low",
            )
            if append_result.get("status") == "accepted":
                appended_evidence_count += 1

        samples.append(
            {
                "sampleId": sample_id,
                "safeSourceRef": _safe_ref("source-hash", sample.get("sourceHash")),
                "packetSafeHashRef": _safe_ref("packet-safe-hash", sample.get("packetSafeHash")),
                "class": _metadata_value(metadata, "class", ""),
                "ascendancy": _metadata_value(metadata, "ascendancy", ""),
                "mainSkill": _metadata_value(metadata, "mainSkill", ""),
                "queryStatus": query_result.get("status"),
                "dedupeQueryRef": dedupe_ref,
                "initialProposalStatus": initial.get("status"),
                "fragmentId": fragment_id,
                "duplicateProposalStatus": duplicate.get("status"),
                "duplicateErrorCode": duplicate.get("errorCode"),
                "appendEvidenceStatus": append_result.get("status"),
                "evidenceCountAfterAppend": append_result.get("evidenceCount"),
                "noRawMatureBuildMaterial": True,
            }
        )

    status = "fragment_only_toolcall_acceptance_completed" if samples else "no_packet_ready_samples"
    report = {
        "reportId": "phase4-researcher-toolcall-e2e-v1",
        "inputReportId": _safe_token_field("reportId", source_report.get("reportId")),
        "status": status,
        "safeArtifactOnly": True,
        "sampleCount": len(samples),
        "acceptedFragmentCount": accepted_fragment_count,
        "duplicateRejectionCount": duplicate_rejection_count,
        "appendedEvidenceCount": appended_evidence_count,
        "semanticEdgeStatus": graph_status,
        "semanticEndpointAssessment": _semantic_endpoint_assessment(graph_status, samples),
        "semanticEdgeCaveats": graph_caveats,
        "samples": samples,
        "caveats": [
            "This acceptance run used only the safe packet report, not transient raw packet files.",
            "Fragment ingestion exercised query_research_memory, propose_research_fragments, duplicate rejection, and append_evidence_to_fragment.",
            "Semantic edge submission remains blocked until Phase 3 graph snapshot resolution is available for the sampled components.",
        ],
    }
    _assert_safe_report(report)
    return report


def write_toolcall_acceptance_report(
    *,
    input_report: str | Path = PACKET_REPORT,
    db_path: str | Path | None = None,
    graph_snapshot_index_path: str | Path | None = None,
    json_output: str | Path = JSON_OUTPUT,
    md_output: str | Path = MD_OUTPUT,
) -> dict[str, Any]:
    report = build_toolcall_acceptance_report(
        input_report=input_report,
        db_path=db_path,
        graph_snapshot_index_path=graph_snapshot_index_path,
    )
    Path(json_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(md_output).write_text(_markdown(report), encoding="utf-8")
    return report


def _validate_input_report(source_report: dict[str, Any]) -> None:
    if source_report.get("safeArtifactOnly") is not True:
        raise ValueError("input report must be safe-only before tool-call acceptance")
    if source_report.get("status") != "ready_for_external_researcher":
        raise ValueError("input report must be ready_for_external_researcher")
    if not isinstance(source_report.get("samples"), list):
        raise ValueError("input report samples must be a list")
    _safe_token_field("reportId", source_report.get("reportId"))
    for index, sample in enumerate(source_report["samples"]):
        if not isinstance(sample, dict):
            raise ValueError(f"samples[{index}] must be an object")
        _safe_token_field(f"samples[{index}].sampleId", sample.get("sampleId"))
        _safe_hash_field(f"samples[{index}].sourceHash", sample.get("sourceHash"))
        _safe_hash_field(f"samples[{index}].packetSafeHash", sample.get("packetSafeHash"))
    flags = _copyability_flags_for_safe_text(source_report)
    if flags:
        raise ValueError(f"input report failed copy-safety scan: {', '.join(flags)}")
    forbidden = copy_safety.find_forbidden_paths(source_report)
    if forbidden:
        raise ValueError("input report contains forbidden raw fields")


def _fragment_payload(sample: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    sample_id = _safe_token(sample.get("sampleId") or metadata.get("case_id") or "unknown")
    main_skill = _metadata_value(metadata, "mainSkill", "unknown skill")
    class_name = _metadata_value(metadata, "class", "unknown class")
    ascendancy = _metadata_value(metadata, "ascendancy", "unknown ascendancy")
    game_patch = _metadata_value(metadata, "gamePatch", "unknown")
    tree_version = _metadata_value(metadata, "passiveTreeVersion", "unknown")
    lifecycle = _metadata_value(metadata, "lifecycleStage", "unknown_lifecycle")
    return {
        "schema_version": 4,
        "fragments": [
            {
                "fragment_type": "research_acceptance_caveat",
                "title": f"{main_skill} mature sample requires graph and Judge validation",
                "summary": (
                    f"{class_name}/{ascendancy} safe metadata identifies a mature {main_skill} "
                    "research sample, but this fragment only records that the sample is ready for "
                    "tool-driven external analysis."
                ),
                "reusable_principle": (
                    "Treat mature PoB samples as research leads, not recipes: resolve components "
                    "through Phase 3 graph tools and verify mechanics with Judge before planner use."
                ),
                "source_case_refs": [f"case:{sample_id}"],
                "safe_evidence_refs": [
                    _safe_ref("packet-safe-hash", sample.get("packetSafeHash")),
                    _safe_ref("source-hash", sample.get("sourceHash")),
                ],
                "confidence": "low",
                "copyability_risk": "low",
                "lifecycle_stages": [lifecycle],
                "modelability": _modelability(metadata),
                "verification_tasks": [
                    "Resolve every proposed skill, support, item, passive, or mechanic endpoint with resolve_graph_component.",
                    "Run Judge/modelability checks before promoting any numeric or planner-facing claim.",
                ],
                "component_keys": [],
                "conditions": [
                    "Only safe metadata and safe hashes were durable in this acceptance run.",
                    "Semantic edge proposals are deferred until graph snapshot resolution is available.",
                ],
                "risks": [
                    "Mature samples can hide leveling gates, budget thresholds, or unmodelled mechanics."
                ],
                "game_patch": game_patch,
                "passive_tree_version": tree_version,
                "pob_version_or_commit": "unknown",
                "visibility": _metadata_value(metadata, "visibility", "creator_visible"),
                "split": _metadata_value(metadata, "split", "train_context"),
                "knowledge_scope": _metadata_value(metadata, "knowledgeScope", "global_seed"),
            }
        ],
        "semantic_edges": [],
    }


def _query_text(metadata: dict[str, Any]) -> str:
    parts = [
        _metadata_value(metadata, "mainSkill", ""),
        _metadata_value(metadata, "class", ""),
        _metadata_value(metadata, "ascendancy", ""),
        "mature sample validation caveat",
    ]
    return " ".join(part for part in parts if part)


def _accepted_or_existing_fragment_id(result: dict[str, Any]) -> str | None:
    ids = result.get("fragmentIds")
    if isinstance(ids, list) and ids:
        return str(ids[0])
    proposal_id = result.get("proposalId")
    if isinstance(proposal_id, str) and proposal_id.startswith("rf-"):
        return proposal_id
    facts = result.get("facts")
    if isinstance(facts, dict):
        existing = facts.get("existingFragmentIds")
        if isinstance(existing, list) and existing:
            return str(existing[0])
    return None


def _graph_snapshot_status(index_path: str | Path | None) -> tuple[str, list[str]]:
    path = (
        Path(index_path)
        if index_path is not None
        else paths.user_data_dir() / "physical_graph" / "snapshot_index.sqlite"
    )
    rows = physical_graph.list_registered_snapshots(path)
    if not rows:
        return "blocked_graph_snapshot", [
            "missing registered snapshot index: user_data/physical_graph/snapshot_index.sqlite"
        ]
    latest = next((row for row in rows if row["is_latest"]), rows[0])
    snapshot_path = Path(str(latest.get("snapshot_path") or ""))
    if not snapshot_path.exists():
        return "blocked_graph_snapshot", ["registered snapshot file is missing"]
    return "available_not_executed_fragment_only_acceptance", [
        "fragment-only acceptance intentionally did not submit semantic edges"
    ]


def _semantic_endpoint_assessment(
    graph_status: str, samples: list[dict[str, Any]]
) -> dict[str, Any]:
    safe_metadata_names = sorted(
        {
            str(sample.get("mainSkill"))
            for sample in samples
            if str(sample.get("mainSkill") or "").strip()
        }
    )
    if graph_status == "blocked_graph_snapshot":
        return {
            "classification": "graph_snapshot_unavailable",
            "hallucinationVerdict": "not_assessed",
            "safeMetadataCandidateNames": safe_metadata_names,
            "candidateNameProvenance": "safe_metadata_unresolved_label",
            "missingEndpointKeys": [],
            "reason": (
                "No Phase 3 graph snapshot was available for resolver checks. Real mature-build "
                "entities must not be marked hallucinated from this fragment-only acceptance run."
            ),
            "requiresStaticSourceReview": True,
        }
    return {
        "classification": "not_executed_fragment_only_acceptance",
        "hallucinationVerdict": "not_assessed",
        "safeMetadataCandidateNames": safe_metadata_names,
        "candidateNameProvenance": "safe_metadata_unresolved_label",
        "missingEndpointKeys": [],
        "reason": "This run intentionally did not submit semantic edges.",
        "requiresStaticSourceReview": False,
    }


def _metadata_value(metadata: dict[str, Any], key: str, default: str) -> str:
    value = metadata.get(key, default)
    text = " ".join(str(value).split())
    if copy_safety.copyability_flags(text):
        raise ValueError(f"metadata field {key} failed copy-safety scan")
    return text[:120] if text else default


def _modelability(metadata: dict[str, Any]) -> str:
    value = _metadata_value(metadata, "pobModelability", "unknown")
    return value if value in {"full", "partial", "not_modelable", "unknown"} else "unknown"


def _safe_ref(prefix: str, value: Any) -> str:
    text = "".join(ch for ch in str(value or "unknown").lower() if ch.isalnum())[:16]
    return f"{prefix}:{text or 'unknown'}"


def _safe_token(value: Any) -> str:
    text = str(value or "unknown").strip()
    _reject_token_copyable("sampleId", text)
    safe = "".join(ch if ch.isalnum() or ch in "_:-." else "-" for ch in text)
    return safe[:80] or "unknown"


def _safe_token_field(field: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    _reject_token_copyable(field, text)
    if not TOKEN_RE.fullmatch(text):
        raise ValueError(f"{field} must be a safe token")
    return text


def _safe_hash_field(field: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    _reject_token_copyable(field, text)
    if not re.fullmatch(r"[A-Fa-f0-9]{16,128}", text):
        raise ValueError(f"{field} must be a hex safe hash")
    return text.lower()


def _reject_token_copyable(field: str, text: str) -> None:
    lower = text.lower()
    if any(marker.lower() in lower for marker in RAW_MARKERS):
        raise ValueError(f"{field} failed copy-safety scan")
    if re.search(
        r"(?:https?://|www\.|pobb\.in|pastebin\.com|poe\.ninja|pathofexile\.com)",
        lower,
    ):
        raise ValueError(f"{field} failed copy-safety scan")
    flags = set(copy_safety.copyability_flags(text))
    flags.discard("full_gem_link_like")
    if flags:
        raise ValueError(f"{field} failed copy-safety scan")


def _assert_safe_report(report: dict[str, Any]) -> None:
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    leaks = [marker for marker in RAW_MARKERS if marker in serialized]
    if leaks:
        raise ValueError(f"unsafe durable report markers detected: {', '.join(leaks)}")
    if "transientPacketPath" in serialized or "transientPromptPath" in serialized:
        raise ValueError("transient packet paths must not be copied into toolcall reports")
    flags = _copyability_flags_for_safe_text(report)
    if flags:
        raise ValueError(f"durable report failed copy-safety scan: {', '.join(flags)}")
    forbidden = copy_safety.find_forbidden_paths(report)
    if forbidden:
        raise ValueError("durable report contains forbidden raw fields")


def _copyability_flags_for_safe_text(value: Any) -> list[str]:
    flags: set[str] = set()
    for text in _iter_safe_text_values(value):
        flags.update(copy_safety.copyability_flags(text))
    return sorted(flags)


def _iter_safe_text_values(value: Any, *, key: str = "") -> list[str]:
    text_fields = {
        "class",
        "ascendancy",
        "mainSkill",
        "summary",
        "reusablePrinciple",
        "reusable_principle",
        "conditions",
        "risks",
        "verificationTasks",
        "verification_tasks",
        "caveats",
        "semanticEdgeCaveats",
    }
    if isinstance(value, dict):
        values: list[str] = []
        for child_key, child in value.items():
            key_text = str(child_key)
            if key_text in text_fields:
                values.extend(_iter_text_leaves(child))
            else:
                values.extend(_iter_safe_text_values(child, key=key_text))
        return values
    if isinstance(value, list):
        values = []
        for child in value:
            values.extend(_iter_safe_text_values(child, key=key))
        return values
    return []


def _iter_text_leaves(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        values: list[str] = []
        for child in value:
            values.extend(_iter_text_leaves(child))
        return values
    if isinstance(value, dict):
        values = []
        for child in value.values():
            values.extend(_iter_text_leaves(child))
        return values
    return []


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 4 Researcher Tool-call E2E Report",
        "",
        f"- Status: `{report['status']}`",
        f"- Safe artifact only: `{report['safeArtifactOnly']}`",
        f"- Samples: `{report['sampleCount']}`",
        f"- Accepted fragments: `{report['acceptedFragmentCount']}`",
        f"- Duplicate rejections: `{report['duplicateRejectionCount']}`",
        f"- Evidence appends: `{report['appendedEvidenceCount']}`",
        f"- Semantic edge status: `{report['semanticEdgeStatus']}`",
        "",
        "## Samples",
        "",
    ]
    assessment = report.get("semanticEndpointAssessment") or {}
    if isinstance(assessment, dict):
        lines[9:9] = [
            f"- Endpoint assessment: `{assessment.get('classification')}` / `{assessment.get('hallucinationVerdict')}`",
            f"- Candidate name provenance: `{assessment.get('candidateNameProvenance')}`",
        ]
    for sample in report["samples"]:
        lines.extend(
            [
                f"- `{sample['sampleId']}`: fragment `{sample.get('fragmentId')}`",
                f"  - query / propose / duplicate / append: `{sample.get('queryStatus')}` / `{sample.get('initialProposalStatus')}` / `{sample.get('duplicateErrorCode')}` / `{sample.get('appendEvidenceStatus')}`",
                f"  - class / ascendancy / skill: `{sample.get('class')}` / `{sample.get('ascendancy')}` / `{sample.get('mainSkill')}`",
            ]
        )
    lines.extend(["", "## Caveats", ""])
    lines.extend(f"- {item}" for item in report["caveats"])
    lines.extend(f"- {item}" for item in report["semanticEdgeCaveats"])
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-report", default=str(PACKET_REPORT))
    parser.add_argument(
        "--db-path",
        default=None,
        help=(
            "Optional explicit mature-learning DB path. If omitted, an ephemeral acceptance DB "
            "under the OS temp directory is used."
        ),
    )
    parser.add_argument(
        "--graph-snapshot-index",
        default=str(paths.user_data_dir() / "physical_graph" / "snapshot_index.sqlite"),
    )
    parser.add_argument("--json-output", default=str(JSON_OUTPUT))
    parser.add_argument("--md-output", default=str(MD_OUTPUT))
    args = parser.parse_args(argv)
    db_path = Path(args.db_path) if args.db_path else _ephemeral_db_path()

    report = write_toolcall_acceptance_report(
        input_report=args.input_report,
        db_path=db_path,
        graph_snapshot_index_path=args.graph_snapshot_index,
        json_output=args.json_output,
        md_output=args.md_output,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["sampleCount"] else 1


def _ephemeral_db_path() -> Path:
    root = Path(tempfile.mkdtemp(prefix="poe-bd-creator-phase4-toolcall-"))
    return root / "mature_learning_acceptance.sqlite"


if __name__ == "__main__":
    raise SystemExit(main())
