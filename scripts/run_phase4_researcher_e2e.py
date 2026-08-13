"""Prepare Phase 4 external Researcher E2E packets from local PoB codes.

The durable report is safe-only. Raw import codes and decoded XML are written only to a
tempfile-backed transient packet directory for handoff to an external Researcher Agent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.compute import pob_code  # noqa: E402
from server.knowledge import copy_safety, pob_xml_meta, research_packet, research_prompt  # noqa: E402

JSON_OUTPUT = REPO_ROOT / "phase4_researcher_e2e_report.json"
MD_OUTPUT = REPO_ROOT / "phase4_researcher_e2e_report.md"
_BUILD_ATTR = re.compile(r"<Build\b([^>]*)>", re.IGNORECASE)
_ATTR = re.compile(r'(\w+)="([^"]*)"')
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
)


def build_acceptance_report(
    source_files: list[str | Path],
    *,
    temp_root: str | Path | None = None,
    ttl_seconds: int = 24 * 60 * 60,
    current_patch: str = "unknown",
    passive_tree_version: str = "unknown",
) -> tuple[dict[str, Any], list[dict[str, Path]]]:
    transient_paths: list[dict[str, Path]] = []
    samples: list[dict[str, Any]] = []
    root = Path(temp_root) if temp_root is not None else Path(tempfile.gettempdir())
    for index, source_file in enumerate(source_files, start=1):
        path = Path(source_file)
        source = path.read_text(encoding="utf-8").strip()
        source_hash = _safe_hash(source)
        sample_id = f"phase4_user_pob_{index:03d}"
        try:
            xml = pob_code.to_xml(source)
        except pob_code.PobCodeError as exc:
            samples.append(
                {
                    "sampleId": sample_id,
                    "status": "import_failed",
                    "sourceHash": source_hash,
                    "errorCode": "build_import_failed",
                    "safeError": _safe_error(str(exc)),
                    "noRawMatureBuildMaterial": True,
                }
            )
            continue

        safe_metadata = _safe_metadata(
            sample_id=sample_id,
            source_hash=source_hash,
            xml=xml,
            current_patch=current_patch,
            passive_tree_version=passive_tree_version,
        )
        case = {
            "safeMetadata": safe_metadata,
            "rawContext": {
                "rawImportCode": source,
                "rawXml": xml,
                "sourcePayload": {"kind": "user_supplied_pob_code", "sourceHash": source_hash},
            },
        }
        packet_result = research_packet.build_research_packet(
            case,
            persist_for_transport=True,
            ttl_seconds=ttl_seconds,
            temp_root=root,
        )
        packet = packet_result["packet"]
        packet_path = Path(packet_result["packetPath"])
        prompt_path = packet_path.with_name("researcher_prompt.txt")
        prompt_text = research_prompt.render_researcher_prompt(
            packet,
            current_patch=current_patch,
            passive_tree_version=passive_tree_version,
            user_language="zh-CN",
        )
        prompt_path.write_text(prompt_text, encoding="utf-8")
        transient_paths.append({"packetPath": packet_path, "promptPath": prompt_path})
        samples.append(
            {
                "sampleId": sample_id,
                "status": "packet_ready",
                "sourceHash": source_hash,
                "packetId": packet["packetId"],
                "packetSafeHash": packet["safeHash"],
                "safeMetadata": safe_metadata,
                "promptInstructionChecks": _prompt_checks(prompt_text),
                "nextToolFlow": [
                    "query_research_memory",
                    "graph_tool_query(resolve_graph_component)",
                    "propose_research_fragments",
                    "propose_semantic_edges",
                ],
                "noRawMatureBuildMaterial": True,
            }
        )

    ready_count = sum(1 for sample in samples if sample["status"] == "packet_ready")
    status = (
        "ready_for_external_researcher" if ready_count == len(samples) else "needs_input_repair"
    )
    report = {
        "reportId": "phase4-researcher-e2e-user-pob-v1",
        "status": status,
        "sampleCount": len(samples),
        "readyCount": ready_count,
        "safeArtifactOnly": True,
        "samples": samples,
        "caveats": [
            (
                "Raw PoB code/XML are present only in transient packet files returned to the "
                "local caller; durable reports do not contain transient paths."
            ),
            "No internal LLM/provider loop was run; submit the prompt files to an external Researcher Agent.",
        ],
    }
    return report, transient_paths


def write_report(report: dict[str, Any]) -> None:
    _assert_safe_report(report)
    JSON_OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    MD_OUTPUT.write_text(_markdown(report), encoding="utf-8")


def _safe_metadata(
    *,
    sample_id: str,
    source_hash: str,
    xml: str,
    current_patch: str,
    passive_tree_version: str,
) -> dict[str, Any]:
    attrs = _build_attributes(xml)
    return {
        "case_id": sample_id,
        "sourceType": "user_supplied_pob_code",
        "sourceRef": f"user-pob-code:{source_hash[:12]}",
        "sourceHash": source_hash,
        "league": "unknown",
        "gamePatch": current_patch,
        "passiveTreeVersion": passive_tree_version,
        "class": attrs.get("className") or "",
        "ascendancy": attrs.get("ascendClassName") or "",
        "level": attrs.get("level") or "",
        "mainSkill": _main_skill(xml) or "",
        "lifecycleStage": "unknown_lifecycle",
        "budgetBand": "unknown",
        "pobModelability": "partial",
        "visibility": "creator_visible",
        "split": "train_context",
        "knowledgeScope": "global_seed",
        "evidenceType": "user_supplied_pob_code",
        "freshnessStatus": "unknown",
        "compatibilityStatus": "unknown",
        "keypoints": ["User-supplied mature PoB code for Phase 4 external Researcher E2E."],
    }


def _build_attributes(xml: str) -> dict[str, str]:
    match = _BUILD_ATTR.search(xml)
    if not match:
        return {}
    return {key: value for key, value in _ATTR.findall(match.group(1))}


def _main_skill(xml: str) -> str | None:
    return pob_xml_meta.main_skill_from_pob_xml(xml)


def _prompt_checks(prompt_text: str) -> dict[str, bool]:
    return {
        "toolDriven": "MUST NOT output the final JSON as regular text" in prompt_text,
        "queryBeforePropose": "query_research_memory" in prompt_text
        and "dedupeQueryRef" in prompt_text,
        "resolveBeforeEdge": "resolve_graph_component" in prompt_text
        and "source_resolution" in prompt_text,
        "noRoutineValidatePreflight": "Do not use validate_researcher_output as a routine preflight"
        in prompt_text,
        "copySafetyRedLines": "NEVER output raw PoB code" in prompt_text,
    }


def _safe_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_error(message: str) -> str:
    flags = copy_safety.copyability_flags(message)
    if flags:
        return ",".join(flags)
    redacted = re.sub(
        r"(?:https?://|www\.|pobb\.in|pastebin\.com|poe\.ninja|pathofexile\.com)[^\s)]+",
        "[redacted-url]",
        message,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(r"[A-Za-z0-9_+/\-=]{80,}", "[redacted-long-token]", redacted)
    return redacted[:240]


def _assert_safe_report(report: dict[str, Any]) -> None:
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    leaks = [marker for marker in RAW_MARKERS if marker in serialized]
    if leaks:
        raise ValueError(f"unsafe durable report markers detected: {', '.join(leaks)}")
    if copy_safety.find_forbidden_paths(report):
        raise ValueError("unsafe durable report contains forbidden raw fields")
    flags = _copyability_flags_for_safe_text(report)
    if flags:
        raise ValueError(f"unsafe durable report failed copy-safety scan: {', '.join(flags)}")


def _copyability_flags_for_safe_text(value: Any) -> list[str]:
    flags: set[str] = set()
    for text in _iter_safe_text_values(value):
        flags.update(copy_safety.copyability_flags(text))
    return sorted(flags)


def _iter_safe_text_values(value: Any, *, key: str = "") -> list[str]:
    text_fields = {
        "safeError",
        "class",
        "ascendancy",
        "mainSkill",
        "keypoints",
        "caveats",
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
        "# Phase 4 Researcher E2E Report",
        "",
        f"- Status: `{report['status']}`",
        f"- Samples: `{report['sampleCount']}`",
        f"- Ready: `{report['readyCount']}`",
        f"- Safe artifact only: `{report['safeArtifactOnly']}`",
        "",
        "## Samples",
        "",
    ]
    for sample in report["samples"]:
        metadata = sample.get("safeMetadata") or {}
        lines.extend(
            [
                f"- `{sample['sampleId']}`: `{sample['status']}`",
                f"  - source hash: `{sample['sourceHash']}`",
                f"  - class / ascendancy / skill: `{metadata.get('class', '')}` / `{metadata.get('ascendancy', '')}` / `{metadata.get('mainSkill', '')}`",
            ]
        )
        if sample.get("packetId"):
            lines.append(f"  - packet: `{sample['packetId']}`")
    lines.extend(["", "## Caveats", ""])
    lines.extend(f"- {item}" for item in report["caveats"])
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-file", action="append", required=True)
    parser.add_argument("--current-patch", default="unknown")
    parser.add_argument("--passive-tree-version", default="unknown")
    parser.add_argument("--ttl-seconds", type=int, default=24 * 60 * 60)
    args = parser.parse_args(argv)
    report, _transient = build_acceptance_report(
        [Path(value) for value in args.source_file],
        ttl_seconds=args.ttl_seconds,
        current_patch=args.current_patch,
        passive_tree_version=args.passive_tree_version,
    )
    write_report(report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["readyCount"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
