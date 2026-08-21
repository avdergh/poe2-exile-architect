"""Prepare one-build-at-a-time Phase 4.5 deep Researcher packets.

This script may transiently decode user-supplied PoB import codes and may run a
non-authoritative Judge selected-skill probe. Durable reports stay safe-only:
no raw PoB code, raw XML, full gear, full passive path, full gem/support links,
complete URLs, or transient packet paths.
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
from server.knowledge import copy_safety, pob_xml_meta, research_packet  # noqa: E402

JSON_OUTPUT = REPO_ROOT / "phase4_deep_researcher_pass_report.json"
MD_OUTPUT = REPO_ROOT / "phase4_deep_researcher_pass_report.md"
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
    "researcher_prompt.txt",
)

DESIGN_AXES = (
    "identity",
    "character_shell",
    "primary_skill_package",
    "secondary_skill_package",
    "passive_tree_shape",
    "itemization",
    "scaling_axis",
    "resource_engine",
    "defense_layers",
    "mechanic_engine",
    "rotation_playstyle",
    "transition_gates",
    "failure_modes",
    "modelability_caveats",
    "variant_relation",
)

AXIS_STATUSES = (
    "observed",
    "weak_signal",
    "not_observed",
    "not_extractable_from_payload",
    "requires_judge_verification",
)


def build_deep_pass_report(
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
        sample_id = f"phase4_deep_user_pob_{index:03d}"
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
        diagnostics = _programmatic_diagnostics(
            source,
            sample_id=sample_id,
            raw_imported_main_skill=str(safe_metadata.get("mainSkill") or ""),
        )
        case = {
            "safeMetadata": safe_metadata,
            "rawContext": {
                "rawImportCode": source,
                "rawXml": xml,
                "programmaticDiagnostics": diagnostics,
                "sourcePayload": {
                    "kind": "user_supplied_pob_code",
                    "sourceHash": source_hash,
                },
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
        prompt_path = packet_path.with_name("deep_researcher_prompt.txt")
        prompt_text = render_deep_researcher_prompt(
            packet,
            current_patch=current_patch,
            passive_tree_version=passive_tree_version,
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
                "diagnosticSummary": _diagnostic_summary(diagnostics),
                "promptInstructionChecks": _prompt_checks(prompt_text),
                "nextResearchFlow": [
                    "read exactly one transient packet",
                    "analyze raw evidence directly",
                    "treat programmatic diagnostics as non-authoritative",
                    "resolve graph endpoints before durable proposals",
                    "submit only copy-safe observations/pattern candidates",
                ],
                "noRawMatureBuildMaterial": True,
            }
        )

    ready_count = sum(1 for sample in samples if sample["status"] == "packet_ready")
    status = "ready_for_deep_researcher" if ready_count == len(samples) else "needs_input_repair"
    report = {
        "reportId": "phase4-deep-researcher-pass-v1",
        "status": status,
        "sampleCount": len(samples),
        "readyCount": ready_count,
        "safeArtifactOnly": True,
        "samples": samples,
        "caveats": [
            "Raw evidence exists only in transient packet files returned to the local caller.",
            "Programmatic diagnostics are non-authoritative and must not override Researcher analysis.",
            "Run one external Researcher/subagent turn per build sample to avoid cross-case attention dilution.",
        ],
    }
    return report, transient_paths


def render_deep_researcher_prompt(
    packet: dict[str, Any],
    *,
    current_patch: str,
    passive_tree_version: str,
) -> str:
    packet_id = str(packet.get("packetId") or "")
    safe_hash = str(packet.get("safeHash") or "")
    metadata = packet.get("safeMetadata") if isinstance(packet.get("safeMetadata"), dict) else {}
    diagnostics = {}
    raw_context = packet.get("rawContext") if isinstance(packet.get("rawContext"), dict) else {}
    if isinstance(raw_context.get("programmaticDiagnostics"), dict):
        diagnostics = raw_context["programmaticDiagnostics"]
    raw_main = str(diagnostics.get("rawImportedMainSkill") or metadata.get("mainSkill") or "")
    judge_candidate = str(diagnostics.get("judgeSelectedSkillCandidate") or "")
    axes = "\n".join(f"- {axis}" for axis in DESIGN_AXES)
    statuses = ", ".join(AXIS_STATUSES)
    return f"""# ROLE
