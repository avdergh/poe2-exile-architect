"""Extract safe Phase 4 research fragments from real mature PoB samples.

This script is the local Codex-as-external-Researcher acceptance path. It may decode
user-supplied PoB import codes transiently, but it writes only typed clean fragments and
safe Chinese review artifacts. It does not run an internal model/provider loop and does not
persist PoB code, raw XML, full gear, passive paths, or full gem links.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.compute import pob_code  # noqa: E402
from server.knowledge import copy_safety, research_memory, research_models  # noqa: E402

PACKET_REPORT = REPO_ROOT / "phase4_researcher_e2e_report.json"
ENDPOINT_MAPPING_REPORT = REPO_ROOT / "phase4_reviewed_endpoint_mapping_report.json"
JSON_OUTPUT = REPO_ROOT / "phase4_real_research_extraction_report.json"
MD_OUTPUT = REPO_ROOT / "phase4_real_research_extraction_report.md"

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
TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
SAFE_REF_RE = re.compile(
    r"^(?:case|safe|external-proposal|source-hash|packet-safe-hash|source-url|"
    r"resolver|manual-review|fixture|benchmark|toolcall):[a-z0-9_.:-]{1,180}$"
)
FULL_GEM_LINK_TOKEN_FIELDS = {
    "acceptedStableKey",
    "componentKeys",
    "component_keys",
    "dedupeQueryRef",
    "duplicateErrorCode",
    "endpointMappingReportId",
    "fragmentId",
    "inputReportId",
    "packetId",
    "packetSafeHash",
    "packetSafeHashRef",
    "proposalOrigin",
    "reportId",
    "safeSourceRef",
    "sampleId",
    "sourceHash",
    "status",
    "writeStatus",
}
SAFE_REF_TOKEN_FIELDS = {"source_case_refs", "safe_evidence_refs"}


@dataclass(frozen=True)
class SampleObservation:
    sample_id: str
    class_name: str
    ascendancy: str
    main_skill: str
    level: int | None
    enabled_skill_group_count: int
    item_count: int
    mechanic_tags: tuple[str, ...]
    lifecycle_stage: str
    primary_skill_preview: tuple[str, ...]


def build_real_research_extraction_report(
    *,
    input_report: str | Path = PACKET_REPORT,
    endpoint_mapping_report: str | Path = ENDPOINT_MAPPING_REPORT,
    external_proposal_file: str | Path,
    source_files: list[str | Path] | None = None,
    db_path: str | Path | None = None,
    _source_xml_by_sample_id_for_tests: dict[str, str] | None = None,
) -> dict[str, Any]:
    source_report = json.loads(Path(input_report).read_text(encoding="utf-8"))
    mapping_report = json.loads(Path(endpoint_mapping_report).read_text(encoding="utf-8"))
    _validate_packet_report(source_report)
    _assert_safe_report(mapping_report)

    ready_samples = [
        sample
        for sample in source_report.get("samples", [])
        if isinstance(sample, dict) and sample.get("status") == "packet_ready"
    ]
    xml_by_sample = _source_xml_by_sample_id_for_tests or _decode_source_files(
        ready_samples, source_files
    )
    endpoint_map = _accepted_endpoint_map(mapping_report)
    proposals_by_sample = _load_external_proposals(
        external_proposal_file,
        endpoint_map=endpoint_map,
    )
    service = research_memory.ResearchMemoryService(
        db_path=Path(db_path) if db_path is not None else None
    )

    samples: list[dict[str, Any]] = []
    accepted_count = 0
    duplicate_count = 0
    appended_count = 0
    skipped_count = 0

    for sample in ready_samples:
        metadata = (
            sample.get("safeMetadata") if isinstance(sample.get("safeMetadata"), dict) else {}
        )
        sample_id = _safe_token(sample.get("sampleId") or metadata.get("case_id") or "unknown")
        xml = xml_by_sample.get(sample_id)
        if not xml:
            skipped_count += 1
            samples.append(_skipped_sample(sample, metadata, "missing_transient_source_xml"))
            continue

        observation = _observe_sample(sample_id, metadata, xml)
        accepted_stable_key = endpoint_map.get(sample_id)
        proposal_fragment = proposals_by_sample.get(sample_id)
        if proposal_fragment is None:
            skipped_count += 1
            samples.append(_skipped_sample(sample, metadata, "missing_external_clean_proposal"))
            continue

        fragment_payload = {
            "schema_version": 4,
            "fragments": [proposal_fragment],
            "semantic_edges": [],
        }
        review_fragment = _review_fragment_from_proposal(proposal_fragment)
        component_keys = fragment_payload["fragments"][0]["component_keys"]
        query = _proposal_dedupe_query(proposal_fragment)
        query_result = service.query_research_memory(query, component_keys=component_keys, limit=5)
        proposal_result = service.propose_research_fragments(
            fragment_payload,
            dedupe_query_ref=str(query_result["dedupeQueryRef"]),
        )

        append_result: dict[str, Any] | None = None
        fragment_id = _accepted_or_existing_fragment_id(proposal_result)
        write_status = str(proposal_result.get("status") or "unknown")
        duplicate_error = proposal_result.get("errorCode")
        if proposal_result.get("status") == "accepted":
            accepted_count += len(proposal_result.get("fragmentIds") or [])
        elif proposal_result.get("errorCode") == "duplicate_fragment_candidate" and fragment_id:
            duplicate_count += 1
            append_result = _append_existing_evidence(
                service,
                fragment_id=fragment_id,
                fragment=fragment_payload["fragments"][0],
            )
            if append_result.get("status") == "accepted":
                appended_count += 1
                write_status = "appended_duplicate_evidence"
        else:
            skipped_count += 1

        review_fragment.update(
            {
                "fragmentId": fragment_id,
                "writeStatus": write_status,
                "dedupeQueryRef": query_result["dedupeQueryRef"],
                "duplicateErrorCode": duplicate_error,
                "evidenceCountAfterAppend": append_result.get("evidenceCount")
                if append_result
                else None,
            }
        )
        samples.append(
            _sample_report(
                sample=sample,
                metadata=metadata,
                observation=observation,
                accepted_stable_key=accepted_stable_key,
                fragment=review_fragment,
            )
        )

    status = "real_research_extraction_completed" if samples else "no_packet_ready_samples"
    report = {
        "reportId": "phase4_real_research_extraction_v1",
        "inputReportId": _safe_token_field("reportId", source_report.get("reportId")),
        "endpointMappingReportId": _safe_token_field(
            "mapping.reportId", mapping_report.get("reportId")
        ),
        "status": status,
        "proposalOrigin": "external_clean_proposal",
        "reviewLanguage": "中文审阅 / zh-CN",
        "safeArtifactOnly": True,
        "sampleCount": len(samples),
        "acceptedFragmentCount": accepted_count,
        "duplicateFragmentCount": duplicate_count,
        "appendedEvidenceCount": appended_count,
        "skippedSampleCount": skipped_count,
        "semanticEdgeWrite": {
            "attempted": False,
            "reason": "clean_fragment_extraction_only_no_external_semantic_edge_proposal",
        },
        "samples": samples,
        "caveats": [
            "本轮由 Codex 在当前会话中扮演外部 Researcher；写库内容来自外部 clean proposal artifact。",
            "报告只包含 safe id、safe hash ref、机制级标签和中文摘要；不包含可复刻成熟 BD 的材料。",
            "真实 semantic edge 仍需外部 Researcher clean proposal 携带两端 resolver evidence 后再走 gate。",
        ],
    }
    _assert_safe_report(report)
    return report


def write_real_research_extraction_report(
    *,
    input_report: str | Path = PACKET_REPORT,
    endpoint_mapping_report: str | Path = ENDPOINT_MAPPING_REPORT,
    external_proposal_file: str | Path,
    source_files: list[str | Path] | None = None,
    db_path: str | Path | None = None,
    _source_xml_by_sample_id_for_tests: dict[str, str] | None = None,
    json_output: str | Path = JSON_OUTPUT,
    md_output: str | Path = MD_OUTPUT,
) -> dict[str, Any]:
    report = build_real_research_extraction_report(
        input_report=input_report,
        endpoint_mapping_report=endpoint_mapping_report,
        external_proposal_file=external_proposal_file,
        source_files=source_files,
        db_path=db_path,
        _source_xml_by_sample_id_for_tests=_source_xml_by_sample_id_for_tests,
    )
    Path(json_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(md_output).write_text(_markdown(report), encoding="utf-8")
    return report


def _decode_source_files(
    ready_samples: list[dict[str, Any]],
    source_files: list[str | Path] | None,
) -> dict[str, str]:
    if source_files is None:
        raise ValueError(
            "source_files are required unless _source_xml_by_sample_id_for_tests is supplied"
        )
    if len(source_files) != len(ready_samples):
        raise ValueError("source file count must match packet_ready sample count")
    xml_by_sample: dict[str, str] = {}
    for sample, source_file in zip(ready_samples, source_files, strict=True):
        metadata = (
            sample.get("safeMetadata") if isinstance(sample.get("safeMetadata"), dict) else {}
        )
        sample_id = _safe_token(sample.get("sampleId") or metadata.get("case_id") or "unknown")
        source = Path(source_file).read_text(encoding="utf-8").strip()
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        expected_hash = _safe_hash_field(f"{sample_id}.sourceHash", sample.get("sourceHash"))
        if source_hash != expected_hash:
            raise ValueError(f"source hash mismatch for {sample_id}")
        xml_by_sample[sample_id] = pob_code.to_xml(source)
    return xml_by_sample


def _observe_sample(sample_id: str, metadata: dict[str, Any], xml: str) -> SampleObservation:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"invalid transient XML for {sample_id}") from exc
    build = root.find("Build")
    attrs = build.attrib if build is not None else {}
    class_name = _metadata_value(metadata, "class", attrs.get("className", ""))
    ascendancy = _metadata_value(metadata, "ascendancy", attrs.get("ascendClassName", ""))
    main_skill = _metadata_value(metadata, "mainSkill", "")
    level = _safe_int(attrs.get("level") or metadata.get("level"))

    enabled_groups = 0
    all_names: list[str] = []
    primary_names: list[str] = []
    for skill in root.findall(".//Skill"):
        if str(skill.attrib.get("enabled", "true")).lower() == "false":
            continue
        gem_names = [
            str(gem.attrib.get("nameSpec") or "").strip()
            for gem in skill.findall("Gem")
            if str(gem.attrib.get("nameSpec") or "").strip()
        ]
        gem_names = [name for name in gem_names if name != "Removed Skill"]
        if not gem_names:
            continue
        enabled_groups += 1
        all_names.extend(gem_names)
        primary_names.append(gem_names[0])

    tags = _mechanic_tags(all_names, class_name=class_name, ascendancy=ascendancy)
    lifecycle_stage = "endgame_final" if level is not None and level >= 95 else "unknown_lifecycle"
    item_count = len(root.findall(".//Item"))
    return SampleObservation(
        sample_id=sample_id,
        class_name=class_name,
        ascendancy=ascendancy,
        main_skill=main_skill,
        level=level,
        enabled_skill_group_count=enabled_groups,
        item_count=item_count,
        mechanic_tags=tuple(sorted(tags)),
        lifecycle_stage=lifecycle_stage,
        primary_skill_preview=tuple(_unique(primary_names)[:4]),
    )


def _mechanic_tags(
    skill_names: list[str],
    *,
    class_name: str,
    ascendancy: str,
) -> set[str]:
    names = " ".join(skill_names).lower()
    tags: set[str] = set()
    if "cooldown recovery" in names:
        tags.add("cooldown_cadence")
    if any(token in names for token in ("charge", "frenzy")):
        tags.add("charge_cadence")
    if any(token in names for token in ("rage", "berserk")):
        tags.add("rage_burst_window")
    if "mark" in names:
        tags.add("mark_setup")
    if "herald" in names:
        tags.add("herald_clear_layer")
    if any(token in names for token in ("shock", "freeze", "cold", "ice", "thunder")):
        tags.add("elemental_ailment_layer")
    if "mana remnants" in names:
        tags.add("mana_remnant_sustain")
    if any(token in names for token in ("barrage", "twister", "tornado", "multishot")):
        tags.add("projectile_multihit_delivery")
    if any(token in names for token in ("crossbow", "bolts", "shards", "explosive shot")):
        tags.add("ammo_rotation")
    if any(token in names for token in ("protector", "minion", "companions")):
        tags.add("companion_layer")
    if any(token in names for token in ("ghost dance", "wind dancer", "purity")):
        tags.add("defense_reservation_layer")
    if "spirit" in ascendancy.lower() or "purity" in names:
        tags.add("spirit_or_reservation_gate")
    if class_name.lower() in {"monk", "ranger", "mercenary", "huntress"}:
        tags.add("class_specific_mature_engine")
    return tags or {"mature_sample_lead"}


def _load_external_proposals(
    proposal_file: str | Path,
    *,
    endpoint_map: dict[str, str],
) -> dict[str, dict[str, Any]]:
    proposal = json.loads(Path(proposal_file).read_text(encoding="utf-8"))
    _assert_safe_report(proposal)
    validation = research_models.validate_researcher_output(proposal)
    if validation.get("status") != "accepted":
        raise ValueError(
            f"external proposal failed schema validation: {validation.get('errorCode')}"
        )
    if proposal.get("semantic_edges"):
        raise ValueError(
            "real research extraction accepts fragments only; use semantic gate for edges"
        )

    proposals_by_sample: dict[str, dict[str, Any]] = {}
    for index, fragment in enumerate(proposal.get("fragments") or []):
        if not isinstance(fragment, dict):
            raise ValueError(f"fragments[{index}] must be an object")
        sample_id = _sample_id_from_fragment(fragment)
        _validate_fragment_component_keys(fragment, sample_id=sample_id, endpoint_map=endpoint_map)
        if sample_id in proposals_by_sample:
            raise ValueError(f"multiple fragments for sample {sample_id} are not supported here")
        proposals_by_sample[sample_id] = fragment
    return proposals_by_sample


def _sample_id_from_fragment(fragment: dict[str, Any]) -> str:
    case_refs = fragment.get("source_case_refs")
    if not isinstance(case_refs, list):
        raise ValueError("fragment.source_case_refs must be a list")
    sample_ids = [
        _safe_token(str(ref)[5:])
        for ref in case_refs
        if isinstance(ref, str) and ref.startswith("case:")
    ]
    if len(sample_ids) != 1:
        raise ValueError(
            "each external proposal fragment must reference exactly one case:<sampleId>"
        )
    return sample_ids[0]


def _validate_fragment_component_keys(
    fragment: dict[str, Any],
    *,
    sample_id: str,
    endpoint_map: dict[str, str],
) -> None:
    component_keys = fragment.get("component_keys")
    if not isinstance(component_keys, list):
        raise ValueError("fragment.component_keys must be a list")
    keys = {_safe_stable_key(key) for key in component_keys}
    allowed = {endpoint_map[sample_id]} if sample_id in endpoint_map else set()
    if allowed and not allowed.issubset(keys):
        raise ValueError(f"fragment for {sample_id} must include its accepted endpoint mapping")
    outside = sorted(keys - allowed)
    if outside:
        raise ValueError(
            f"fragment for {sample_id} contains component keys outside accepted mapping"
        )


def _review_fragment_from_proposal(fragment: dict[str, Any]) -> dict[str, Any]:
    return {
        "titleZh": _safe_text(fragment.get("title")),
        "summaryZh": _safe_text(fragment.get("summary")),
        "reusablePrincipleZh": _safe_text(fragment.get("reusable_principle")),
        "conditionsZh": [_safe_text(item) for item in fragment.get("conditions", [])],
        "risksZh": [_safe_text(item) for item in fragment.get("risks", [])],
        "verificationTasksZh": [
            _safe_text(item) for item in fragment.get("verification_tasks", [])
        ],
        "componentKeys": [_safe_stable_key(item) for item in fragment.get("component_keys", [])],
        "confidence": _safe_text(fragment.get("confidence")),
        "modelability": _safe_text(fragment.get("modelability")),
    }


def _sample_report(
    *,
    sample: dict[str, Any],
    metadata: dict[str, Any],
    observation: SampleObservation,
    accepted_stable_key: str | None,
    fragment: dict[str, Any],
) -> dict[str, Any]:
    action = (
        "ready_for_future_semantic_proposal_gate"
        if accepted_stable_key
        else "blocked_pending_endpoint_mapping"
    )
    return {
        "sampleId": observation.sample_id,
        "safeSourceRef": _safe_ref("source-hash", sample.get("sourceHash")),
        "packetSafeHashRef": _safe_ref("packet-safe-hash", sample.get("packetSafeHash")),
        "class": observation.class_name,
        "ascendancy": observation.ascendancy,
        "mainSkill": observation.main_skill,
        "acceptedStableKey": accepted_stable_key,
        "lifecycleStage": observation.lifecycle_stage,
        "observedSafeSignals": {
            "enabledSkillGroupCount": observation.enabled_skill_group_count,
            "itemCount": observation.item_count,
            "mechanicTags": list(observation.mechanic_tags),
            "primarySkillPreview": list(observation.primary_skill_preview[:3]),
        },
        "semanticEdgeAction": action,
        "semanticEdgeActionReason": (
            "clean fragment accepted; edge still requires external clean proposal and resolver evidence"
            if accepted_stable_key
            else "endpoint mapping is pending manual review, so no edge can be proposed"
        ),
        "extractedFragments": [fragment],
        "noRawMatureBuildMaterial": True,
    }


def _skipped_sample(
    sample: dict[str, Any],
    metadata: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    sample_id = _safe_token(sample.get("sampleId") or metadata.get("case_id") or "unknown")
    return {
        "sampleId": sample_id,
        "safeSourceRef": _safe_ref("source-hash", sample.get("sourceHash")),
        "status": "skipped",
        "reason": reason,
        "noRawMatureBuildMaterial": True,
    }


def _append_existing_evidence(
    service: research_memory.ResearchMemoryService,
    *,
    fragment_id: str,
    fragment: dict[str, Any],
) -> dict[str, Any]:
    return service.append_evidence_to_fragment(
        fragment_id=fragment_id,
        source_case_refs=list(fragment["source_case_refs"]),
        safe_evidence_refs=list(fragment["safe_evidence_refs"]),
        game_patch=str(fragment["game_patch"]),
        passive_tree_version=str(fragment["passive_tree_version"]),
        pob_version_or_commit=str(fragment["pob_version_or_commit"]),
        visibility=str(fragment["visibility"]),
        split=str(fragment["split"]),
        knowledge_scope=str(fragment["knowledge_scope"]),
        confidence=str(fragment["confidence"]),
    )


def _proposal_dedupe_query(fragment: dict[str, Any]) -> str:
    parts = [
        str(fragment.get("title") or ""),
        str(fragment.get("summary") or ""),
        str(fragment.get("reusable_principle") or ""),
        " ".join(str(item) for item in fragment.get("component_keys") or []),
    ]
    return " ".join(part for part in parts if part)


def _accepted_endpoint_map(mapping_report: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in mapping_report.get("reviewItems", []):
        if not isinstance(item, dict):
            continue
        if item.get("reviewStatus") != "accepted" or not item.get("acceptedStableKey"):
            continue
        sample_id = _safe_token(item.get("sampleId"))
        stable_key = _safe_stable_key(item.get("acceptedStableKey"))
        out[sample_id] = stable_key
    return out


def _accepted_or_existing_fragment_id(result: dict[str, Any]) -> str | None:
    ids = result.get("fragmentIds")
    if isinstance(ids, list) and ids:
        return str(ids[0])
    facts = result.get("facts")
    if isinstance(facts, dict):
        existing = facts.get("existingFragmentIds")
        if isinstance(existing, list) and existing:
            return str(existing[0])
    proposal_id = result.get("proposalId")
    if isinstance(proposal_id, str) and proposal_id.startswith("rf-"):
        return proposal_id
    return None


def _validate_packet_report(report: dict[str, Any]) -> None:
    if report.get("safeArtifactOnly") is not True:
        raise ValueError("input report must be safe-only")
    if report.get("status") != "ready_for_external_researcher":
        raise ValueError("input report must be ready_for_external_researcher")
    if not isinstance(report.get("samples"), list):
        raise ValueError("input report samples must be a list")
    _safe_token_field("reportId", report.get("reportId"))
    for index, sample in enumerate(report["samples"]):
        if not isinstance(sample, dict):
            raise ValueError(f"samples[{index}] must be an object")
        _safe_token_field(f"samples[{index}].sampleId", sample.get("sampleId"))
        _safe_hash_field(f"samples[{index}].sourceHash", sample.get("sourceHash"))
        if sample.get("packetSafeHash"):
            _safe_hash_field(f"samples[{index}].packetSafeHash", sample.get("packetSafeHash"))
    _assert_safe_report(report)


def _assert_safe_report(report: dict[str, Any]) -> None:
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    leaks = [marker for marker in RAW_MARKERS if marker in serialized]
    if leaks:
        raise ValueError(f"unsafe durable report markers detected: {', '.join(leaks)}")
    _validate_safe_ref_fields(report)
    flags = set(_copyability_flags_for_report(report))
    if flags:
        raise ValueError(f"durable report failed copy-safety scan: {', '.join(sorted(flags))}")
    forbidden = copy_safety.find_forbidden_paths(report)
    if forbidden:
        raise ValueError("durable report contains forbidden raw fields")


def _copyability_flags_for_report(value: Any, *, path: str = "") -> list[str]:
    flags: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            flags.update(_copyability_flags_for_report(child, path=child_path))
        return sorted(flags)
    if isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            flags.update(_copyability_flags_for_report(child, path=child_path))
        return sorted(flags)
    if isinstance(value, str):
        local_flags = set(copy_safety.copyability_flags(value))
        if "full_gem_link_like" in local_flags and (
            _is_structured_safe_token(path, value) or _is_safe_ref_token(path, value)
        ):
            local_flags.remove("full_gem_link_like")
        flags.update(local_flags)
    return sorted(flags)


def _is_structured_safe_token(path: str, value: str) -> bool:
    leaf = path.rsplit(".", 1)[-1].split("[", 1)[0]
    return leaf in FULL_GEM_LINK_TOKEN_FIELDS and bool(TOKEN_RE.fullmatch(value))


def _is_safe_ref_token(path: str, value: str) -> bool:
    leaf = path.rsplit(".", 1)[-1].split("[", 1)[0]
    return leaf in SAFE_REF_TOKEN_FIELDS and bool(SAFE_REF_RE.fullmatch(value))


def _validate_safe_ref_fields(value: Any, *, path: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key in SAFE_REF_TOKEN_FIELDS:
                _validate_safe_ref_list(child, path=child_path)
                continue
            _validate_safe_ref_fields(child, path=child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_safe_ref_fields(child, path=f"{path}[{index}]")


def _validate_safe_ref_list(value: Any, *, path: str) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a safe ref list")
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(item, str) or not SAFE_REF_RE.fullmatch(item):
            raise ValueError(f"{item_path} must be a short safe ref token")
        flags = set(copy_safety.copyability_flags(item))
        flags.discard("full_gem_link_like")
        if flags:
            raise ValueError(f"{item_path} failed copy-safety scan")


def _metadata_value(metadata: dict[str, Any], key: str, default: str) -> str:
    value = metadata.get(key, default)
    text = " ".join(str(value or default).split())[:180]
    _reject_copyable(text)
    return text or default


def _safe_ref(prefix: str, value: Any) -> str:
    text = "".join(ch for ch in str(value or "unknown").lower() if ch.isalnum())[:16]
    return f"{prefix}:{text or 'unknown'}"


def _safe_token(value: Any) -> str:
    text = str(value or "unknown").strip()
    _reject_copyable(text, allow_full_gem_link_like=True)
    safe = "".join(ch if ch.isalnum() or ch in "_:-." else "-" for ch in text)
    return safe[:80] or "unknown"


def _safe_token_field(field: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    _reject_copyable(text, allow_full_gem_link_like=True)
    if not TOKEN_RE.fullmatch(text):
        raise ValueError(f"{field} must be a safe token")
    return text


def _safe_hash_field(field: str, value: Any) -> str:
    text = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{16,128}", text):
        raise ValueError(f"{field} must be a hex safe hash")
    _reject_copyable(text, allow_full_gem_link_like=True)
    return text


def _safe_stable_key(value: Any) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", text):
        raise ValueError("acceptedStableKey must be a safe stable key")
    _reject_copyable(text, allow_full_gem_link_like=True)
    return text


def _safe_text(value: Any) -> str:
    text = " ".join(str(value or "").split())[:300]
    _reject_copyable(text)
    return text


def _reject_copyable(text: str, *, allow_full_gem_link_like: bool = False) -> None:
    lower = text.lower()
    if any(marker.lower() in lower for marker in RAW_MARKERS):
        raise ValueError("copy-safety marker detected")
    if re.search(
        r"(?:https?://|www\.|pobb\.in|pastebin\.com|poe\.ninja|pathofexile\.com)",
        lower,
    ):
        raise ValueError("copy-safety URL marker detected")
    flags = set(copy_safety.copyability_flags(text))
    if allow_full_gem_link_like:
        flags.discard("full_gem_link_like")
    if flags:
        raise ValueError(f"copy-safety flags detected: {', '.join(sorted(flags))}")


def _safe_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 4 Real Research Extraction",
        "",
        f"- Status: `{report['status']}`",
        f"- Safe artifact only: `{report['safeArtifactOnly']}`",
        f"- Accepted fragments: `{report['acceptedFragmentCount']}`",
        f"- Duplicate fragments: `{report['duplicateFragmentCount']}`",
        f"- Evidence appends: `{report['appendedEvidenceCount']}`",
        f"- Semantic edge write attempted: `{report['semanticEdgeWrite']['attempted']}`",
        "",
        "## 中文机制摘录",
        "",
    ]
    for sample in report["samples"]:
        fragments = sample.get("extractedFragments") or []
        fragment = fragments[0] if fragments else {}
        lines.extend(
            [
                f"### {sample.get('sampleId')} - {sample.get('mainSkill')}",
                "",
                f"- 职业/升华：`{sample.get('class')}` / `{sample.get('ascendancy')}`",
                f"- Fragment：`{fragment.get('fragmentId')}` / `{fragment.get('writeStatus')}`",
                f"- 标题：{fragment.get('titleZh')}",
                f"- 原则：{fragment.get('reusablePrincipleZh')}",
                f"- Edge 动作：`{sample.get('semanticEdgeAction')}`",
            ]
        )
        tags = sample.get("observedSafeSignals", {}).get("mechanicTags", [])
        if tags:
            lines.append(f"- 机制标签：`{', '.join(tags[:8])}`")
        conditions = fragment.get("conditionsZh") or []
        if conditions:
            lines.append(f"- 条件：{conditions[0]}")
        risks = fragment.get("risksZh") or []
        if risks:
            lines.append(f"- 风险：{risks[0]}")
        lines.append("")
    lines.extend(["## Caveats", ""])
    lines.extend(f"- {item}" for item in report["caveats"])
    lines.append("")
    text = "\n".join(lines)
    for marker in RAW_MARKERS:
        if marker in text:
            raise ValueError(f"unsafe markdown marker detected: {marker}")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-report", default=str(PACKET_REPORT))
    parser.add_argument("--endpoint-mapping-report", default=str(ENDPOINT_MAPPING_REPORT))
    parser.add_argument("--proposal-file", required=True)
    parser.add_argument("--source-file", action="append", required=True)
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--json-output", default=str(JSON_OUTPUT))
    parser.add_argument("--md-output", default=str(MD_OUTPUT))
    args = parser.parse_args(argv)
    report = write_real_research_extraction_report(
        input_report=args.input_report,
        endpoint_mapping_report=args.endpoint_mapping_report,
        external_proposal_file=args.proposal_file,
        source_files=[Path(value) for value in args.source_file],
        db_path=Path(args.db_path) if args.db_path else None,
        json_output=args.json_output,
        md_output=args.md_output,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["sampleCount"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