You are the external Deep Researcher Agent for PoE2 BD Creator.

You are analyzing one build sample only. Do not compare against other raw builds in this turn.
The packet is quarantine-only mature BD evidence. You may inspect it, but you MUST NOT output raw PoB code,
raw XML, full gear tables, full passive paths, full gem/support links, full URLs, account names, or copied guide prose.

# PACKET
- packetId: {packet_id}
- safeHash: {safe_hash}
- Patch Version: {current_patch}
- Passive Tree Version: {passive_tree_version}

# SNAPSHOT TRAP WARNING
Programmatic diagnostics are NON-AUTHORITATIVE.
- rawImportedMainSkill: {raw_main}
- judgeSelectedSkillCandidate: {judge_candidate or "none"}

Do not treat rawImportedMainSkill as ground truth.
Do not treat judgeSelectedSkillCandidate as ground truth.
If they conflict, inspect the raw skill groups, supports, itemization, passive clues, resource layer, and damage/rotation context yourself.
You may mark multiple roles such as primary_damage_candidate, clear_skill, boss_skill, generator, transformer,
payoff, reservation, defensive_buff, movement, trigger_host, support_modifier, unique_enabler, or transition_gate.

# REQUIRED DESIGN AXIS REVIEW
For each axis below, output one status from: {statuses}.
Do not force every axis to produce a finding. If the payload does not prove an axis, say so.

{axes}

# EXTRACTION GOAL
Identify reusable, non-copyable tactical knowledge:
- build identity and character shell;
- primary and secondary skill package roles;
- support pairs, but never full support-link recipes;
- key passive/notable/keystone and unique item signals;
- scaling axis, resource/Spirit/reservation engine, defense layers;
- mechanic chain: generator -> transformer -> payoff;
- transition gates, failure modes, modelability caveats, and variant relations.

# RESOLUTION AND MEMORY RULES
- Query existing memory before proposing durable new knowledge.
- Resolve graph endpoints before proposing edges or patterns.
- Missing or ambiguous endpoints must become caveats or mapping tasks, not hallucination claims.
- Mature BD observations are advisory planner context, not hard legality or numerical proof.
- If you cannot call project tools in this environment, return a safe-only structured review for the controller to submit through tools.

# OUTPUT SHAPE
Return safe-only structured content with:
- caseSummaryZh;
- designAxisReview: one item per required axis with status, evidenceSummaryZh, candidateComponents, caveats;
- primarySkillAssessment: rawImportedMainSkill, judgeSelectedSkillCandidate, researcherAssessment, confidence, caveats;
- candidateObservations: copy-safe BuildDesignObservation candidates;
- candidatePatterns: only if this single case provides a useful case_observation, with a typed Agent scope review rather than language-keyword checks;
- resolverRequests: endpoint names that should be resolved before durable write;
- verificationTasks;
- noRawMatureBuildMaterial: true.
"""


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
        "keypoints": ["User-supplied mature PoB code for one-case deep Researcher analysis."],
    }


def _programmatic_diagnostics(
    source: str,
    *,
    sample_id: str,
    raw_imported_main_skill: str,
) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "authority": "non_authoritative",
        "rawImportedMainSkill": raw_imported_main_skill,
        "judgeProbeStatus": "not_run",
        "judgeSelectedSkillCandidate": "",
        "selectionCaveats": [
            "Programmatic selected-skill probe is a snapshot-trap warning, not ground truth."
        ],
    }
    try:
        probe = _run_judge_probe(source, sample_id)
    except Exception as exc:
        diagnostics["judgeProbeStatus"] = "failed"
        diagnostics["safeError"] = _safe_error(str(exc))
        return diagnostics
    summary = probe.get("summary") if isinstance(probe.get("summary"), dict) else {}
    breakdown = probe.get("scoreBreakdown") if isinstance(probe.get("scoreBreakdown"), dict) else {}
    offense = breakdown.get("offense") if isinstance(breakdown.get("offense"), dict) else {}
    candidate = str(summary.get("judgeSelectedSkill") or offense.get("skillName") or "")
    caveats = [str(item) for item in probe.get("caveats") or [] if str(item).strip()]
    diagnostics.update(
        {
            "judgeProbeStatus": "failed" if probe.get("errorKind") else "ok",
            "judgeSelectedSkillCandidate": candidate,
            "judgeOffenseProbe": {
                key: offense.get(key)
                for key in (
                    "skillName",
                    "skillGroupIndex",
                    "provenance",
                    "evidenceLevel",
                    "sourceMetricDetail",
                    "isMinion",
                    "activeSkillCount",
                    "activeMinionLimit",
                    "caveats",
                )
                if offense.get(key) is not None
            },
            "selectionCaveats": caveats
            + ["Programmatic selected-skill probe is a snapshot-trap warning, not ground truth."],
        }
    )
    if probe.get("errorKind"):
        diagnostics["safeError"] = _safe_error(str(probe.get("errorKind")))
    return diagnostics


def _run_judge_probe(source: str, snapshot_id: str) -> dict[str, Any]:
    from scripts import run_judge_user_samples

    return run_judge_user_samples.evaluate_source(source, snapshot_id=snapshot_id)


def _diagnostic_summary(diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        "authority": "non_authoritative",
        "rawImportedMainSkill": diagnostics.get("rawImportedMainSkill") or "",
        "judgeProbeStatus": diagnostics.get("judgeProbeStatus") or "unknown",
        "judgeSelectedSkillCandidate": diagnostics.get("judgeSelectedSkillCandidate") or "",
        "selectionCaveats": list(diagnostics.get("selectionCaveats") or []),
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
        "singleCaseOnly": "one build sample only" in prompt_text,
        "judgeProbeNonAuthoritative": "Programmatic diagnostics are NON-AUTHORITATIVE"
        in prompt_text
        and "Do not treat judgeSelectedSkillCandidate as ground truth" in prompt_text,
        "designAxisStatusRequired": "not_extractable_from_payload" in prompt_text
        and "Do not force every axis to produce a finding" in prompt_text,
        "copySafetyRedLines": "MUST NOT output raw PoB code" in prompt_text,
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
        "rawImportedMainSkill",
        "judgeSelectedSkillCandidate",
        "selectionCaveats",
        "keypoints",
        "caveats",
        "nextResearchFlow",
    }
    if isinstance(value, dict):
        out: list[str] = []
        for child_key, child in value.items():
            out.extend(_iter_safe_text_values(child, key=str(child_key)))
        return out
    if isinstance(value, list):
        out: list[str] = []
        for child in value:
            out.extend(_iter_safe_text_values(child, key=key))
        return out
    if isinstance(value, str) and key in text_fields:
        return [value]
    return []


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 4.5 Deep Researcher Pass",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Samples: `{report.get('sampleCount')}`",
        f"- Ready: `{report.get('readyCount')}`",
        "",
        "## Samples",
        "",
    ]
    for sample in report.get("samples", []):
        metadata = sample.get("safeMetadata") or {}
        diagnostic = sample.get("diagnosticSummary") or {}
        lines.extend(
            [
                f"- `{sample.get('sampleId')}`: `{sample.get('status')}`",
                (
                    f"  - class / ascendancy / raw main: `{metadata.get('class', '')}` / "
                    f"`{metadata.get('ascendancy', '')}` / `{metadata.get('mainSkill', '')}`"
                ),
                (
                    "  - non-authoritative judge candidate: "
                    f"`{diagnostic.get('judgeSelectedSkillCandidate', '')}` "
                    f"(`{diagnostic.get('judgeProbeStatus', '')}`)"
                ),
            ]
        )
    lines.extend(
        [
            "",
            "## Caveats",
            "",
        ]
    )
    for caveat in report.get("caveats", []):
        lines.append(f"- {caveat}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-file", action="append", required=True)
    parser.add_argument("--temp-root")
    parser.add_argument("--ttl-seconds", type=int, default=24 * 60 * 60)
    parser.add_argument("--current-patch", default="unknown")
    parser.add_argument("--passive-tree-version", default="unknown")
    args = parser.parse_args(argv)
    report, transient = build_deep_pass_report(
        args.source_file,
        temp_root=args.temp_root,
        ttl_seconds=args.ttl_seconds,
        current_patch=args.current_patch,
        passive_tree_version=args.passive_tree_version,
    )
    write_report(report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "sampleCount": report["sampleCount"],
                "readyCount": report["readyCount"],
                "transientCount": len(transient),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "ready_for_deep_researcher" else 1


if __name__ == "__main__":
    raise SystemExit(main())
