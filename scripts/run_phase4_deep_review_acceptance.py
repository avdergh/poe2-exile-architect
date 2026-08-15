"""Accept safe Phase 4.5 deep-review candidates into durable research memory.

The Researcher pass returns safe candidate reviews, not final durable knowledge.
This controller accepts only candidates backed by a structured safe review
artifact and public resolver evidence. Ambiguous names must also reference an
explicit reviewed endpoint mapping decision.
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
from server.freshness import providers as freshness_providers  # noqa: E402
from server.knowledge import (  # noqa: E402
    copy_safety,
    graph_tools,
    physical_graph,
    research_identity,
    research_memory,
    research_models,
)

JSON_OUTPUT = REPO_ROOT / "phase4_deep_review_acceptance_report.json"
MD_OUTPUT = REPO_ROOT / "phase4_deep_review_acceptance_report.md"
DB_PATH = paths.mature_learning_path()
REVIEW_FILE = REPO_ROOT / "phase4_deep_researcher_candidate_review.json"
PRIMARY_MAPPING_REPORT = REPO_ROOT / "phase4_reviewed_endpoint_mapping_report.json"
SECONDARY_MAPPING_REPORT = REPO_ROOT / "phase4_reviewed_secondary_endpoint_mapping_report.json"
DEEP_COMPONENT_MAPPING_REPORT = REPO_ROOT / "phase4_deep_reviewed_component_mapping_report.json"

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
    "packet.json",
    "deep_researcher_prompt.txt",
    "pobb.in/",
    "poe.ninja/",
)

CASE_COVERAGE_DIMENSIONS = {
    "supports",
    "rotation",
    "passiveAscendancy",
    "gearRoles",
    "resourceDefense",
}
CASE_COVERAGE_STATUSES = {"covered", "evidence_missing", "not_applicable"}

MECHANIC_AUDIT_CLAIM_TYPES = {
    "behavior_or_trigger",
    "precondition",
    "resource_flow",
    "conversion_or_transform",
}
MECHANIC_AUDIT_WIKI_STATUSES = {"supports", "contradicts", "silent", "unavailable"}
MECHANIC_AUDIT_DECISIONS = {"keep", "revise", "defer"}
MECHANIC_AUDIT_CORROBORATION = {
    "source_artifact",
    "pinned_pob_static",
    "typed_graph",
    "typed_support_compatibility",
    "local_mechanics",
    "judge_readback",
}
MECHANIC_AUDIT_HIGH_RISK_RECORD_KINDS = {"mechanic_chain", "resource_engine"}
POE2WIKI_REVISION_REF = re.compile(r"^poe2wiki:page:[1-9][0-9]*:rev:[1-9][0-9]*$")

PATTERN_TYPE_VALUES = {
    "build_archetype",
    "cooccurrence",
    "transition_gate",
    "failure_pattern",
    "planner_hint",
}

AXIS_ALIASES = {
    "modelability_caveat": "modelability_caveats",
    "modelability_caveats": "modelability_caveats",
    "variant_relation": "variant_relations",
    "variant_relations": "variant_relations",
}

DESIGN_AXIS_VALUES = {
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
    "variant_relations",
    "modelability_caveats",
}

CONCRETE_RECORD_KINDS = {
    "skill_package",
    "mechanic_chain",
    "rotation",
    "gear_synergy",
    "passive_package",
    "defense_engine",
    "resource_engine",
    "class_or_ascendancy_principle",
}

ROLE_NODE_TYPES = {
    "primary_damage": ["active_skill"],
    "clear_skill": ["active_skill"],
    "boss_skill": ["active_skill"],
    # Generator/payoff describe build function, not a single physical node kind. A skill,
    # support, passive or unique can legitimately supply either side of a mechanism chain.
    "generator": [
        "active_skill",
        "support_gem",
        "unique",
        "passive",
        "notable",
        "keystone",
        "ascendancy_passive",
    ],
    "payoff": [
        "active_skill",
        "support_gem",
        "unique",
        "passive",
        "notable",
        "keystone",
        "ascendancy_passive",
    ],
    "reservation": ["active_skill"],
    "defensive_buff": ["active_skill"],
    "movement": ["active_skill"],
    "trigger_host": ["active_skill"],
    "secondary_skill": ["active_skill"],
    "control_skill": ["active_skill"],
    # The payload is the active skill that actually deals or applies the triggered effect.
    # A support may grant that skill, but the support itself remains a support_modifier;
    # otherwise Family identity silently loses the payload because supports are not skills.
    "triggered_payload": ["active_skill"],
    "support_modifier": ["support_gem"],
    "unique_enabler": ["unique"],
    "passive_anchor": ["passive", "notable", "keystone", "ascendancy_passive"],
    # The legacy role names are functional: transformation may live on a notable or
    # ascendancy passive, and a weapon choice may be either a base or a unique weapon.
    "keystone_transformer": [
        "passive",
        "notable",
        "keystone",
        "ascendancy_passive",
    ],
    "gear_base": ["item_base"],
    "weapon_base": ["item_base", "unique"],
    "ascendancy_shell": ["ascendancy"],
}

PLAYER_COMPONENT_ROLES = {
    "primary_damage",
    "clear_skill",
    "boss_skill",
    "reservation",
    "defensive_buff",
    "movement",
    "trigger_host",
    "secondary_skill",
    "control_skill",
}

NODE_TYPE_ROLE_SUGGESTIONS = {
    "active_skill": ["secondary_skill"],
    "support_gem": ["support_modifier"],
    "skill_gem": ["secondary_skill"],
    "unique": ["unique_enabler"],
    "ascendancy": ["ascendancy_shell"],
    "passive": ["passive_anchor"],
    "notable": ["passive_anchor"],
    "keystone": ["keystone_transformer", "passive_anchor"],
    "item_base": ["gear_base", "weapon_base"],
}


def _unresolved_jewel_sockets_deferred(
    review: dict[str, Any],
    jewel_counts: dict[str, Any],
) -> list[dict[str, Any]]:
    """Defer a case whose allocated jewel sockets carry no socketed jewel and whose review
    never declares the jewel state.

    ``tree_data_missing`` stays advisory-only (the packet cannot prove sockets are empty);
    a review that mentions jewels anywhere counts as a declaration.
    """
    if not isinstance(jewel_counts, dict):
        return []
    if str(jewel_counts.get("status") or "") in {"tree_data_missing", "sockets_absent"}:
        return []
    allocated = int(jewel_counts.get("allocatedJewelSocketCount") or 0)
    # Only tree sockets count toward the closure gate: a jewel in an embedded equipment
    # socket cannot fill an empty tree socket, so it must not suppress the declaration.
    tree_socketed = jewel_counts.get("treeSocketedJewelCount")
    if tree_socketed is None:
        tree_socketed = jewel_counts.get("socketedJewelCount") or 0
    tree_socketed = int(tree_socketed or 0)
    if allocated <= 0 or tree_socketed > 0:
        return []
    if _review_declares_jewels(review):
        return []
    sample_id = str((review.get("artifactIdentity") or {}).get("sampleId") or "")
    return [
        {
            "titleZh": "已分配珠宝槽未声明珠宝状态",
            "sampleId": sample_id,
            "reason": "unresolved_jewel_sockets",
            "componentKeys": [],
            "caveats": [
                f"{allocated} allocated jewel socket(s) carry no socketed jewel and the review "
                "never mentions jewels; declare the jewel state explicitly (empty sockets, or "
                "socketed gems with their radius/Time-Lost conditions) before accepting"
            ],
            "candidateKind": "research_case",
        }
    ]


def _review_declares_jewels(review: dict[str, Any]) -> bool:
    """Whether any research record mentions jewels in its study content.

    Scans only record prose (title/summary/content/conditions/failureConditions) and
    component candidate names, never identity fields such as sampleId, so a case id that
    happens to contain the word "jewel" cannot count as a declaration.
    """
    for record in review.get("deepResearchRecords") or []:
        if not isinstance(record, dict):
            continue
        parts = [
            str(record.get("title") or ""),
            str(record.get("summary") or ""),
            str(record.get("content") or ""),
            *[str(value) for value in record.get("conditions") or []],
            *[str(value) for value in record.get("failureConditions") or []],
            *[
                str(component.get("candidateName") or "")
                for component in record.get("components") or []
                if isinstance(component, dict)
            ],
        ]
        if any("jewel" in part.casefold() for part in parts):
            return True
    return False


def _unique_gem_diagnostics(
    review: dict[str, Any],
    source_skill_manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    """Detect lineage (unique) support gems in the source and whether the review labeled them.

    Tri-state lookup: True/False from the corpus ``is_lineage`` field; unknown when the corpus
    is unavailable or the gem name does not resolve (never blocks). Only names whose
    ``nameSource`` is ``nameSpec`` are gem candidates: item/passive-granted skills fall back to
    internal skill ids and are reported separately as ``nonGemSkillNames`` so they never pollute
    gem diagnostics. A lineage gem counts as labeled when any record mentions it inside an
    open_question/modelability_caveat record, or when the record prose explicitly labels its
    lineage/unique identity. A bare component with role unique_enabler does not label it:
    lineage gems are support_gem nodes, so that role fails resolver type checks (use
    support_modifier with prose labeling instead). Otherwise any mention is reported as
    unlabeled so the Researcher marks its unique identity.
    """
    if not isinstance(source_skill_manifest, dict):
        return {
            "available": False,
            "uniqueGemCandidates": [],
            "unlabeledUniqueGemNames": [],
            "corpusMissingGemNames": [],
            "nonGemSkillNames": [],
            "proseMentionedWithoutComponentNames": [],
        }
    gem_names: list[str] = []
    non_gem_names: list[str] = []
    for group in source_skill_manifest.get("activeSkillGroups") or []:
        if not isinstance(group, dict):
            continue
        for item in [
            *(group.get("activeSkills") or []),
            *(group.get("supports") or []),
        ]:
            if not isinstance(item, dict) or not str(item.get("name") or "").strip():
                continue
            name = str(item["name"]).strip()
            name_source = str(item.get("nameSource") or "gem_name")
            if name_source == "gem_name":
                gem_names.append(name)
            else:
                non_gem_names.append(name)
    unique_candidates: list[str] = []
    corpus_missing_names: list[str] = []
    try:
        from server.knowledge import db as corpus_db

        corpus_available = True
    except Exception:  # pragma: no cover - import layout drift guard
        corpus_db = None
        corpus_available = False
    for name in dict.fromkeys(gem_names):
        if not corpus_available:
            corpus_missing_names.append(name)
            continue
        try:
            gem = corpus_db.get_gem(name)
        except Exception:
            gem = None
        if gem is None:
            corpus_missing_names.append(name)
            continue
        if gem.get("is_lineage") is True:
            unique_candidates.append(name)
    if not unique_candidates:
        return {
            "available": corpus_available,
            "uniqueGemCandidates": [],
            "unlabeledUniqueGemNames": [],
            "corpusMissingGemNames": corpus_missing_names,
            "nonGemSkillNames": sorted(dict.fromkeys(non_gem_names)),
            "proseMentionedWithoutComponentNames": [],
        }
    raw_records = review.get("deepResearchRecords") or []
    raw_records = raw_records if isinstance(raw_records, list) else []
    record_texts: list[tuple[str, list[str]]] = []
    for record in raw_records:
        if not isinstance(record, dict):
            continue
        parts = [
            str(record.get("title") or ""),
            str(record.get("summary") or ""),
            str(record.get("content") or ""),
            *[str(value) for value in record.get("conditions") or []],
            *[str(value) for value in record.get("failureConditions") or []],
        ]
        record_texts.append((str(record.get("recordKind") or ""), parts))
    unlabeled: list[str] = []
    prose_only_mentions: list[str] = []
    declared_component_names = {
        str(component.get("candidateName") or "").casefold()
        for record in raw_records
        if isinstance(record, dict)
        for component in record.get("components") or []
        if isinstance(component, dict)
    }
    for gem_name in unique_candidates:
        normalized = gem_name.casefold()
        labeled = False
        mentioned = False
        in_prose = False
        for record_kind, parts in record_texts:
            in_text = any(normalized in part.casefold() for part in parts)
            if not in_text:
                continue
            mentioned = True
            in_prose = True
            if record_kind in {"open_question", "modelability_caveat"}:
                labeled = True
            elif any(_mentions_unique_identity(part, normalized) for part in parts):
                labeled = True
        for record in raw_records:
            if not isinstance(record, dict):
                continue
            for component in record.get("components") or []:
                if not isinstance(component, dict):
                    continue
                if str(component.get("candidateName") or "").casefold() != normalized:
                    continue
                mentioned = True
        if mentioned and not labeled:
            unlabeled.append(gem_name)
        if in_prose and normalized not in declared_component_names:
            prose_only_mentions.append(gem_name)
    return {
        "available": corpus_available,
        "uniqueGemCandidates": unique_candidates,
        "unlabeledUniqueGemNames": sorted(unlabeled),
        "corpusMissingGemNames": corpus_missing_names,
        "nonGemSkillNames": sorted(dict.fromkeys(non_gem_names)),
        "proseMentionedWithoutComponentNames": sorted(prose_only_mentions),
    }


def _mentions_unique_identity(text: str, gem_name: str) -> bool:
    """Whether a record's prose explicitly labels a gem's lineage/unique identity.

    Matches AGENTS.md's allowance to keep a lineage gem's role as support_modifier while
    labeling its unique identity in prose. The gem name itself is stripped first so a name
    that literally contains "unique" (e.g. "Unique Breach Lightning Bolt") cannot self-label.
    """
    lowered = str(text or "").casefold()
    if not lowered:
        return False
    stripped = lowered.replace(gem_name.casefold(), "")
    return "lineage" in stripped or "unique" in stripped


def accept_deep_review_candidates(
    *,
    db_path: str | Path = DB_PATH,
    json_output: str | Path = JSON_OUTPUT,
    md_output: str | Path = MD_OUTPUT,
    review_file: str | Path = REVIEW_FILE,
    primary_mapping_report: str | Path | None = PRIMARY_MAPPING_REPORT,
    secondary_mapping_report: str | Path | None = SECONDARY_MAPPING_REPORT,
    component_mapping_reports: list[str | Path] | None = None,
    graph_service: graph_tools.GraphQueryService | None = None,
    version_context: dict[str, str] | None = None,
    source_skill_manifest: dict[str, Any] | None = None,
    jewel_counts: dict[str, Any] | None = None,
    review_payload: dict[str, Any] | None = None,
    require_deep_records: bool = False,
    validation_only: bool = False,
) -> dict[str, Any]:
    graph_service = graph_service or _graph_service()
    durable_version_context = _durable_version_context(version_context)
    review = (
        json.loads(json.dumps(review_payload))
        if review_payload is not None
        else _load_safe_json(Path(review_file), expected_safe=True)
    )
    if not isinstance(review, dict) or review.get("safeArtifactOnly") is not True:
        raise ValueError("deep review artifact must be safeArtifactOnly=true")
    structural_groups = _structural_schema_issues(review)
    if structural_groups:
        report = _structural_failure_report(structural_groups)
        if not validation_only:
            _write_safe_report(report, Path(json_output), Path(md_output))
        return report
    unique_gem_diagnostics = _unique_gem_diagnostics(review, source_skill_manifest)
    review, mechanic_audit_diagnostics, mechanic_audit_deferred = _prepare_mechanic_audit(review)
    mechanic_audit_schema_failed = bool(mechanic_audit_diagnostics["schemaIssueCount"])
    reviewed_mappings = _reviewed_mappings(
        primary_mapping_report=Path(primary_mapping_report) if primary_mapping_report else None,
        secondary_mapping_report=Path(secondary_mapping_report)
        if secondary_mapping_report
        else None,
        component_mapping_reports=[Path(item) for item in component_mapping_reports or []],
    )
    confirmed_review_components = _confirmed_review_component_resolutions(
        graph_service=graph_service,
        review=review,
    )
    source_skill_resolutions = _source_skill_id_resolutions(
        graph_service=graph_service,
        source_skill_manifest=source_skill_manifest,
    )
    source_support_compatibility = _source_support_compatibility_diagnostics(
        graph_service=graph_service,
        source_skill_manifest=source_skill_manifest,
        source_skill_resolutions=source_skill_resolutions,
    )
    deep_payload, accepted_record_summaries, deferred_records = _build_deep_record_payload(
        graph_service=graph_service,
        review=review,
        reviewed_mappings=reviewed_mappings,
        confirmed_review_components=confirmed_review_components,
        source_skill_resolutions=source_skill_resolutions,
        version_context=durable_version_context,
    )
    _propagate_group_ascendancy_scope(deep_payload)
    (
        deep_payload,
        accepted_record_summaries,
        structured_support_deferred,
    ) = _filter_records_with_unsupported_structured_support_packages(
        graph_service=graph_service,
        deep_payload=deep_payload,
        accepted_records=accepted_record_summaries,
    )
    deferred_records.extend(structured_support_deferred)
    (
        deep_payload,
        accepted_record_summaries,
        support_compatibility_deferred,
    ) = _filter_records_with_unsupported_source_supports(
        deep_payload=deep_payload,
        accepted_records=accepted_record_summaries,
        diagnostics=source_support_compatibility,
    )
    deferred_records.extend(support_compatibility_deferred)
    source_evidence_diagnostics = _source_skill_evidence_diagnostics(
        review=review,
        source_skill_manifest=source_skill_manifest,
    )
    source_evidence_diagnostics.update(source_support_compatibility)
    case_coverage, coverage_advisories = _evaluate_case_coverage(
        review=review,
        accepted_records=accepted_record_summaries,
        graph_service=graph_service,
        source_evidence_diagnostics=source_evidence_diagnostics,
    )
    deep_payload, accepted_record_summaries, gear_context_deferred = (
        _filter_mechanic_records_without_gear_context(
            review=review,
            deep_payload=deep_payload,
            accepted_records=accepted_record_summaries,
            case_coverage=case_coverage,
        )
    )
    deferred_records.extend(gear_context_deferred)
    blocked_pattern_dependencies = _blocked_pattern_dependencies(
        [
            *gear_context_deferred,
            *structured_support_deferred,
            *support_compatibility_deferred,
            *mechanic_audit_deferred,
        ]
    )
    origin_family_by_case_ref = _origin_family_by_case_ref(deep_payload)
    if require_deep_records:
        deferred_records.extend(
            _missing_build_family_identity_deferred(
                deep_payload=deep_payload,
                accepted_records=accepted_record_summaries,
                origin_family_by_case_ref=origin_family_by_case_ref,
            )
        )
    source_specific_components_by_case_ref = _source_specific_components_by_case_ref(deep_payload)
    if jewel_counts is not None:
        deferred_records.extend(_unresolved_jewel_sockets_deferred(review, jewel_counts))
    (
        payload,
        accepted_summaries,
        single_component_observations,
        case_only_observations,
        deferred,
    ) = _build_payload(
        graph_service=graph_service,
        review=review,
        reviewed_mappings=reviewed_mappings,
        confirmed_review_components=confirmed_review_components,
        source_skill_resolutions=source_skill_resolutions,
        source_skill_manifest=source_skill_manifest,
        version_context=durable_version_context,
        origin_family_by_case_ref=origin_family_by_case_ref,
        source_specific_components_by_case_ref=source_specific_components_by_case_ref,
        component_transfer_allowed=case_coverage["gearRoles"] != "evidence_missing",
        blocked_pattern_dependencies=blocked_pattern_dependencies,
    )
    deferred.extend(deferred_records)
    deferred.extend(mechanic_audit_deferred)
    service = research_memory.ResearchMemoryService(
        db_path=Path(db_path),
        graph_service=graph_service,
        initialize_store=not validation_only,
    )
    submitted_deep_records = _deep_record_reviews(review)
    record_kind_advisories = _record_kind_advisories(submitted_deep_records)
    if require_deep_records and not deep_payload["deep_research_records"]:
        submitted_sample_id = str(
            (submitted_deep_records or review.get("candidateReviews") or [{}])[0].get("sampleId")
            or ""
        )
        deferred.append(
            {
                "titleZh": (
                    "案例没有可接收的深度研究记录"
                    if submitted_deep_records
                    else "案例未提交深度研究记录"
                ),
                "sampleId": submitted_sample_id,
                "reason": "missing_deep_research_records",
                "componentKeys": [],
                "candidateKind": "research_case",
            }
        )
    depth_gate_failed = any(
        item.get("reason")
        in {
            "insufficient_case_research_depth",
            "missing_build_family_identity",
            "missing_deep_research_records",
        }
        for item in deferred
    )
    # Formal acceptance mirrors the validate-only schema gate: schema-violating
    # candidates are deferred (never silently dropped into a partial payload),
    # so a case carrying any invalid_schema deferral must not be accepted.
    schema_gate_failed = any(str(item.get("reason") or "") == "invalid_schema" for item in deferred)
    acceptance_gate_failed = depth_gate_failed or mechanic_audit_schema_failed or schema_gate_failed
    if acceptance_gate_failed:
        payload = {"schema_version": 4, "build_design_observations": [], "patterns": []}
        deep_payload = {"schema_version": 5, "deep_research_records": []}
        accepted_summaries = []
        accepted_record_summaries = []
    has_pattern_payload = bool(payload["build_design_observations"] or payload["patterns"])
    has_deep_payload = bool(deep_payload["deep_research_records"])
    empty_pattern_result = {
        "status": "accepted",
        "observationIds": [],
        "patternIds": [],
        "validationOnly": validation_only,
        "noRawQuery": True,
        "noRawMatureBuildMaterial": True,
    }
    empty_deep_result = {
        "status": "accepted",
        "recordIds": [],
        "recordWrites": [],
        "knowledgeKeys": [],
        "buildFamilyKeys": [],
        "createdRecordCount": 0,
        "updatedRecordCount": 0,
        "evidenceAddedCount": 0,
        "familyEvidenceAddedCount": 0,
        "createdBuildFamilyCount": 0,
        "researchGroupIds": [],
        "validationOnly": validation_only,
        "noRawQuery": True,
        "noRawMatureBuildMaterial": True,
    }
    pattern_validation = (
        service.validate_build_patterns(payload) if has_pattern_payload else empty_pattern_result
    )
    deep_validation = (
        service.validate_deep_research_records(deep_payload)
        if has_deep_payload
        else empty_deep_result
    )
    all_payloads_valid = (
        pattern_validation.get("status") == "accepted"
        and deep_validation.get("status") == "accepted"
    )
    if validation_only:
        result = _pattern_validation_result(pattern_validation)
        deep_result = _deep_record_validation_result(
            deep_validation,
            deep_payload=deep_payload,
        )
    elif not all_payloads_valid:
        # Validate the complete acceptance unit before either durable writer runs.
        result = pattern_validation
        deep_result = deep_validation
    else:
        result = (
            service.propose_build_patterns(payload) if has_pattern_payload else empty_pattern_result
        )
        deep_result = (
            service.propose_deep_research_records(deep_payload)
            if has_deep_payload
            else empty_deep_result
        )
    accepted = (
        result.get("status") == "accepted"
        and deep_result.get("status") == "accepted"
        and not acceptance_gate_failed
    )
    persisted_record_summaries = (
        _attach_deep_record_ids(accepted_record_summaries, deep_result)
        if deep_result.get("status") == "accepted"
        else []
    )
    unresolved_component_mentions = [
        component
        for item in persisted_record_summaries
        for component in item.get("unresolvedComponents") or []
    ]
    unresolved_component_identities = {
        str(component.get("resolverQuery") or component.get("candidateName") or "")
        .strip()
        .casefold()
        for component in unresolved_component_mentions
        if str(component.get("resolverQuery") or component.get("candidateName") or "").strip()
    }
    unkeyed_deep_records = [
        item for item in deferred if str(item.get("reason") or "") == "missing_knowledge_identity"
    ]
    case_coverage_gaps = [
        dimension for dimension, status in case_coverage.items() if status == "evidence_missing"
    ]
    acceptance_mode = (
        "blocked"
        if not accepted
        else "clean"
        if not deferred and not unresolved_component_mentions and not case_coverage_gaps
        else "partial_with_deferred"
    )
    report = {
        "reportId": "phase4-deep-review-acceptance-v3",
        "status": "accepted" if accepted else "rejected",
        "acceptanceMode": acceptance_mode,
        "validationOnly": validation_only,
        "durableWritePerformed": not validation_only
        and bool(
            result.get("observationIds") or result.get("patternIds") or deep_result.get("recordIds")
        ),
        "safeArtifactOnly": True,
        "inputKind": "safe_deep_researcher_candidate_review",
        "inputReviewReportId": str(review.get("reportId") or ""),
        "patternWrite": result,
        "deepRecordWrite": deep_result,
        "acceptedDeepRecordCount": len(deep_result.get("recordIds") or [])
        if deep_result.get("status") == "accepted"
        else 0,
        "createdDeepRecordCount": int(deep_result.get("createdRecordCount") or 0)
        if deep_result.get("status") == "accepted"
        else 0,
        "updatedDeepRecordCount": int(deep_result.get("updatedRecordCount") or 0)
        if deep_result.get("status") == "accepted"
        else 0,
        "addedDeepRecordEvidenceCount": int(deep_result.get("evidenceAddedCount") or 0)
        if deep_result.get("status") == "accepted"
        else 0,
        "addedBuildFamilyEvidenceCount": int(deep_result.get("familyEvidenceAddedCount") or 0)
        if deep_result.get("status") == "accepted"
        else 0,
        "createdBuildFamilyCount": int(deep_result.get("createdBuildFamilyCount") or 0)
        if deep_result.get("status") == "accepted"
        else 0,
        "acceptedBuildFamilyKeys": list(deep_result.get("buildFamilyKeys") or [])
        if deep_result.get("status") == "accepted"
        else [],
        "siblingFamilyHints": list(deep_result.get("siblingFamilyHints") or []),
        "acceptedDeepRecords": persisted_record_summaries,
        # Compatibility field: this has always counted mentions, not unique entities.
        "unresolvedDeepRecordComponentCount": len(unresolved_component_mentions),
        "unresolvedDeepRecordMentionCount": len(unresolved_component_mentions),
        "unresolvedUniqueComponentCount": len(unresolved_component_identities),
        "deepRecordsWithUnresolvedComponents": [
            {
                "titleZh": str(item.get("titleZh") or ""),
                "recordKind": str(item.get("recordKind") or ""),
                "unresolvedComponentCount": int(item.get("unresolvedComponentCount") or 0),
                "unresolvedComponents": list(item.get("unresolvedComponents") or []),
            }
            for item in persisted_record_summaries
            if int(item.get("unresolvedComponentCount") or 0) > 0
        ],
        "unkeyedDeepRecordCount": len(unkeyed_deep_records),
        "deepRecordsWithoutKnowledgeIdentity": [
            {
                "titleZh": str(item.get("titleZh") or ""),
                "recordKind": str(item.get("recordKind") or ""),
                "suggestedRepair": str(item.get("suggestedRepair") or ""),
            }
            for item in unkeyed_deep_records
        ],
        "recordKindCounts": _record_kind_counts(persisted_record_summaries),
        "mechanicAudit": mechanic_audit_diagnostics,
        "mechanicAuditEntryCount": int(mechanic_audit_diagnostics["entryCount"]),
        "mechanicAuditSchemaIssueCount": int(mechanic_audit_diagnostics["schemaIssueCount"]),
        "mechanicAuditPinnedRevisionCount": int(mechanic_audit_diagnostics["pinnedRevisionCount"]),
        "mechanicAuditLiveEvidenceStatus": str(mechanic_audit_diagnostics["liveEvidenceStatus"]),
        "mechanicAuditUnauditedHighRiskRecordCount": int(
            mechanic_audit_diagnostics["unauditedHighRiskRecordCount"]
        ),
        "mechanicAuditAdvisories": list(mechanic_audit_diagnostics["advisories"]),
        "caseCoverage": case_coverage,
        "caseCoverageGapCount": len(case_coverage_gaps),
        "caseCoverageGaps": case_coverage_gaps,
        "caseCoverageAdvisories": coverage_advisories,
        "sourceEvidenceDiagnostics": source_evidence_diagnostics,
        "sourceSkillIdResolutionCount": len(source_skill_resolutions),
        "sourceSkillIdResolvedNames": sorted(
            str(item.get("candidateName") or "") for item in source_skill_resolutions.values()
        ),
        "recordKindAdvisories": record_kind_advisories,
        "acceptedPatternCount": len(result.get("patternIds") or [])
        if result.get("status") == "accepted"
        else 0,
        "acceptedObservationCount": len(result.get("observationIds") or [])
        if result.get("status") == "accepted"
        else 0,
        "acceptedPatterns": accepted_summaries if result.get("status") == "accepted" else [],
        "acceptedTransferCandidateCount": sum(
            1 for item in accepted_summaries if item.get("transferScope") == "component"
        )
        if result.get("status") == "accepted"
        else 0,
        "promotedTransferPatternCount": len(result.get("promotedPatternIds") or [])
        if result.get("status") == "accepted"
        else 0,
        "promotedTransferPatternIds": list(result.get("promotedPatternIds") or [])
        if result.get("status") == "accepted"
        else [],
        "singleComponentObservationCount": len(single_component_observations)
        if result.get("status") == "accepted"
        else 0,
        "singleComponentObservations": single_component_observations
        if result.get("status") == "accepted"
        else [],
        "caseOnlyObservationCount": len(case_only_observations)
        if result.get("status") == "accepted"
        else 0,
        "caseOnlyObservations": case_only_observations
        if result.get("status") == "accepted"
        else [],
        "deferredCandidateCount": len(deferred),
        "deferredCandidates": deferred,
        "deferredReasonCounts": _reason_counts(deferred),
        "uniqueGemDiagnostics": unique_gem_diagnostics,
        "versionContext": durable_version_context,
        "caveats": [
            "Only structured safe candidate reviews were considered.",
            "Resolver evidence came from public resolve_graph_component output.",
            (
                "Ambiguous resolver results require explicit reviewed endpoint mapping or a "
                "stable-key lookup confirmed elsewhere in the same review."
            ),
            (
                "Each new deep-review pattern enters as case_observation. The backend may promote "
                "an identical component-scoped pattern only after independent cross-Family evidence."
            ),
            "Component/global knowledge is capped at likely_pattern and never receives strong cross-Family ranking authority.",
            "Each deep record contains one focused knowledge unit; a research group carries case coverage.",
            (
                "Mechanic audit wiki citations are revision-pinned corroboration, not authority "
                "for source-instance provenance, compatibility, numerical legality, or Family identity."
            ),
            *(
                [
                    "Advisory: lineage/unique support gems from the source were mentioned "
                    "without labeling their unique identity: "
                    + ", ".join(unique_gem_diagnostics["unlabeledUniqueGemNames"])
                    + ". Label them (support_modifier role with the lineage/unique identity "
                    "stated in prose, or an open_question/modelability_caveat record) so "
                    "downstream consumers can distinguish unique gems from ordinary supports."
                ]
                if unique_gem_diagnostics.get("unlabeledUniqueGemNames")
                else []
            ),
            *(
                [
                    "Advisory: source gems not found in the bundled corpus (unique/lineage "
                    "status unknown): "
                    + ", ".join(unique_gem_diagnostics["corpusMissingGemNames"])
                    + "."
                ]
                if unique_gem_diagnostics.get("corpusMissingGemNames")
                else []
            ),
            *(
                [
                    "Advisory: source skill names are internal ids rather than gem names "
                    "(nameSource != gem_name) and were excluded from unique-gem diagnostics: "
                    + ", ".join(unique_gem_diagnostics["nonGemSkillNames"])
                    + "."
                ]
                if unique_gem_diagnostics.get("nonGemSkillNames")
                else []
            ),
            *(
                [
                    "Advisory: unique gems mentioned in record prose without a declared "
                    "component (their graph presence cannot be verified or counted): "
                    + ", ".join(unique_gem_diagnostics["proseMentionedWithoutComponentNames"])
                    + ". Declare them as components (even unresolved) so coverage counts "
                    "surface them."
                ]
                if unique_gem_diagnostics.get("proseMentionedWithoutComponentNames")
                else []
            ),
            (
                "Researcher candidates passed validation only; durable memory was not changed."
                if validation_only
                else "Researcher conclusions were accepted only through typed resolver and copy-safety gates."
            ),
            *coverage_advisories,
            *record_kind_advisories,
            *mechanic_audit_diagnostics["advisories"],
            *(
                [
                    "Advisory: a BuildFamily was created "
                    + ", ".join(list(deep_result.get("buildFamilyKeys") or []))
                    + " but no deep record was written for it (empty shell). Check the family "
                    "identity derivation and sibling hints before relying on this family."
                ]
                if deep_result.get("status") == "accepted"
                and int(deep_result.get("createdBuildFamilyCount") or 0) > 0
                and int(deep_result.get("createdRecordCount") or 0) == 0
                and (deep_result.get("buildFamilyKeys") or [])
                else []
            ),
        ],
    }
    if not validation_only:
        _write_safe_report(report, Path(json_output), Path(md_output))
    return report


def _pattern_validation_result(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") != "accepted":
        return result
    return {
        **result,
        "observationIds": list(result.get("candidateObservationIds") or []),
        "patternIds": list(result.get("candidatePatternIds") or []),
    }


def _deep_record_validation_result(
    result: dict[str, Any],
    *,
    deep_payload: dict[str, Any],
) -> dict[str, Any]:
    if result.get("status") != "accepted":
        return result
    candidate_record_ids = list(result.get("candidateRecordIds") or [])
    records = list(deep_payload.get("deep_research_records") or [])
    if len(candidate_record_ids) != len(records):
        raise ValueError("validated deep-record IDs do not align with candidate records")
    return {
        **result,
        "recordIds": candidate_record_ids,
        "recordWrites": [
            {
                "recordId": record_id,
                "researchGroupId": str(record.get("research_group_id") or ""),
                "recordKind": str(record.get("record_kind") or ""),
                "title": str(record.get("title") or ""),
                "validationOnly": True,
            }
            for record_id, record in zip(candidate_record_ids, records, strict=True)
        ],
        "researchGroupIds": sorted(
            {
                str(item.get("research_group_id") or "")
                for item in deep_payload.get("deep_research_records") or []
                if str(item.get("research_group_id") or "")
            }
        ),
    }


def _attach_deep_record_ids(
    accepted_records: list[dict[str, Any]],
    deep_result: dict[str, Any],
) -> list[dict[str, Any]]:
    record_writes = list(deep_result.get("recordWrites") or [])
    if len(record_writes) != len(accepted_records):
        raise ValueError("deep-record write mapping does not align with accepted records")
    attached: list[dict[str, Any]] = []
    for summary, write in zip(accepted_records, record_writes, strict=True):
        if str(write.get("title") or "") != str(summary.get("titleZh") or "") or str(
            write.get("researchGroupId") or ""
        ) != str(summary.get("researchGroupId") or ""):
            raise ValueError("deep-record write mapping identity does not match accepted record")
        attached.append({**summary, "recordId": str(write.get("recordId") or "")})
    return attached


def _build_deep_record_payload(
    *,
    graph_service: graph_tools.GraphQueryService,
    review: dict[str, Any],
    reviewed_mappings: dict[tuple[str, str, str], dict[str, Any]],
    confirmed_review_components: dict[str, dict[str, Any]],
    source_skill_resolutions: dict[str, dict[str, Any]],
    version_context: dict[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for item in _deep_record_reviews(review):
        component_keys: list[str] = []
        component_mentions: list[dict[str, Any]] = []
        unresolved_components: list[dict[str, Any]] = []
        for component in item["components"]:
            resolution = _resolve_component(
                graph_service=graph_service,
                sample_id=item["sampleId"],
                component=component,
                reviewed_mappings=reviewed_mappings,
                confirmed_review_components=confirmed_review_components,
                source_skill_resolutions=source_skill_resolutions,
            )
            resolved_key = (
                str(resolution["componentKey"]) if resolution["status"] == "accepted" else None
            )
            if resolved_key:
                component_keys.append(resolved_key)
            else:
                unresolved_components.append(
                    {
                        "candidateName": component["candidateName"],
                        "role": component["role"],
                        "resolverQuery": component["resolverQuery"],
                        "reason": str(resolution.get("reason") or "resolver_missing"),
                        "actualNodeTypes": list(resolution.get("actualNodeTypes") or []),
                        "suggestedRoles": list(resolution.get("suggestedRoles") or []),
                    }
                )
            component_mentions.append(
                {
                    "candidate_name": component["candidateName"],
                    "role": component["role"],
                    "resolver_query": component["resolverQuery"],
                    "expected_node_types": component["expectedNodeTypes"],
                    "scope": component["scope"],
                    "component_key": resolved_key,
                    "resolution_status": _mention_resolution_status(resolution),
                }
            )
        typed_payload, typed_reference_issues = _canonicalize_typed_payload_references(
            typed_payload=item["typedPayload"],
            component_mentions=component_mentions,
        )
        if typed_reference_issues:
            deferred.append(
                {
                    "titleZh": item["title"],
                    "sampleId": item["sampleId"],
                    "reason": "invalid_schema",
                    "componentKeys": component_keys,
                    "caveats": [
                        "Name-based typedPayload references must match exactly one resolved "
                        "component declared in the same record."
                    ],
                    "validationIssues": typed_reference_issues,
                    "candidateKind": "deep_research_record",
                }
            )
            continue
        if item["recordKind"] in CONCRETE_RECORD_KINDS and not component_mentions:
            deferred.append(
                {
                    "titleZh": item["title"],
                    "sampleId": item["sampleId"],
                    "reason": "insufficient_research_depth",
                    "componentKeys": [],
                    "caveats": [
                        "Concrete research records require at least one resolved skill, support, "
                        "item, passive, jewel, ascendancy, or mechanic component."
                    ],
                    "candidateKind": "deep_research_record",
                }
            )
            continue
        record = {
            "research_group_id": item["researchGroupId"],
            "record_kind": item["recordKind"],
            "title": item["title"],
            "summary": item["summary"],
            "content": item["content"],
            "content_language": item["contentLanguage"],
            "length_exception_reason": item["lengthExceptionReason"],
            "component_keys": sorted(set(component_keys)),
            "component_mentions": component_mentions,
            "source_case_refs": [item["caseRef"]],
            "safe_evidence_refs": item["safeEvidenceRefs"],
            "conditions": item["conditions"],
            "failure_conditions": item["failureConditions"],
            "typed_payload": typed_payload,
            "class_key": item["classKey"],
            "ascendancy_key": item["ascendancyKey"],
            "extraction_method_version": item["extractionMethodVersion"],
            "record_schema_version": 1,
            "game_patch": version_context["gamePatch"],
            "passive_tree_version": version_context["passiveTreeVersion"],
            "pob_version_or_commit": version_context["pobVersionOrCommit"],
            "visibility": "creator_visible",
            "split": "train_context",
            "knowledge_scope": "global_seed",
            "status": "valid",
            "copy_safety_state": "passed",
        }
        validation = research_models.validate_researcher_output(
            {"schema_version": 5, "deep_research_records": [record]}
        )
        if validation.get("status") == "error":
            deferred.append(
                {
                    "titleZh": item["title"],
                    "sampleId": item["sampleId"],
                    "reason": str(validation.get("errorCode") or "invalid_deep_record"),
                    "componentKeys": component_keys,
                    "caveats": list(validation.get("caveats") or []),
                    "validationIssues": list(
                        (validation.get("facts") or {}).get("validationIssues") or []
                    ),
                    "candidateKind": "deep_research_record",
                }
            )
            continue
        records.append(record)
        accepted.append(
            {
                "titleZh": item["title"],
                "summaryZh": item["summary"],
                "recordKind": item["recordKind"],
                "researchGroupId": item["researchGroupId"],
                "sampleId": item["sampleId"],
                "componentKeys": component_keys,
                "componentRoles": [mention["role"] for mention in component_mentions],
                "components": [
                    {
                        "componentKey": mention["component_key"],
                        "role": mention["role"],
                    }
                    for mention in component_mentions
                    if mention["component_key"]
                ],
                "typedPayload": typed_payload,
                "unresolvedComponentCount": sum(
                    1 for mention in component_mentions if not mention["component_key"]
                ),
                "unresolvedComponents": unresolved_components,
            }
        )
    records, accepted, identity_deferred = _filter_deep_records_with_identity(
        records=records,
        accepted=accepted,
    )
    deferred.extend(identity_deferred)
    submitted_records = _deep_record_reviews(review)
    has_concrete_record = any(
        record["record_kind"] in CONCRETE_RECORD_KINDS and record["component_mentions"]
        for record in records
    )
    if submitted_records and not has_concrete_record:
        records.clear()
        accepted.clear()
        deferred.append(
            {
                "titleZh": "案例深度研究未达到最低标准",
                "sampleId": submitted_records[0]["sampleId"],
                "reason": "insufficient_case_research_depth",
                "componentKeys": [],
                "caveats": [
                    "A mature-build case must contribute at least one concrete record that names "
                    "the skills, supports, items, passives, jewels, ascendancy, or mechanics it "
                    "explains. Resolver coverage affects graph indexing, not content depth."
                ],
                "candidateKind": "research_case",
            }
        )
    return {"schema_version": 5, "deep_research_records": records}, accepted, deferred


def _canonicalize_typed_payload_references(
    *,
    typed_payload: dict[str, Any],
    component_mentions: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Resolve explicit name references without inferring research relationships."""

    normalized = json.loads(json.dumps(typed_payload))
    issues: list[dict[str, Any]] = []

    def resolve_name(
        value: Any,
        *,
        roles: set[str] | None,
        key_prefix: str,
        loc: list[Any],
    ) -> str | None:
        name = str(value or "").strip()
        if not name:
            issues.append(
                {
                    "loc": loc,
                    "msg": "component name must be a non-empty string",
                    "type": "value_error",
                }
            )
            return None
        keys = {
            str(mention.get("component_key") or "")
            for mention in component_mentions
            if str(mention.get("candidate_name") or "").strip().casefold() == name.casefold()
            and (roles is None or str(mention.get("role") or "") in roles)
            and str(mention.get("component_key") or "").startswith(key_prefix)
            and str(mention.get("resolution_status") or "") == "resolved"
        }
        if len(keys) != 1:
            issues.append(
                {
                    "loc": loc,
                    "msg": (
                        "component name must match exactly one resolved component in the same "
                        f"record: {name}"
                    ),
                    "type": "value_error",
                }
            )
            return None
        return next(iter(keys))

    packages = normalized.get("supportPackages")
    if isinstance(packages, list):
        canonical_packages: list[dict[str, Any]] = []
        for index, package in enumerate(packages):
            if not isinstance(package, dict):
                issues.append(
                    {
                        "loc": ["typed_payload", "supportPackages", index],
                        "msg": "support package must be an object",
                        "type": "value_error",
                    }
                )
                continue
            if set(package) == {"skillKey", "supportKeys"}:
                canonical_packages.append(package)
                continue
            if set(package) != {"skillName", "supportNames"}:
                issues.append(
                    {
                        "loc": ["typed_payload", "supportPackages", index],
                        "msg": (
                            "support package must use skillKey/supportKeys or "
                            "skillName/supportNames"
                        ),
                        "type": "value_error",
                    }
                )
                continue
            support_names = package.get("supportNames")
            if (
                not isinstance(support_names, list)
                or not support_names
                or any(not isinstance(value, str) for value in support_names)
            ):
                issues.append(
                    {
                        "loc": ["typed_payload", "supportPackages", index, "supportNames"],
                        "msg": "supportNames must be a non-empty string list",
                        "type": "value_error",
                    }
                )
                continue
            skill_key = resolve_name(
                package.get("skillName"),
                roles=None,
                key_prefix="skill:",
                loc=["typed_payload", "supportPackages", index, "skillName"],
            )
            support_keys = [
                resolve_name(
                    name,
                    roles={"support_modifier"},
                    key_prefix="support:",
                    loc=["typed_payload", "supportPackages", index, "supportNames", offset],
                )
                for offset, name in enumerate(support_names)
            ]
            if skill_key and all(support_keys):
                canonical_packages.append(
                    {
                        "skillKey": skill_key,
                        "supportKeys": [str(value) for value in support_keys],
                    }
                )
        normalized["supportPackages"] = canonical_packages

    support_exceptions = normalized.get("supportCoverageExceptions")
    if isinstance(support_exceptions, list):
        canonical_support_exceptions: list[dict[str, Any]] = []
        for index, exception in enumerate(support_exceptions):
            if not isinstance(exception, dict):
                issues.append(
                    {
                        "loc": ["typed_payload", "supportCoverageExceptions", index],
                        "msg": "support coverage exception must be an object",
                        "type": "value_error",
                    }
                )
                continue
            if set(exception) == {"skillKey", "reason", "detail"}:
                canonical_support_exceptions.append(exception)
                continue
            if set(exception) != {"skillName", "reason", "detail"}:
                issues.append(
                    {
                        "loc": ["typed_payload", "supportCoverageExceptions", index],
                        "msg": "support coverage exception must use skillKey or skillName",
                        "type": "value_error",
                    }
                )
                continue
            skill_key = resolve_name(
                exception.get("skillName"),
                roles=None,
                key_prefix="skill:",
                loc=["typed_payload", "supportCoverageExceptions", index, "skillName"],
            )
            if skill_key:
                canonical_support_exceptions.append(
                    {
                        "skillKey": skill_key,
                        "reason": exception.get("reason"),
                        "detail": exception.get("detail"),
                    }
                )
        normalized["supportCoverageExceptions"] = canonical_support_exceptions

    responsibilities = normalized.get("ascendancyResponsibilities")
    if isinstance(responsibilities, list):
        canonical_responsibilities: list[dict[str, Any]] = []
        for index, responsibility in enumerate(responsibilities):
            if not isinstance(responsibility, dict):
                issues.append(
                    {
                        "loc": ["typed_payload", "ascendancyResponsibilities", index],
                        "msg": "ascendancy responsibility must be an object",
                        "type": "value_error",
                    }
                )
                continue
            if set(responsibility) == {"componentKey", "responsibility"}:
                canonical_responsibilities.append(responsibility)
                continue
            if set(responsibility) != {"componentName", "responsibility"}:
                issues.append(
                    {
                        "loc": ["typed_payload", "ascendancyResponsibilities", index],
                        "msg": ("ascendancy responsibility must use componentKey or componentName"),
                        "type": "value_error",
                    }
                )
                continue
            component_key = resolve_name(
                responsibility.get("componentName"),
                roles={"passive_anchor", "keystone_transformer"},
                key_prefix="",
                loc=["typed_payload", "ascendancyResponsibilities", index, "componentName"],
            )
            if component_key:
                canonical_responsibilities.append(
                    {
                        "componentKey": component_key,
                        "responsibility": responsibility.get("responsibility"),
                    }
                )
        normalized["ascendancyResponsibilities"] = canonical_responsibilities

    gear_responsibilities = normalized.get("gearResponsibilities")
    if isinstance(gear_responsibilities, list):
        canonical_gear_responsibilities: list[dict[str, Any]] = []
        for index, responsibility in enumerate(gear_responsibilities):
            if not isinstance(responsibility, dict):
                issues.append(
                    {
                        "loc": ["typed_payload", "gearResponsibilities", index],
                        "msg": "gear responsibility must be an object",
                        "type": "value_error",
                    }
                )
                continue
            if set(responsibility) == {
                "componentKey",
                "responsibilityType",
                "responsibility",
            }:
                canonical_gear_responsibilities.append(responsibility)
                continue
            if set(responsibility) != {
                "componentName",
                "responsibilityType",
                "responsibility",
            }:
                issues.append(
                    {
                        "loc": ["typed_payload", "gearResponsibilities", index],
                        "msg": "gear responsibility must use componentKey or componentName",
                        "type": "value_error",
                    }
                )
                continue
            component_key = resolve_name(
                responsibility.get("componentName"),
                roles={"unique_enabler", "gear_base", "weapon_base"},
                key_prefix="",
                loc=["typed_payload", "gearResponsibilities", index, "componentName"],
            )
            if component_key:
                canonical_gear_responsibilities.append(
                    {
                        "componentKey": component_key,
                        "responsibilityType": responsibility.get("responsibilityType"),
                        "responsibility": responsibility.get("responsibility"),
                    }
                )
        normalized["gearResponsibilities"] = canonical_gear_responsibilities

    return normalized, issues


def _origin_family_by_case_ref(deep_payload: dict[str, Any]) -> dict[str, str]:
    records_by_group: dict[str, list[dict[str, Any]]] = {}
    for record in deep_payload.get("deep_research_records") or []:
        if not isinstance(record, dict):
            continue
        records_by_group.setdefault(str(record.get("research_group_id") or ""), []).append(record)

    result: dict[str, str] = {}
    for records in records_by_group.values():
        if not any(
            str(record.get("record_kind") or "") in research_identity.FAMILY_IDENTITY_RECORD_KINDS
            for record in records
        ):
            continue
        family = research_identity.infer_build_family(records)
        if family is None:
            continue
        for record in records:
            for case_ref in record.get("source_case_refs") or []:
                result[str(case_ref)] = family.key
    return result


def _missing_build_family_identity_deferred(
    *,
    deep_payload: dict[str, Any],
    accepted_records: list[dict[str, Any]],
    origin_family_by_case_ref: dict[str, str],
) -> list[dict[str, Any]]:
    records_by_group: dict[str, list[dict[str, Any]]] = {}
    for record in deep_payload.get("deep_research_records") or []:
        if isinstance(record, dict):
            records_by_group.setdefault(str(record.get("research_group_id") or ""), []).append(
                record
            )
    sample_by_group = {
        str(item.get("researchGroupId") or ""): str(item.get("sampleId") or "")
        for item in accepted_records
    }
    deferred: list[dict[str, Any]] = []
    for group_id, records in records_by_group.items():
        case_refs = {
            str(case_ref)
            for record in records
            for case_ref in record.get("source_case_refs") or []
            if str(case_ref)
        }
        if case_refs and all(case_ref in origin_family_by_case_ref for case_ref in case_refs):
            continue
        unresolved_identity_components = sorted(
            {
                str(mention.get("candidate_name") or "")
                for record in records
                for mention in record.get("component_mentions") or []
                if mention.get("role") in {"primary_damage", "clear_skill", "boss_skill"}
                and not mention.get("component_key")
                and str(mention.get("candidate_name") or "")
            }
        )
        deferred.append(
            {
                "titleZh": "案例缺少可确认的 BuildFamily 身份",
                "sampleId": sample_by_group.get(group_id, ""),
                "reason": "missing_build_family_identity",
                "componentKeys": [],
                "unresolvedIdentityComponents": unresolved_identity_components,
                "caveats": [
                    "Queue research requires one resolved ascendancy and one confirmed primary "
                    "skill before durable records can be deduplicated, ranked, and attributed. "
                    "The review remains available for repair, but no part of this case is written."
                ],
                "suggestedRepair": (
                    "Resolve the source-backed primary skill and ascendancy, then validate the "
                    "same safe review again. Do not guess a Family from a programmatic main-skill "
                    "label."
                ),
                "candidateKind": "research_case",
            }
        )
    return deferred


def _filter_mechanic_records_without_gear_context(
    *,
    review: dict[str, Any],
    deep_payload: dict[str, Any],
    accepted_records: list[dict[str, Any]],
    case_coverage: dict[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    declared_coverage = review.get("caseCoverage")
    if (
        not isinstance(declared_coverage, dict)
        or "gearRoles" not in declared_coverage
        or case_coverage.get("gearRoles") != "evidence_missing"
    ):
        return deep_payload, accepted_records, []

    kept_records: list[dict[str, Any]] = []
    kept_summaries: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for record, summary in zip(
        deep_payload.get("deep_research_records") or [], accepted_records, strict=True
    ):
        if record.get("record_kind") != "mechanic_chain":
            kept_records.append(record)
            kept_summaries.append(summary)
            continue
        deferred.append(
            {
                "titleZh": summary["titleZh"],
                "recordKind": summary["recordKind"],
                "sampleId": summary["sampleId"],
                "reason": "insufficient_gear_context",
                "componentKeys": summary["componentKeys"],
                "caveats": [
                    "The case has incomplete gear-role evidence. A mechanic chain may otherwise "
                    "generalize an item-specific rule while omitting the item that changes or "
                    "enables that rule. Preserve the skill/resource records, but do not persist "
                    "the mechanic conclusion until gear responsibilities are reviewed."
                ],
                "candidateKind": "deep_research_record",
            }
        )
    return (
        {**deep_payload, "deep_research_records": kept_records},
        kept_summaries,
        deferred,
    )


def _blocked_pattern_dependencies(
    deferred_records: list[dict[str, Any]],
) -> dict[str, list[set[str]]]:
    blocked: dict[str, list[set[str]]] = {}
    for item in deferred_records:
        if (
            item.get("candidateKind") != "deep_research_record"
            or item.get("recordKind") != "mechanic_chain"
        ):
            continue
        component_keys = {str(value) for value in item.get("componentKeys") or [] if str(value)}
        if len(component_keys) < 2:
            continue
        blocked.setdefault(str(item.get("sampleId") or ""), []).append(component_keys)
    return blocked


def _source_specific_components_by_case_ref(
    deep_payload: dict[str, Any],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for record in deep_payload.get("deep_research_records") or []:
        if not isinstance(record, dict):
            continue
        typed_payload = record.get("typed_payload") or {}
        if typed_payload.get("availability") != "source_specific_random":
            continue
        component_keys = {
            str(value)
            for value in typed_payload.get("sourceSpecificComponentKeys") or []
            if str(value)
        }
        for case_ref in record.get("source_case_refs") or []:
            result.setdefault(str(case_ref), set()).update(component_keys)
    return result


def _filter_deep_records_with_identity(
    *,
    records: list[dict[str, Any]],
    accepted: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep queue records canonicalizable without guessing Family identity."""

    records_by_group: dict[str, list[dict[str, Any]]] = {}
    resolved_skills_by_group: dict[str, set[str]] = {}
    for record in records:
        group_id = str(record["research_group_id"])
        records_by_group.setdefault(group_id, []).append(record)
        resolved_skills_by_group.setdefault(group_id, set()).update(
            str(mention.get("component_key") or "")
            for mention in record.get("component_mentions") or []
            if str(mention.get("component_key") or "").startswith("skill:")
            and str(mention.get("resolution_status") or "") == "resolved"
        )

    invalid_groups: dict[str, set[str]] = {}
    redundant_automatic_keys: dict[str, set[str]] = {}
    duplicate_titles: set[tuple[str, str, str]] = set()
    title_counts: dict[tuple[str, str, str], int] = {}
    for group_id, group_records in records_by_group.items():
        declared = {
            key
            for record in group_records
            for key in research_identity.family_core_skill_keys(record)
        }
        missing = declared - resolved_skills_by_group.get(group_id, set())
        if missing:
            invalid_groups[group_id] = missing
        redundant = declared & set(research_identity.automatic_family_skill_keys(group_records))
        if redundant:
            redundant_automatic_keys[group_id] = redundant
    for record in records:
        title_key = (
            str(record["research_group_id"]),
            str(record.get("record_kind") or ""),
            " ".join(str(record.get("title") or "").split()),
        )
        if not title_key[2]:
            continue
        title_counts[title_key] = title_counts.get(title_key, 0) + 1
        if title_counts[title_key] > 1:
            duplicate_titles.add(title_key)

    families = {
        group_id: research_identity.infer_build_family(group_records)
        for group_id, group_records in records_by_group.items()
        if group_id not in invalid_groups
    }
    kept_records: list[dict[str, Any]] = []
    kept_summaries: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for record, summary in zip(records, accepted, strict=True):
        group_id = str(record["research_group_id"])
        title_key = (
            group_id,
            str(record.get("record_kind") or ""),
            " ".join(str(record.get("title") or "").split()),
        )
        if title_key in duplicate_titles:
            deferred.append(
                {
                    "titleZh": summary["titleZh"],
                    "recordKind": summary["recordKind"],
                    "sampleId": summary["sampleId"],
                    "reason": "invalid_schema",
                    "componentKeys": summary["componentKeys"],
                    "caveats": [
                        "Duplicate record title within the same research group and record kind. "
                        "mechanicAudit.affectedRecords binds by exact title, so duplicates would "
                        "break audit binding and knowledge deduplication. Rename or merge the "
                        "duplicate records before accepting."
                    ],
                    "validationIssues": [
                        {
                            "loc": ["deep_research_records", "title"],
                            "msg": "duplicate (research_group_id, record_kind, title)",
                            "type": "value_error",
                        }
                    ],
                    "candidateKind": "deep_research_record",
                }
            )
            continue
        if group_id in invalid_groups:
            deferred.append(
                {
                    "titleZh": summary["titleZh"],
                    "recordKind": summary["recordKind"],
                    "sampleId": summary["sampleId"],
                    "reason": "invalid_schema",
                    "componentKeys": summary["componentKeys"],
                    "caveats": [
                        "typedPayload.familyCoreSkillKeys may only reference resolved active "
                        "skills from the same research group."
                    ],
                    "validationIssues": [
                        {
                            "loc": ["typed_payload", "familyCoreSkillKeys"],
                            "msg": "unresolved Family core skill keys: "
                            + ", ".join(sorted(invalid_groups[group_id])),
                            "type": "value_error",
                        }
                    ],
                    "candidateKind": "deep_research_record",
                }
            )
            continue
        if group_id in redundant_automatic_keys:
            deferred.append(
                {
                    "titleZh": summary["titleZh"],
                    "recordKind": summary["recordKind"],
                    "sampleId": summary["sampleId"],
                    "reason": "invalid_schema",
                    "componentKeys": summary["componentKeys"],
                    "caveats": [
                        "clear skills, boss skills, and triggered payloads are inferred by the "
                        "Family contract; do not repeat them in typedPayload.familyCoreSkillKeys."
                    ],
                    "validationIssues": [
                        {
                            "loc": ["typed_payload", "familyCoreSkillKeys"],
                            "msg": "remove automatically inferred Family skills: "
                            + ", ".join(sorted(redundant_automatic_keys[group_id])),
                            "type": "value_error",
                        }
                    ],
                    "candidateKind": "deep_research_record",
                }
            )
            continue
        if (
            record["record_kind"] == "skill_package"
            and any(
                mention.get("role") == "support_modifier"
                for mention in record.get("component_mentions") or []
            )
            and not research_identity.support_packages(record)
        ):
            deferred.append(
                {
                    "titleZh": summary["titleZh"],
                    "recordKind": summary["recordKind"],
                    "sampleId": summary["sampleId"],
                    "reason": "invalid_schema",
                    "componentKeys": summary["componentKeys"],
                    "caveats": [
                        "skill_package records with supports must preserve skill-to-support "
                        "ownership in typedPayload.supportPackages."
                    ],
                    "validationIssues": [
                        {
                            "loc": ["typed_payload", "supportPackages"],
                            "msg": "missing structured support ownership",
                            "type": "value_error",
                        }
                    ],
                    "candidateKind": "deep_research_record",
                }
            )
            continue
        family = families.get(group_id)
        if family is not None and research_identity.knowledge_key(record, family) is None:
            suggested_repair = (
                "Add a resolved component that identifies this knowledge unit. For a "
                "resource_engine based on ordinary stats or flasks, add lower_snake_case "
                "typedPayload.resourceMechanisms tags such as mana_leech or mana_flask."
            )
            deferred.append(
                {
                    "titleZh": summary["titleZh"],
                    "recordKind": summary["recordKind"],
                    "sampleId": summary["sampleId"],
                    "reason": "missing_knowledge_identity",
                    "componentKeys": summary["componentKeys"],
                    "caveats": [
                        "The record belongs to a BuildFamily but has no kind-specific canonical "
                        "identity, so accepting it would prevent evidence aggregation and deduplication."
                    ],
                    "suggestedRepair": suggested_repair,
                    "candidateKind": "deep_research_record",
                }
            )
            continue
        kept_records.append(record)
        kept_summaries.append(summary)
    return kept_records, kept_summaries, deferred


def _build_payload(
    *,
    graph_service: graph_tools.GraphQueryService,
    review: dict[str, Any],
    reviewed_mappings: dict[tuple[str, str, str], dict[str, Any]],
    confirmed_review_components: dict[str, dict[str, Any]],
    source_skill_resolutions: dict[str, dict[str, Any]],
    source_skill_manifest: dict[str, Any] | None,
    version_context: dict[str, str],
    origin_family_by_case_ref: dict[str, str],
    source_specific_components_by_case_ref: dict[str, set[str]],
    component_transfer_allowed: bool,
    blocked_pattern_dependencies: dict[str, list[set[str]]] | None = None,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    observations: list[dict[str, Any]] = []
    patterns: list[dict[str, Any]] = []
    accepted_summaries: list[dict[str, Any]] = []
    single_component_observations: list[dict[str, Any]] = []
    case_only_observations: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    blocked_pattern_dependencies = blocked_pattern_dependencies or {}
    for candidate in _candidate_reviews(review):
        sample_id = str(candidate["sampleId"])
        missing_fields = [
            field for field in ("title", "summary") if not str(candidate.get(field) or "").strip()
        ]
        if missing_fields:
            deferred.append(
                {
                    "titleZh": candidate.get("title") or candidate["patternType"],
                    "sampleId": sample_id,
                    "reason": "invalid_schema",
                    "componentKeys": [],
                    "caveats": [
                        "candidateReviews entry is missing required fields: "
                        + ", ".join(missing_fields)
                    ],
                    "candidateKind": "build_pattern",
                }
            )
            continue
        unstructured_source_mentions = _unstructured_candidate_source_mentions(
            candidate=candidate,
            source_skill_manifest=source_skill_manifest,
        )
        if unstructured_source_mentions:
            deferred.append(
                {
                    "titleZh": candidate["title"],
                    "sampleId": sample_id,
                    "reason": "unstructured_source_component_mention",
                    "componentKeys": [],
                    "caveats": [
                        "Candidate text names source skill/support components that are missing "
                        "from the same candidate's structured components: "
                        + ", ".join(unstructured_source_mentions)
                    ],
                    "candidateKind": "build_pattern",
                }
            )
            continue
        overclaim = research_models.case_observation_overclaim_error(
            title=str(candidate["title"]),
            summary=str(candidate["summary"]),
            planner_hint=str(candidate["plannerHint"]),
        )
        if overclaim:
            deferred.append(
                {
                    "titleZh": candidate["title"],
                    "sampleId": sample_id,
                    "reason": "overclaimed_pattern_confidence",
                    "componentKeys": [],
                    "caveats": [overclaim],
                    "candidateKind": "build_pattern",
                }
            )
            continue
        transfer_scope = str(candidate["transferScope"])
        if transfer_scope not in {"family", "component", "global"}:
            deferred.append(
                {
                    "titleZh": candidate["title"],
                    "sampleId": sample_id,
                    "reason": "invalid_schema",
                    "componentKeys": [],
                    "caveats": ["transferScope must be family, component, or global"],
                    "candidateKind": "build_pattern",
                }
            )
            continue
        if candidate["availability"] not in {"standard", "source_specific_random"}:
            deferred.append(
                {
                    "titleZh": candidate["title"],
                    "sampleId": sample_id,
                    "reason": "invalid_schema",
                    "componentKeys": [],
                    "caveats": ["availability must be standard or source_specific_random"],
                    "candidateKind": "build_pattern",
                }
            )
            continue
        explicitly_source_specific = candidate["availability"] == "source_specific_random"
        source_specific_component_names = {
            value.casefold(): value for value in candidate["sourceSpecificComponentNames"]
        }
        if explicitly_source_specific:
            if not source_specific_component_names:
                deferred.append(
                    {
                        "titleZh": candidate["title"],
                        "sampleId": sample_id,
                        "reason": "missing_source_specific_component",
                        "componentKeys": [],
                        "caveats": [
                            "A source_specific_random candidate must identify the random-instance "
                            "item in sourceSpecificComponentNames."
                        ],
                        "candidateKind": "build_pattern",
                    }
                )
                continue
            submitted_component_names = {
                str(component.get("candidateName") or "").casefold()
                for component in candidate["components"]
            }
            missing_source_components = sorted(
                original
                for normalized, original in source_specific_component_names.items()
                if normalized not in submitted_component_names
            )
            if missing_source_components:
                deferred.append(
                    {
                        "titleZh": candidate["title"],
                        "sampleId": sample_id,
                        "reason": "missing_source_specific_component",
                        "componentKeys": [],
                        "caveats": [
                            "sourceSpecificComponentNames must reference components submitted by "
                            "the same candidate: " + ", ".join(missing_source_components)
                        ],
                        "candidateKind": "build_pattern",
                    }
                )
                continue
        if transfer_scope == "global":
            deferred.append(
                {
                    "titleZh": candidate["title"],
                    "sampleId": sample_id,
                    "reason": "overclaimed_transfer_scope",
                    "componentKeys": [],
                    "caveats": [
                        "A single mature-build case may nominate a component-level transfer "
                        "candidate, but it cannot establish global knowledge."
                    ],
                    "candidateKind": "build_pattern",
                }
            )
            continue
        origin_family_key = origin_family_by_case_ref.get(str(candidate["caseRef"]))
        if (
            transfer_scope == "component"
            and not origin_family_key
            and not explicitly_source_specific
        ):
            deferred.append(
                {
                    "titleZh": candidate["title"],
                    "sampleId": sample_id,
                    "reason": "missing_transfer_origin_family",
                    "componentKeys": [],
                    "caveats": [
                        "A transferable candidate needs a resolved origin Build Family so "
                        "cross-Family evidence can be counted without guessing."
                    ],
                    "candidateKind": "build_pattern",
                }
            )
            continue
        if (
            transfer_scope == "component"
            and not component_transfer_allowed
            and not explicitly_source_specific
        ):
            deferred.append(
                {
                    "titleZh": candidate["title"],
                    "sampleId": sample_id,
                    "reason": "insufficient_transfer_evidence",
                    "componentKeys": [],
                    "caveats": [
                        "Component-level transfer requires explicit gear responsibilities or a "
                        "reviewed not_applicable gear boundary. This prevents an omitted identity "
                        "item from turning a source-specific mechanism into reusable planner advice."
                    ],
                    "candidateKind": "build_pattern",
                }
            )
            continue
        components = list(candidate["components"])
        components_to_resolve = (
            [
                component
                for component in components
                if str(component.get("candidateName") or "").casefold()
                in source_specific_component_names
            ]
            if explicitly_source_specific
            else components
        )
        resolved_components = []
        component_roles: dict[str, str] = {}
        component_keys: list[str] = []
        component_resolution_summaries: list[dict[str, Any]] = []
        candidate_deferred: list[dict[str, Any]] = []
        for component in components_to_resolve:
            resolution = _resolve_component(
                graph_service=graph_service,
                sample_id=sample_id,
                component=component,
                reviewed_mappings=reviewed_mappings,
                confirmed_review_components=confirmed_review_components,
                source_skill_resolutions=source_skill_resolutions,
            )
            if resolution["status"] != "accepted":
                candidate_deferred.append(resolution)
                continue
            component_key = str(resolution["componentKey"])
            role = str(component["role"])
            resolved_components.append(
                {
                    "component_key": component_key,
                    "role": role,
                    "resolution": resolution["evidence"],
                }
            )
            component_keys.append(component_key)
            component_roles[component_key] = role
            component_resolution_summaries.append(
                {
                    "componentKey": component_key,
                    "candidateName": str(component.get("candidateName") or ""),
                    "resolverStatus": resolution["resolverStatus"],
                    "resolutionSource": resolution["resolutionSource"],
                }
            )
        if candidate_deferred:
            if explicitly_source_specific:
                resolved_components = []
                component_roles = {}
                component_keys = []
                component_resolution_summaries = []
            else:
                deferred.append(
                    {
                        "titleZh": candidate["title"],
                        "sampleId": sample_id,
                        "reason": candidate_deferred[0]["reason"],
                        "componentKeys": [item["componentKey"] for item in candidate_deferred],
                        "componentReasons": candidate_deferred,
                    }
                )
                continue
        candidate_key_set = set(component_keys)
        blocked_by_record = next(
            (
                blocked_keys
                for blocked_keys in blocked_pattern_dependencies.get(sample_id, [])
                if len(candidate_key_set) >= 2 and candidate_key_set <= blocked_keys
            ),
            None,
        )
        if blocked_by_record is not None:
            deferred.append(
                {
                    "titleZh": candidate["title"],
                    "sampleId": sample_id,
                    "reason": "supporting_record_deferred",
                    "componentKeys": component_keys,
                    "caveats": [
                        "This pattern is fully contained in a deferred mechanic-chain component "
                        "set. It cannot enter planner memory through a second write path until the "
                        "supporting mechanic record passes acceptance."
                    ],
                    "candidateKind": "build_pattern",
                }
            )
            continue
        base = {
            "source_case_refs": [candidate["caseRef"]],
            "safe_evidence_refs": candidate["safeEvidenceRefs"],
            "game_patch": version_context["gamePatch"],
            "passive_tree_version": version_context["passiveTreeVersion"],
            "pob_version_or_commit": version_context["pobVersionOrCommit"],
            "visibility": "creator_visible",
            "split": "train_context",
            "knowledge_scope": "global_seed",
        }
        observation = {
            "observation_type": candidate["patternType"],
            "title": candidate["title"],
            "summary": candidate["summary"],
            "axes": candidate["axes"],
            "components": resolved_components,
            **base,
        }
        pattern = {
            "pattern_type": candidate["patternType"],
            "title": candidate["title"],
            "summary": candidate["summary"],
            "component_keys": component_keys,
            "component_roles": component_roles,
            "confidence_tier": "case_observation",
            "transfer_scope": transfer_scope,
            "applicability_axes": candidate["axes"] if transfer_scope != "family" else [],
            "applicability_requirements": candidate["applicabilityRequirements"],
            "exclusion_conditions": candidate["exclusionConditions"],
            "transfer_rationale": candidate["transferRationale"] or None,
            "origin_family_keys": [origin_family_key] if origin_family_key else [],
            "sample_count": 1,
            "family_count": 1,
            "source_diversity_count": 1,
            "denominator": 1,
            "context_requirements": [
                {"context_type": "lifecycle_stage_requirement", "stages": ["endgame_mature"]},
                {
                    "context_type": "verification_gate_requirement",
                    "task": candidate["verificationGate"],
                },
            ],
            "planner_hint": candidate["plannerHint"],
            "verification_tasks": candidate["verificationTasks"],
            **base,
        }
        is_relational_pattern = len(set(component_keys)) >= 2
        source_specific_keys = source_specific_components_by_case_ref.get(
            str(candidate["caseRef"]), set()
        )
        is_source_specific_random = candidate["availability"] == "source_specific_random" or bool(
            set(component_keys) & source_specific_keys
        )
        candidate_patterns = (
            [pattern] if is_relational_pattern and not is_source_specific_random else []
        )
        candidate_validation = research_models.validate_researcher_output(
            {
                "schema_version": 4,
                "build_design_observations": [observation],
                "patterns": candidate_patterns,
            }
        )
        if candidate_validation.get("status") == "error":
            deferred.append(
                {
                    "titleZh": candidate["title"],
                    "sampleId": sample_id,
                    "reason": str(candidate_validation.get("errorCode") or "invalid_candidate"),
                    "componentKeys": component_keys,
                    "caveats": list(candidate_validation.get("caveats") or []),
                    "validationIssues": list(
                        (candidate_validation.get("facts") or {}).get("validationIssues") or []
                    ),
                }
            )
            continue
        observations.append(observation)
        summary = {
            "titleZh": candidate["title"],
            "summaryZh": candidate["summary"],
            "confidenceTier": "case_observation",
            "transferScope": transfer_scope,
            "originFamilyKeys": [origin_family_key] if origin_family_key else [],
            "availability": ("source_specific_random" if is_source_specific_random else "standard"),
            "sampleId": sample_id,
            "componentKeys": component_keys,
            "componentResolutions": component_resolution_summaries,
        }
        if explicitly_source_specific:
            summary["sourceSpecificComponentNames"] = list(source_specific_component_names.values())
            summary["componentIndexing"] = (
                "resolved_source_specific_components"
                if component_keys
                else "omitted_unresolved_source_specific_components"
            )
        if is_relational_pattern and not is_source_specific_random:
            patterns.append(pattern)
            accepted_summaries.append(summary)
        elif is_source_specific_random:
            summary["observationOnlyReason"] = "source_specific_random"
            case_only_observations.append(summary)
        else:
            single_component_observations.append(summary)
    return (
        {"schema_version": 4, "build_design_observations": observations, "patterns": patterns},
        accepted_summaries,
        single_component_observations,
        case_only_observations,
        deferred,
    )


def _source_skill_id_resolutions(
    *,
    graph_service: graph_tools.GraphQueryService,
    source_skill_manifest: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Confirm unique packet skill IDs without inferring how the build uses them."""

    if not isinstance(source_skill_manifest, dict):
        return {}
    ids_by_name: dict[str, set[str]] = {}
    display_names: dict[str, str] = {}
    for group in source_skill_manifest.get("activeSkillGroups") or []:
        if not isinstance(group, dict):
            continue
        for skill in group.get("activeSkills") or []:
            if not isinstance(skill, dict):
                continue
            name = str(skill.get("name") or "").strip()
            skill_id = str(skill.get("skillId") or "").strip()
            # Item/passive-granted skills carry internal ids rather than gem
            # names; the resolver cannot confirm them, so skip them instead of
            # issuing a guaranteed-miss graph lookup.
            if not name or not skill_id or str(skill.get("nameSource") or "gem_name") != "gem_name":
                continue
            normalized_name = name.casefold()
            stable_key = skill_id if skill_id.startswith("skill:") else f"skill:{skill_id}"
            ids_by_name.setdefault(normalized_name, set()).add(stable_key)
            display_names.setdefault(normalized_name, name)

    resolutions: dict[str, dict[str, Any]] = {}
    for normalized_name, stable_keys in ids_by_name.items():
        if len(stable_keys) != 1:
            continue
        stable_key = next(iter(stable_keys))
        result = graph_service.run_tool(
            "resolve_graph_component",
            {
                "query": stable_key,
                "expected_node_types": ["active_skill"],
                "scope": "player",
            },
        )
        resolved_key = str((result.get("resolvedSubject") or {}).get("stableKey") or "")
        if result.get("status") != "resolved" or resolved_key != stable_key:
            continue
        resolutions[normalized_name] = {
            "candidateName": display_names[normalized_name],
            "componentKey": stable_key,
            "resolverResult": result,
        }
    return resolutions


def _source_support_compatibility_diagnostics(
    *,
    graph_service: graph_tools.GraphQueryService,
    source_skill_manifest: dict[str, Any] | None,
    source_skill_resolutions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Verify unambiguous source socket groups without guessing multi-skill ownership.

    A source group identifies the active gem, but a single active gem can grant more than one
    physical active-skill endpoint (for example, a setup/buff endpoint and its damage payload).
    Compatibility is therefore checked against every statically linked endpoint of the same gem.
    Explicit component queries keep their exact-endpoint semantics elsewhere.
    """

    empty = {
        "sourceSupportCompatibilityCheckedPairCount": 0,
        "unsupportedSourceSupportPairCount": 0,
        "unsupportedSourceSupportPairs": [],
        "unverifiedSourceSupportPairCount": 0,
        "unverifiedSourceSupportPairs": [],
        "multiActiveSkillSupportGroupCount": 0,
        "sourceSupportCompatibilityBlocked": False,
    }
    if not isinstance(source_skill_manifest, dict):
        return empty

    checked_count = 0
    unsupported: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []
    multi_active_count = 0
    for group in source_skill_manifest.get("activeSkillGroups") or []:
        if not isinstance(group, dict):
            continue
        group_ref = str(group.get("groupRef") or "")
        active_skills = [
            item
            for item in group.get("activeSkills") or []
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        supports = [
            item
            for item in group.get("supports") or []
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        if not supports:
            continue
        if len(active_skills) != 1:
            if len(active_skills) > 1:
                multi_active_count += 1
            continue

        active_name = str(active_skills[0].get("name") or "").strip()
        active_resolution = source_skill_resolutions.get(active_name.casefold()) or {}
        skill_key = str(active_resolution.get("componentKey") or "")
        if not skill_key:
            unverified.extend(
                {
                    "groupRef": group_ref,
                    "skillName": active_name,
                    "supportName": str(item.get("name") or "").strip(),
                    "reason": "source_skill_not_resolved",
                }
                for item in supports
            )
            continue

        resolved_supports: list[tuple[str, str]] = []
        for support in supports:
            support_name = str(support.get("name") or "").strip()
            support_key = _resolve_source_support_key(
                graph_service=graph_service,
                support=support,
            )
            if not support_key:
                unverified.append(
                    {
                        "groupRef": group_ref,
                        "skillName": active_name,
                        "skillKey": skill_key,
                        "supportName": support_name,
                        "reason": "source_support_not_resolved",
                    }
                )
                continue
            resolved_supports.append((support_name, support_key))

        endpoint_skill_keys = _active_gem_endpoint_keys(
            snapshot=graph_service.snapshot,
            skill_key=skill_key,
        )
        endpoint_group_results: dict[str, dict[str, physical_graph.ComputedFactResult]] = {}
        if len(resolved_supports) == len(supports):
            for endpoint_skill_key in endpoint_skill_keys:
                try:
                    endpoint_group_results[endpoint_skill_key] = {
                        str(result.request.inputs["support_key"]): result
                        for result in physical_graph.support_skill_group_candidates(
                            snapshot=graph_service.snapshot,
                            support_keys=[support_key for _, support_key in resolved_supports],
                            skill_key=endpoint_skill_key,
                        )
                    }
                except ValueError:
                    continue

        for support_name, support_key in resolved_supports:
            endpoint_results = [
                (endpoint_skill_key, results[support_key])
                for endpoint_skill_key, results in endpoint_group_results.items()
                if support_key in results
            ]
            known_endpoint_result = next(
                (
                    (endpoint_skill_key, candidate)
                    for endpoint_skill_key, candidate in endpoint_results
                    if candidate.status == "known"
                ),
                None,
            )
            all_endpoints_unsupported = bool(endpoint_results) and all(
                candidate.status == "unsupported" for _, candidate in endpoint_results
            )
            selected_endpoint_result = known_endpoint_result or (
                endpoint_results[0] if all_endpoints_unsupported else None
            )
            if endpoint_results and selected_endpoint_result is None:
                unverified.append(
                    {
                        "groupRef": group_ref,
                        "skillName": active_name,
                        "skillKey": skill_key,
                        "evaluatedSkillKeys": endpoint_skill_keys,
                        "supportName": support_name,
                        "supportKey": support_key,
                        "reason": "compatibility_unknown_across_gem_endpoints",
                    }
                )
                continue
            group_result = (
                selected_endpoint_result[1] if selected_endpoint_result is not None else None
            )
            matched_skill_key = (
                selected_endpoint_result[0] if selected_endpoint_result is not None else skill_key
            )
            if group_result is not None:
                status = group_result.status
                facts = group_result.facts
                source_refs = list(group_result.source_refs)
                evaluation_mode = "support_group_fixed_point"
            else:
                result = graph_service.run_tool(
                    "support_skill_candidate",
                    {"support_key": support_key, "skill_key": skill_key},
                )
                status = str(result.get("status") or "")
                facts = result.get("facts") or {}
                source_refs = list(result.get("sourceRefs") or [])
                evaluation_mode = "single_pair"
            if status == "unsupported":
                unsupported.append(
                    {
                        "groupRef": group_ref,
                        "skillName": active_name,
                        "skillKey": skill_key,
                        "supportName": support_name,
                        "supportKey": support_key,
                        "evaluatedSkillKeys": endpoint_skill_keys,
                        "excludedReason": str(
                            facts.get("excluded_reason") or "support_not_compatible"
                        ),
                        "sourceRefs": source_refs,
                        "evaluationMode": evaluation_mode,
                    }
                )
                checked_count += 1
                continue
            if status == "known":
                checked_count += 1
                continue
            unverified.append(
                {
                    "groupRef": group_ref,
                    "skillName": active_name,
                    "skillKey": skill_key,
                    "evaluatedSkillKeys": endpoint_skill_keys,
                    "matchedSkillKey": matched_skill_key,
                    "supportName": support_name,
                    "supportKey": support_key,
                    "reason": str(
                        (result.get("errorCode") if group_result is None else None)
                        or status
                        or "compatibility_unknown"
                    ),
                }
            )

    return {
        "sourceSupportCompatibilityCheckedPairCount": checked_count,
        "unsupportedSourceSupportPairCount": len(unsupported),
        "unsupportedSourceSupportPairs": unsupported,
        "unverifiedSourceSupportPairCount": len(unverified),
        "unverifiedSourceSupportPairs": unverified[:12],
        "unverifiedSourceSupportPairsTruncated": len(unverified) > 12,
        "multiActiveSkillSupportGroupCount": multi_active_count,
        "sourceSupportCompatibilityBlocked": bool(unsupported),
    }


def _active_gem_endpoint_keys(
    *,
    snapshot: physical_graph.GraphSnapshot,
    skill_key: str,
) -> list[str]:
    """Return all active-skill endpoints granted by the same statically known active gem."""

    nodes_by_key = {node.stable_key: node for node in snapshot.nodes}
    active_gem_keys = {
        edge.target_key
        for edge in snapshot.edges
        if edge.edge_type == "granted_by"
        and edge.source_key == skill_key
        and nodes_by_key.get(edge.target_key) is not None
        and nodes_by_key[edge.target_key].node_type == "skill_gem"
    }
    endpoint_keys = {skill_key}
    endpoint_keys.update(
        edge.target_key
        for edge in snapshot.edges
        if edge.edge_type == "grants_skill"
        and edge.source_key in active_gem_keys
        and nodes_by_key.get(edge.target_key) is not None
        and nodes_by_key[edge.target_key].node_type == "active_skill"
    )
    return sorted(endpoint_keys)


def _resolve_source_support_key(
    *,
    graph_service: graph_tools.GraphQueryService,
    support: dict[str, Any],
) -> str | None:
    support_name = str(support.get("name") or "").strip()
    gem_id = str(support.get("gemId") or "").strip()
    queries: list[str] = []
    if gem_id:
        queries.append(gem_id if gem_id.startswith("support:") else f"support:{gem_id}")
    if support_name and support_name not in queries:
        queries.append(support_name)
    for query in queries:
        result = graph_service.run_tool(
            "resolve_graph_component",
            {
                "query": query,
                "expected_node_types": ["support_gem"],
                "scope": "any",
            },
        )
        resolved_key = str((result.get("resolvedSubject") or {}).get("stableKey") or "")
        if result.get("status") == "resolved" and resolved_key.startswith("support:"):
            return resolved_key
    return None


def _filter_records_with_unsupported_source_supports(
    *,
    deep_payload: dict[str, Any],
    accepted_records: list[dict[str, Any]],
    diagnostics: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    conflicts = [
        item
        for item in diagnostics.get("unsupportedSourceSupportPairs") or []
        if str(item.get("skillKey") or "") and str(item.get("supportKey") or "")
    ]
    if not conflicts:
        return deep_payload, accepted_records, []

    kept_records: list[dict[str, Any]] = []
    kept_summaries: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for record, summary in zip(
        deep_payload.get("deep_research_records") or [],
        accepted_records,
        strict=True,
    ):
        component_keys = {str(value) for value in record.get("component_keys") or []}
        claim_segments = _deep_record_claim_segments(record)
        matched: list[dict[str, Any]] = []
        for item in conflicts:
            structured_pair = {
                str(item["skillKey"]),
                str(item["supportKey"]),
            } <= component_keys
            same_name_different_skill_key = any(
                str(mention.get("candidate_name") or "").strip().casefold()
                == str(item.get("skillName") or "").strip().casefold()
                and str(mention.get("component_key") or "").startswith("skill:")
                and str(mention.get("component_key") or "") != str(item["skillKey"])
                for mention in record.get("component_mentions") or []
            )
            exact_same_statement = (
                any(
                    _text_mentions_exact_name(segment, str(item.get("skillName") or ""))
                    and _text_mentions_exact_name(segment, str(item.get("supportName") or ""))
                    for segment in claim_segments
                )
                and not same_name_different_skill_key
            )
            if structured_pair or exact_same_statement:
                matched.append(
                    {
                        **item,
                        "matchedBy": (
                            "structured_components" if structured_pair else "exact_same_statement"
                        ),
                    }
                )
        if not matched:
            kept_records.append(record)
            kept_summaries.append(summary)
            continue
        deferred.append(
            {
                "titleZh": summary["titleZh"],
                "recordKind": summary["recordKind"],
                "sampleId": summary["sampleId"],
                "reason": "unsupported_source_skill_support_pair",
                "componentKeys": summary["componentKeys"],
                "unsupportedPairs": matched,
                "caveats": [
                    "The source socket group has exactly one active skill, and the static "
                    "support contract rejects at least one co-mentioned support. Component "
                    "resolution alone cannot authorize the mechanic claim."
                ],
                "candidateKind": "deep_research_record",
            }
        )
    return (
        {**deep_payload, "deep_research_records": kept_records},
        kept_summaries,
        deferred,
    )


def _filter_records_with_unsupported_structured_support_packages(
    *,
    graph_service: graph_tools.GraphQueryService,
    deep_payload: dict[str, Any],
    accepted_records: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate explicit Researcher support ownership without inferring source-group ownership."""

    display_names = {node.stable_key: node.display_name for node in graph_service.snapshot.nodes}
    kept_records: list[dict[str, Any]] = []
    kept_summaries: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for record, summary in zip(
        deep_payload.get("deep_research_records") or [],
        accepted_records,
        strict=True,
    ):
        unsupported_pairs: list[dict[str, Any]] = []
        packages = (record.get("typed_payload") or {}).get("supportPackages") or []
        for package in packages:
            if not isinstance(package, dict):
                continue
            skill_key = str(package.get("skillKey") or "")
            support_keys = [str(value) for value in package.get("supportKeys") or [] if str(value)]
            if not skill_key or not support_keys:
                continue
            try:
                results = physical_graph.support_skill_group_candidates(
                    snapshot=graph_service.snapshot,
                    support_keys=support_keys,
                    skill_key=skill_key,
                )
            except ValueError:
                # Resolver/schema validation owns missing or mistyped endpoints. Unknown static
                # contracts remain a Researcher caveat rather than an automatic rejection.
                continue
            for result in results:
                if result.status != "unsupported":
                    continue
                support_key = str(result.request.inputs.get("support_key") or "")
                unsupported_pairs.append(
                    {
                        "skillKey": skill_key,
                        "skillName": display_names.get(skill_key, skill_key),
                        "supportKey": support_key,
                        "supportName": display_names.get(support_key, support_key),
                        "excludedReason": str(
                            result.facts.get("excluded_reason") or "support_not_compatible"
                        ),
                        "sourceRefs": list(result.source_refs),
                        "evaluationMode": "review_support_package_fixed_point",
                    }
                )
        if not unsupported_pairs:
            kept_records.append(record)
            kept_summaries.append(summary)
            continue
        pair_summary = "; ".join(
            f"{item['skillName']}[{item['skillKey']}] + {item['supportName']}[{item['supportKey']}]"
            f" (excluded: {item['excludedReason']})"
            for item in unsupported_pairs[:5]
        )
        deferred.append(
            {
                "titleZh": summary["titleZh"],
                "recordKind": summary["recordKind"],
                "sampleId": summary["sampleId"],
                "reason": "unsupported_structured_skill_support_pair",
                "componentKeys": summary["componentKeys"],
                "unsupportedPairs": unsupported_pairs,
                "caveats": [
                    "typedPayload.supportPackages explicitly assigns each support to an active "
                    "skill, and the static fixed-point contract rejects at least one submitted "
                    "pair. This check validates the Researcher claim and does not infer ownership "
                    "for an unstructured multi-active source group.",
                    "Unsupported pairs: " + pair_summary + ". Fix: move each rejected support into "
                    "the supportPackages entry of the active skill it actually links to in the "
                    "source group (meta hosts must not own the supports of their socketed skill), "
                    "or remove it from supportPackages and describe it in content only.",
                ],
                "candidateKind": "deep_research_record",
            }
        )
    return (
        {**deep_payload, "deep_research_records": kept_records},
        kept_summaries,
        deferred,
    )


def _deep_record_claim_segments(record: dict[str, Any]) -> list[str]:
    text_values = [
        record.get("title"),
        record.get("summary"),
        record.get("content"),
        *(record.get("conditions") or []),
        *(record.get("failure_conditions") or []),
    ]
    return [
        segment.strip()
        for value in text_values
        if isinstance(value, str)
        for segment in re.split(r"(?<=[.!?。！？])|\n", value)
        if segment.strip()
    ]


def _text_mentions_exact_name(text: str, name: str) -> bool:
    normalized_name = " ".join(name.split())
    if not normalized_name:
        return False
    pattern = re.escape(normalized_name).replace(r"\ ", r"\s+")
    return re.search(rf"(?<![\w]){pattern}(?![\w])", text, flags=re.IGNORECASE) is not None


def _resolve_component(
    *,
    graph_service: graph_tools.GraphQueryService,
    sample_id: str,
    component: dict[str, Any],
    reviewed_mappings: dict[tuple[str, str, str], dict[str, Any]],
    confirmed_review_components: dict[str, dict[str, Any]],
    source_skill_resolutions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    component_key = str(component.get("componentKey") or "")
    candidate_name = str(component.get("candidateName") or "")
    resolver_query = str(component.get("resolverQuery") or candidate_name or component_key)
    expected_node_types = list(component.get("expectedNodeTypes") or [])
    scope = str(component.get("scope") or "any")
    query = resolver_query or candidate_name or component_key
    result = graph_service.run_tool(
        "resolve_graph_component",
        {"query": query, "expected_node_types": expected_node_types, "scope": scope},
    )
    status = str(result.get("status") or "")
    direct_candidates = sorted(
        {
            str(value)
            for value in (result.get("facts") or {}).get("candidate_keys") or []
            if str(value)
        }
    )
    if status == "resolved":
        resolved_key = str((result.get("resolvedSubject") or {}).get("stableKey") or "")
        if not component_key or resolved_key == component_key:
            return {
                "status": "accepted",
                "resolverStatus": status,
                "resolutionSource": "direct_resolver",
                "componentKey": resolved_key,
                "evidence": _evidence_from_resolver(result, resolved_key),
            }
        return {
            "status": "deferred",
            "reason": "resolver_key_mismatch",
            "componentKey": component_key,
            "candidateName": candidate_name,
            "resolverStatus": status,
            "resolvedKey": resolved_key,
            "candidateKeys": direct_candidates,
            "expectedNodeTypes": expected_node_types,
            "scope": scope,
        }
    source_resolution = source_skill_resolutions.get(candidate_name.strip().casefold())
    source_key = str((source_resolution or {}).get("componentKey") or "")
    source_result = (source_resolution or {}).get("resolverResult")
    source_key_allowed = not expected_node_types or "active_skill" in expected_node_types
    source_matches_direct_result = status != "ambiguous" or source_key in direct_candidates
    if (
        source_key
        and isinstance(source_result, dict)
        and source_key_allowed
        and source_matches_direct_result
    ):
        if component_key and component_key != source_key:
            return {
                "status": "deferred",
                "reason": "source_manifest_key_mismatch",
                "componentKey": component_key,
                "candidateName": candidate_name,
                "resolverStatus": status,
                "sourceManifestKey": source_key,
                "candidateKeys": direct_candidates,
                "expectedNodeTypes": expected_node_types,
                "scope": scope,
            }
        return {
            "status": "accepted",
            "resolverStatus": "resolved",
            "resolutionSource": "source_skill_manifest",
            "componentKey": source_key,
            "evidence": _evidence_from_resolver(source_result, source_key),
        }
    if status == "ambiguous":
        if not component_key:
            return {
                "status": "deferred",
                "reason": "ambiguous_endpoint_requires_reviewed_mapping",
                "componentKey": "",
                "candidateName": candidate_name,
                "resolverStatus": status,
                "candidateKeys": direct_candidates,
                "expectedNodeTypes": expected_node_types,
                "scope": scope,
            }
        current_candidate = _resolver_candidate(result, component_key)
        if current_candidate is None:
            return {
                "status": "deferred",
                "reason": "ambiguous_endpoint_not_in_current_resolver_candidates",
                "componentKey": component_key,
                "candidateName": candidate_name,
                "resolverStatus": status,
                "candidateKeys": direct_candidates,
                "expectedNodeTypes": expected_node_types,
                "scope": scope,
            }
        confirmation = confirmed_review_components.get(component_key)
        if confirmation is not None:
            return {
                "status": "accepted",
                "resolverStatus": "resolved",
                "resolutionSource": "intra_review_stable_confirmation",
                "componentKey": component_key,
                "evidence": _evidence_from_resolver(confirmation, component_key),
            }
        reviewed = _matching_reviewed_mapping(
            sample_id=sample_id,
            candidate_name=candidate_name,
            component_key=component_key,
            reviewed_mappings=reviewed_mappings,
        )
        if reviewed is None:
            return {
                "status": "deferred",
                "reason": "ambiguous_endpoint_requires_reviewed_mapping",
                "componentKey": component_key,
                "candidateName": candidate_name,
                "resolverStatus": status,
            }
        return {
            "status": "accepted",
            "resolverStatus": status,
            "resolutionSource": "reviewed_mapping",
            "componentKey": component_key,
            "evidence": _evidence_from_reviewed_mapping(result, reviewed, current_candidate),
        }
    discovery = graph_service.run_tool(
        "search_graph_components",
        {
            "query": resolver_query or candidate_name,
            "expected_node_types": expected_node_types,
            "scope": scope,
            "limit": 20,
        },
    )
    discovered = list((discovery.get("facts") or {}).get("candidates") or [])
    if len(discovered) == 1:
        discovered_key = str(discovered[0].get("stableKey") or "")
        confirmation = graph_service.run_tool(
            "resolve_graph_component",
            {"query": discovered_key, "expected_node_types": expected_node_types, "scope": scope},
        )
        if confirmation.get("status") == "resolved":
            return {
                "status": "accepted",
                "resolverStatus": "resolved",
                "resolutionSource": "lexical_discovery_then_stable_confirmation",
                "componentKey": discovered_key,
                "evidence": _evidence_from_resolver(confirmation, discovered_key),
            }
    if len(discovered) > 1:
        status = "ambiguous"
    if status in {"missing", "unknown"} and expected_node_types:
        mismatch_candidates = _type_mismatch_candidates(
            graph_service=graph_service,
            candidate_name=candidate_name,
        )
        if len(mismatch_candidates) == 1:
            mismatch = mismatch_candidates[0]
            actual_node_type = str(mismatch.get("nodeType") or "")
            return {
                "status": "deferred",
                "reason": "component_type_mismatch",
                "componentKey": component_key,
                "candidateName": candidate_name,
                "resolverStatus": status,
                "resolverQuery": resolver_query,
                "expectedNodeTypes": expected_node_types,
                "actualNodeTypes": [actual_node_type],
                "scope": scope,
                "discoveredCandidates": [str(mismatch.get("stableKey") or "")],
                "suggestedRoles": NODE_TYPE_ROLE_SUGGESTIONS.get(actual_node_type, []),
            }
    reason = "source_coverage_gap" if status in {"missing", "unknown"} else f"resolver_{status}"
    return {
        "status": "deferred",
        "reason": reason,
        "componentKey": component_key,
        "candidateName": candidate_name,
        "resolverStatus": status,
        "resolverQuery": resolver_query,
        "expectedNodeTypes": expected_node_types,
        "scope": scope,
        "discoveredCandidates": [str(item.get("stableKey") or "") for item in discovered],
    }


def _confirmed_review_component_resolutions(
    *,
    graph_service: graph_tools.GraphQueryService,
    review: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Collect stable-key lookups that this review explicitly resolved against the current graph.

    A component qualifies when it carries an explicit ``componentKey``: either the resolver
    query is the key itself (key-authored lookup), or the key was resolved elsewhere in the
    same review (name-authored component whose key is already proven by a sibling component).
    The qualifying key is re-resolved against the current graph and only accepted when the
    graph resolves to exactly that key, so a stale or invented key never passes here. The
    caller still enforces ``_resolver_candidate`` (key must be a candidate of the component's
    display name) before this confirmation is consulted, so a name pointing at the wrong
    variant cannot be confirmed through this path either.
    """

    components = [
        component
        for item in [*_candidate_reviews(review), *_deep_record_reviews(review)]
        for component in item["components"]
    ]
    confirmed: dict[str, dict[str, Any]] = {}
    for component in components:
        component_key = str(component.get("componentKey") or "").strip()
        if not component_key or component_key in confirmed:
            continue
        result = graph_service.run_tool(
            "resolve_graph_component",
            {
                "query": component_key,
                "expected_node_types": list(component.get("expectedNodeTypes") or []),
                "scope": str(component.get("scope") or "any"),
            },
        )
        resolved_key = str((result.get("resolvedSubject") or {}).get("stableKey") or "")
        if result.get("status") == "resolved" and resolved_key == component_key:
            confirmed[component_key] = result
    return confirmed


def _type_mismatch_candidates(
    *,
    graph_service: graph_tools.GraphQueryService,
    candidate_name: str,
) -> list[dict[str, Any]]:
    discovery = graph_service.run_tool(
        "search_graph_components",
        {"query": candidate_name, "scope": "any", "limit": 20},
    )
    candidates = list((discovery.get("facts") or {}).get("candidates") or [])
    named_component_types = {
        "active_skill",
        "support_gem",
        "skill_gem",
        "unique",
        "ascendancy",
        "passive",
        "notable",
        "keystone",
        "item_base",
    }
    candidates = [
        item for item in candidates if str(item.get("nodeType") or "") in named_component_types
    ]
    non_item_types_by_name = {
        str(item.get("displayName") or "").casefold()
        for item in candidates
        if str(item.get("nodeType") or "") != "item_base"
    }
    filtered = [
        item
        for item in candidates
        if str(item.get("nodeType") or "") != "item_base"
        or str(item.get("displayName") or "").casefold() not in non_item_types_by_name
    ]
    exact_name = candidate_name.strip().casefold()
    exact_matches = [
        item
        for item in filtered
        if str(item.get("displayName") or "").strip().casefold() == exact_name
    ]
    return exact_matches or filtered


def _mention_resolution_status(resolution: dict[str, Any]) -> str:
    if resolution.get("status") == "accepted":
        return "resolved"
    reason = str(resolution.get("reason") or "")
    if "ambiguous" in reason or resolution.get("resolverStatus") == "ambiguous":
        return "ambiguous"
    if reason in {"resolver_key_mismatch", "component_type_mismatch"}:
        return "type_mismatch"
    return "missing"


def _evidence_from_resolver(result: dict[str, Any], component_key: str) -> dict[str, Any]:
    return {
        "tool_name": "resolve_graph_component",
        "status": "resolved",
        "stable_key": component_key,
        "snapshot_id": str(result["snapshotId"]),
        "evidence_path_nodes": [component_key],
        "source_refs": list(result.get("sourceRefs") or []),
    }


def _evidence_from_reviewed_mapping(
    result: dict[str, Any],
    reviewed: dict[str, Any],
    current_candidate: dict[str, Any],
) -> dict[str, Any]:
    component_key = str(reviewed["acceptedStableKey"])
    return {
        "tool_name": "resolve_graph_component",
        "status": "resolved",
        "stable_key": component_key,
        "snapshot_id": str(result["snapshotId"]),
        "evidence_path_nodes": [component_key],
        "source_refs": list(current_candidate.get("sourceRefs") or []),
    }


def _resolver_candidate(result: dict[str, Any], component_key: str) -> dict[str, Any] | None:
    candidates = list((result.get("facts") or {}).get("candidates") or [])
    return next(
        (
            item
            for item in candidates
            if isinstance(item, dict) and str(item.get("stableKey") or "") == component_key
        ),
        None,
    )


def _matching_reviewed_mapping(
    *,
    sample_id: str,
    candidate_name: str,
    component_key: str,
    reviewed_mappings: dict[tuple[str, str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    return reviewed_mappings.get((sample_id, candidate_name.casefold(), component_key))


def _reviewed_mappings(
    *,
    primary_mapping_report: Path | None,
    secondary_mapping_report: Path | None,
    component_mapping_reports: list[Path],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    mappings: dict[tuple[str, str, str], dict[str, Any]] = {}
    paths = [primary_mapping_report, secondary_mapping_report, *component_mapping_reports]
    for path in paths:
        if path is None or not path.exists():
            continue
        payload = _load_safe_json(path, expected_safe=True)
        if str(payload.get("safeArtifactOnly")).casefold() != "true":
            continue
        for item in payload.get("reviewItems") or []:
            if not isinstance(item, dict) or item.get("reviewStatus") != "accepted":
                continue
            sample_id = str(item.get("sampleId") or "")
            candidate_name = str(item.get("candidateName") or "")
            accepted_key = str(item.get("acceptedStableKey") or "")
            if not sample_id or not candidate_name or not accepted_key:
                continue
            candidate = next(
                (
                    candidate
                    for candidate in item.get("candidates") or []
                    if isinstance(candidate, dict)
                    and str(candidate.get("stableKey") or "") == accepted_key
                ),
                None,
            )
            if candidate is None:
                continue
            mappings[(sample_id, candidate_name.casefold(), accepted_key)] = {
                "sampleId": sample_id,
                "candidateName": candidate_name,
                "acceptedStableKey": accepted_key,
                "sourceRefs": list(candidate.get("sourceRefs") or []),
                "reportId": str(payload.get("reportId") or ""),
                "snapshotId": str(payload.get("snapshotId") or ""),
            }
    return mappings


def _prepare_mechanic_audit(
    review: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Validate a case-level mechanic audit and remove only unsafe linked objects.

    The Researcher, not this deterministic gate, decides which semantic claims need a wiki
    check. This gate only validates revision-pinned provenance and enforces the Researcher's
    explicit keep/revise/defer decision without turning a single semantic mistake into a
    global name-based rule.
    """

    prepared = json.loads(json.dumps(review))
    provided = "mechanicAudit" in prepared
    audit_values = prepared.get("mechanicAudit", [])
    if not isinstance(audit_values, list):
        raise ValueError("deep review mechanicAudit must be a list")

    record_values = prepared.get("deepResearchRecords") or []
    candidate_values = prepared.get("candidateReviews") or []
    if not isinstance(record_values, list):
        raise ValueError("deep review deepResearchRecords must be a list")
    if not isinstance(candidate_values, list):
        raise ValueError("deep review candidateReviews must be a list")
    record_objects = [item for item in record_values if isinstance(item, dict)]
    candidate_objects = [item for item in candidate_values if isinstance(item, dict)]
    record_index: dict[str, list[dict[str, Any]]] = {}
    candidate_index: dict[str, list[dict[str, Any]]] = {}
    for item in record_objects:
        record_index.setdefault(str(item.get("title") or "").strip(), []).append(item)
    for item in candidate_objects:
        candidate_index.setdefault(str(item.get("title") or "").strip(), []).append(item)

    status_counts: dict[str, int] = {}
    decision_counts: dict[str, int] = {}
    audit_summaries: list[dict[str, Any]] = []
    deferred_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    filtered_record_titles: set[str] = set()
    filtered_candidate_titles: set[str] = set()
    audited_record_titles: set[str] = set()
    schema_issue_count = 0
    pinned_revision_count = 0
    compound_wiki_query_count = 0

    def issue(path: str, message: str) -> dict[str, str]:
        return {"path": path, "message": message}

    def target_titles(
        raw: dict[str, Any],
        *,
        field: str,
        index: int,
        issues: list[dict[str, str]],
    ) -> list[str]:
        values = raw.get(field, [])
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            issues.append(
                issue(f"mechanicAudit[{index}].{field}", "must be a list of non-empty titles")
            )
            return []
        return list(dict.fromkeys(value.strip() for value in values))

    for index, raw in enumerate(audit_values):
        issues: list[dict[str, str]] = []
        if not isinstance(raw, dict):
            issues.append(issue(f"mechanicAudit[{index}]", "must be an object"))
            raw = {}
        claim = str(raw.get("claim") or "").strip()
        claim_type = str(raw.get("claimType") or "").strip()
        wiki = raw.get("wiki", {})
        decision = str(raw.get("decision") or "").strip()
        if not claim:
            issues.append(issue(f"mechanicAudit[{index}].claim", "must be non-empty"))
        if claim_type not in MECHANIC_AUDIT_CLAIM_TYPES:
            issues.append(
                issue(
                    f"mechanicAudit[{index}].claimType",
                    f"must be one of {sorted(MECHANIC_AUDIT_CLAIM_TYPES)}",
                )
            )
        if not isinstance(wiki, dict):
            issues.append(issue(f"mechanicAudit[{index}].wiki", "must be an object"))
            wiki = {}
        wiki_status = str(wiki.get("status") or "").strip()
        if wiki_status not in MECHANIC_AUDIT_WIKI_STATUSES:
            issues.append(
                issue(
                    f"mechanicAudit[{index}].wiki.status",
                    f"must be one of {sorted(MECHANIC_AUDIT_WIKI_STATUSES)}",
                )
            )
        if decision not in MECHANIC_AUDIT_DECISIONS:
            issues.append(
                issue(
                    f"mechanicAudit[{index}].decision",
                    f"must be one of {sorted(MECHANIC_AUDIT_DECISIONS)}",
                )
            )
        if decision == "revise" and wiki_status in {"silent", "unavailable"}:
            issues.append(
                issue(
                    f"mechanicAudit[{index}].decision",
                    "revise requires wiki.status=supports or contradicts",
                )
            )

        affected_record_titles = target_titles(
            raw, field="affectedRecords", index=index, issues=issues
        )
        affected_candidate_titles = target_titles(
            raw, field="affectedCandidates", index=index, issues=issues
        )
        if not affected_record_titles and not affected_candidate_titles:
            issues.append(
                issue(
                    f"mechanicAudit[{index}]",
                    "must reference at least one affected record or candidate",
                )
            )

        matched_records: list[dict[str, Any]] = []
        matched_candidates: list[dict[str, Any]] = []
        for title in affected_record_titles:
            matches = record_index.get(title) or []
            if len(matches) != 1:
                issues.append(
                    issue(
                        f"mechanicAudit[{index}].affectedRecords",
                        f"title must match exactly one deepResearchRecord: {title}",
                    )
                )
            matched_records.extend(matches)
        for title in affected_candidate_titles:
            matches = candidate_index.get(title) or []
            if len(matches) != 1:
                issues.append(
                    issue(
                        f"mechanicAudit[{index}].affectedCandidates",
                        f"title must match exactly one candidateReview: {title}",
                    )
                )
            matched_candidates.extend(matches)

        corroboration = raw.get("corroboration", [])
        if not isinstance(corroboration, list) or any(
            str(value or "").strip() not in MECHANIC_AUDIT_CORROBORATION for value in corroboration
        ):
            issues.append(
                issue(
                    f"mechanicAudit[{index}].corroboration",
                    f"must use only {sorted(MECHANIC_AUDIT_CORROBORATION)}",
                )
            )
            corroboration = []
        corroboration = sorted({str(value).strip() for value in corroboration})

        page_title = str(wiki.get("pageTitle") or "").strip()
        source_ref = str(wiki.get("sourceRef") or "").strip()
        if " / " in page_title:
            compound_wiki_query_count += 1
        if wiki_status in {"supports", "contradicts"}:
            if not page_title:
                issues.append(issue(f"mechanicAudit[{index}].wiki.pageTitle", "must be non-empty"))
            if not POE2WIKI_REVISION_REF.fullmatch(source_ref):
                issues.append(
                    issue(
                        f"mechanicAudit[{index}].wiki.sourceRef",
                        "must be a revision-pinned poe2wiki:page:<id>:rev:<id> reference",
                    )
                )
            else:
                pinned_revision_count += 1
        elif source_ref and not POE2WIKI_REVISION_REF.fullmatch(source_ref):
            issues.append(
                issue(
                    f"mechanicAudit[{index}].wiki.sourceRef",
                    "when present, must be a revision-pinned poe2wiki reference",
                )
            )

        reason = ""
        if issues:
            reason = "invalid_schema"
            schema_issue_count += 1
        elif decision == "defer":
            reason = "mechanic_audit_deferred"
        elif wiki_status == "contradicts" and decision == "keep":
            reason = "mechanic_evidence_conflict"
        elif not corroboration:
            reason = "wiki_only_mechanic_claim"

        if source_ref and POE2WIKI_REVISION_REF.fullmatch(source_ref) and not issues:
            for target in [*matched_records, *matched_candidates]:
                refs = target.get("safeEvidenceRefs", [])
                if not isinstance(refs, list):
                    issues.append(
                        issue(
                            f"mechanicAudit[{index}]",
                            "linked object's safeEvidenceRefs must be a list",
                        )
                    )
                    reason = "invalid_schema"
                    schema_issue_count += 1
                    continue
                target["safeEvidenceRefs"] = sorted(
                    {
                        str(value).strip()
                        for value in [*refs, source_ref]
                        if str(value or "").strip()
                    }
                )

        # A record counts as audited only when the covering entry is itself
        # valid and accepted; invalid/deferred entries filter their records out
        # of the payload and must not inflate the audited set.
        if not reason:
            audited_record_titles.update(
                str(target.get("title") or "").strip() for target in matched_records
            )

        if reason:
            for kind, targets in (
                ("deep_research_record", matched_records),
                ("candidate_review", matched_candidates),
            ):
                for target in targets:
                    title = str(target.get("title") or "").strip()
                    if kind == "deep_research_record":
                        filtered_record_titles.add(title)
                    else:
                        filtered_candidate_titles.add(title)
                    component_keys = sorted(
                        {
                            str(component.get("componentKey") or "").strip()
                            for component in target.get("components") or []
                            if isinstance(component, dict)
                            and str(component.get("componentKey") or "").strip()
                        }
                    )
                    key = (kind, title, reason)
                    deferred_by_key[key] = {
                        "titleZh": title,
                        "sampleId": str(target.get("sampleId") or ""),
                        "reason": reason,
                        "componentKeys": component_keys,
                        "candidateKind": kind,
                        **({"validationIssues": issues} if issues else {}),
                    }
            if not matched_records and not matched_candidates:
                sample_id = str((prepared.get("artifactIdentity") or {}).get("sampleId") or "")
                deferred_by_key[("research_case", f"mechanicAudit[{index}]", reason)] = {
                    "titleZh": f"mechanicAudit[{index}]",
                    "sampleId": sample_id,
                    "reason": reason,
                    "componentKeys": [],
                    "candidateKind": "research_case",
                    **({"validationIssues": issues} if issues else {}),
                }

        status_counts[wiki_status or "invalid"] = status_counts.get(wiki_status or "invalid", 0) + 1
        decision_counts[decision or "invalid"] = decision_counts.get(decision or "invalid", 0) + 1
        audit_summaries.append(
            {
                "index": index,
                "claim": claim,
                "claimType": claim_type,
                "wikiStatus": wiki_status,
                "decision": decision,
                "sourceRef": source_ref or None,
                "corroboration": corroboration,
                "affectedRecordCount": len(matched_records),
                "affectedCandidateCount": len(matched_candidates),
                "outcome": reason or "accepted",
                "validationIssues": issues,
            }
        )

    prepared["deepResearchRecords"] = [
        item
        for item in record_values
        if not isinstance(item, dict)
        or str(item.get("title") or "").strip() not in filtered_record_titles
    ]
    prepared["candidateReviews"] = [
        item
        for item in candidate_values
        if not isinstance(item, dict)
        or str(item.get("title") or "").strip() not in filtered_candidate_titles
    ]
    accepted_record_payload = prepared.get("deepResearchRecords") or []
    high_risk_record_titles = sorted(
        {
            str(item.get("title") or "").strip()
            for item in accepted_record_payload
            if isinstance(item, dict)
            and str(item.get("recordKind") or "").strip() in MECHANIC_AUDIT_HIGH_RISK_RECORD_KINDS
            and str(item.get("title") or "").strip()
        }
    )
    unaudited_high_risk_record_titles = sorted(set(high_risk_record_titles) - audited_record_titles)
    live_evidence_status = (
        "not_requested"
        if not audit_values
        else "complete"
        if pinned_revision_count == len(audit_values)
        else "partial"
        if pinned_revision_count
        else "unavailable_or_unused"
    )
    advisories: list[str] = []
    if compound_wiki_query_count:
        advisories.append(
            "Mechanic audit used compound wiki page titles; query one exact page per lookup."
        )
    if unaudited_high_risk_record_titles:
        advisories.append(
            "Some mechanic_chain/resource_engine records were not referenced by mechanicAudit."
        )
    diagnostics = {
        "provided": provided,
        "entryCount": len(audit_values),
        "validEntryCount": len(audit_values) - schema_issue_count,
        "schemaIssueCount": schema_issue_count,
        "pinnedRevisionCount": pinned_revision_count,
        "liveEvidenceStatus": live_evidence_status,
        "liveEvidenceCoverage": (
            pinned_revision_count / len(audit_values) if audit_values else None
        ),
        "compoundWikiQueryCount": compound_wiki_query_count,
        "highRiskRecordCount": len(high_risk_record_titles),
        "auditedHighRiskRecordCount": len(set(high_risk_record_titles) & audited_record_titles),
        "unauditedHighRiskRecordCount": len(unaudited_high_risk_record_titles),
        "unauditedHighRiskRecordTitles": unaudited_high_risk_record_titles,
        "statusCounts": status_counts,
        "decisionCounts": decision_counts,
        "deferredObjectCount": len(deferred_by_key),
        "entries": audit_summaries,
        "advisories": advisories,
    }
    return prepared, diagnostics, list(deferred_by_key.values())


_STRUCTURAL_CANDIDATE_REQUIRED = (
    "sampleId",
    "caseRef",
    "patternType",
    "plannerHint",
    "verificationGate",
)
_STRUCTURAL_CANDIDATE_NONEMPTY_LISTS = ("axes", "verificationTasks")
_STRUCTURAL_RECORD_REQUIRED = (
    "sampleId",
    "researchGroupId",
    "caseRef",
    "recordKind",
    "title",
    "summary",
    "content",
)


def _structural_schema_issues(
    review: dict[str, Any],
) -> list[tuple[str, str, list[dict[str, Any]]]]:
    """Collect non-optional schema errors as fixable issues instead of raising.

    Mirrors the required-field and container-type rules of :func:`_candidate_reviews` /
    :func:`_deep_record_reviews` / :func:`_prepare_mechanic_audit` (and their
    ``_required`` / ``_string_list`` helpers) so ``--validate-only`` can return
    ``validationIssues`` instead of crashing with a ``runtime_failed`` exception.
    Candidate ``title``/``summary`` are intentionally excluded: they are soft fields
    that defer the candidate without losing accepted deep records.

    ``loc`` values point at the review JSON path (camelCase + index) so the Agent can
    locate the field inside the review file. Known boundaries kept as direct failures:
    deep field value types inside ``_optional_string_list`` / ``_component_payload``
    (e.g. ``expectedNodeTypes`` non-list) and unsupported PoB version enums in
    ``_durable_version_context`` (fail-closed by design, runs before this check).

    Returns ``[(sample_id, candidateKind, issues)]`` groups.
    """

    groups: list[tuple[str, str, list[dict[str, Any]]]] = []

    def _container_issue(path: list[object], msg: str) -> dict[str, Any]:
        return {"loc": path, "msg": msg, "type": "value_error"}

    mechanic_audit = review.get("mechanicAudit") or []
    if not isinstance(mechanic_audit, list):
        groups.append(
            (
                "",
                "research_case",
                [_container_issue(["mechanicAudit"], "deep review mechanicAudit must be a list")],
            )
        )

    candidates = review.get("candidateReviews") or []
    if not isinstance(candidates, list):
        groups.append(
            (
                "",
                "build_pattern",
                [
                    _container_issue(
                        ["candidateReviews"], "deep review candidateReviews must be a list"
                    )
                ],
            )
        )
        candidates = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            groups.append(
                (
                    "",
                    "build_pattern",
                    [
                        _container_issue(
                            ["candidateReviews", index],
                            "deep review candidate must be an object",
                        )
                    ],
                )
            )
            continue
        issues: list[dict[str, Any]] = []
        sample_id = str(candidate.get("sampleId") or "")
        for field in _STRUCTURAL_CANDIDATE_REQUIRED:
            if not str(candidate.get(field) or "").strip():
                issues.append(
                    {
                        "loc": ["candidateReviews", index, field],
                        "msg": f"deep review missing required field: {field}",
                        "type": "value_error",
                    }
                )
        for field in _STRUCTURAL_CANDIDATE_NONEMPTY_LISTS:
            values = candidate.get(field) or []
            if not isinstance(values, list) or not values:
                issues.append(
                    {
                        "loc": ["candidateReviews", index, field],
                        "msg": f"deep review field must be a non-empty list: {field}",
                        "type": "value_error",
                    }
                )
        components = candidate.get("components") or []
        if not isinstance(components, list):
            issues.append(
                _container_issue(
                    ["candidateReviews", index, "components"],
                    "deep review components must be a list",
                )
            )
        safe_evidence = candidate.get("safeEvidenceRefs") or []
        if not isinstance(safe_evidence, list):
            issues.append(
                _container_issue(
                    ["candidateReviews", index, "safeEvidenceRefs"],
                    "deep review safeEvidenceRefs must be a list",
                )
            )
        if issues:
            groups.append((sample_id, "build_pattern", issues))
    records = review.get("deepResearchRecords") or []
    if not isinstance(records, list):
        groups.append(
            (
                "",
                "deep_research_record",
                [
                    _container_issue(
                        ["deepResearchRecords"], "deep review deepResearchRecords must be a list"
                    )
                ],
            )
        )
        records = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            groups.append(
                (
                    "",
                    "deep_research_record",
                    [
                        _container_issue(
                            ["deepResearchRecords", index],
                            "deep research record must be an object",
                        )
                    ],
                )
            )
            continue
        issues = []
        sample_id = str(record.get("sampleId") or "")
        for field in _STRUCTURAL_RECORD_REQUIRED:
            if not str(record.get(field) or "").strip():
                issues.append(
                    {
                        "loc": ["deepResearchRecords", index, field],
                        "msg": f"deep review missing required field: {field}",
                        "type": "value_error",
                    }
                )
        typed_payload = record.get("typedPayload") or {}
        if not isinstance(typed_payload, dict):
            issues.append(
                _container_issue(
                    ["deepResearchRecords", index, "typedPayload"],
                    "deep research record typedPayload must be an object",
                )
            )
        safe_evidence = record.get("safeEvidenceRefs") or []
        if not isinstance(safe_evidence, list):
            issues.append(
                _container_issue(
                    ["deepResearchRecords", index, "safeEvidenceRefs"],
                    "deep research record safeEvidenceRefs must be a list",
                )
            )
        if issues:
            groups.append((sample_id, "deep_research_record", issues))
    return groups


def _structural_failure_report(
    groups: list[tuple[str, str, list[dict[str, Any]]]],
) -> dict[str, Any]:
    """Short-circuit report for structurally invalid reviews.

    Shape aligns with the normal deferred-candidate contract so ``--validate-only``
    surfaces ``validation_failed`` + fixable ``validationIssues`` and the real accept
    path lands on ``acceptance_rejected`` instead of a crash.
    """

    deferred: list[dict[str, Any]] = []
    for sample_id, kind, issues in groups:
        deferred.append(
            {
                "titleZh": "safe review 结构校验未通过",
                "sampleId": sample_id or "",
                "reason": "invalid_schema",
                "componentKeys": [],
                "caveats": [
                    f"{kind} 存在结构错误：按 validationIssues 修正后重新校验；"
                    "不要把 raw 材料填入 review"
                ],
                "validationIssues": issues,
            }
        )
    return {
        "status": "rejected",
        "deferredCandidates": deferred,
        "deferredReasonCounts": {"invalid_schema": len(deferred)},
        "deferredCandidateCount": len(deferred),
        "acceptedPatternCount": 0,
        "acceptedDeepRecordCount": 0,
    }


def _candidate_reviews(review: dict[str, Any]) -> list[dict[str, Any]]:
    if str(review.get("safeArtifactOnly")).casefold() != "true":
        raise ValueError("deep review artifact must be safeArtifactOnly=true")
    candidates = review.get("candidateReviews") or []
    if not isinstance(candidates, list):
        raise ValueError("deep review candidateReviews must be a list")
    normalized: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("deep review candidate must be an object")
        components = candidate.get("components") or []
        if not isinstance(components, list):
            raise ValueError("deep review components must be a list")
        normalized.append(
            {
                "sampleId": _required(candidate, "sampleId"),
                "caseRef": _required(candidate, "caseRef"),
                "safeEvidenceRefs": _safe_evidence_refs(candidate),
                "patternType": _normalize_pattern_type(_required(candidate, "patternType")),
                "title": str(candidate.get("title") or "").strip(),
                "summary": str(candidate.get("summary") or "").strip(),
                "axes": _normalize_axes(_string_list(candidate, "axes")),
                "components": [_component_payload(component) for component in components],
                "plannerHint": _required(candidate, "plannerHint"),
                "verificationGate": _required(candidate, "verificationGate"),
                "verificationTasks": _string_list(candidate, "verificationTasks"),
                "transferScope": str(candidate.get("transferScope") or "family").strip(),
                "availability": str(candidate.get("availability") or "standard").strip(),
                "sourceSpecificComponentNames": _optional_string_list(
                    candidate, "sourceSpecificComponentNames"
                ),
                "transferRationale": str(candidate.get("transferRationale") or "").strip(),
                "applicabilityRequirements": _optional_string_list(
                    candidate, "applicabilityRequirements"
                ),
                "exclusionConditions": _optional_string_list(candidate, "exclusionConditions"),
                "gamePatch": str(candidate.get("gamePatch") or "0.5.4"),
                "passiveTreeVersion": str(candidate.get("passiveTreeVersion") or "0_5"),
                "pobVersionOrCommit": str(candidate.get("pobVersionOrCommit") or "unknown"),
            }
        )
    return normalized


def _unstructured_candidate_source_mentions(
    *,
    candidate: dict[str, Any],
    source_skill_manifest: dict[str, Any] | None,
) -> list[str]:
    """Find exact source component names used only in a candidate's durable prose."""

    if not isinstance(source_skill_manifest, dict):
        return []
    source_names: dict[str, str] = {}
    for group in source_skill_manifest.get("activeSkillGroups") or []:
        if not isinstance(group, dict):
            continue
        for item in [*(group.get("activeSkills") or []), *(group.get("supports") or [])]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name:
                source_names.setdefault(name.casefold(), name)
    submitted_names = {
        str(component.get("candidateName") or "").strip().casefold()
        for component in candidate.get("components") or []
        if str(component.get("candidateName") or "").strip()
    }
    prose = " ".join(
        [
            str(candidate.get("title") or ""),
            str(candidate.get("summary") or ""),
            str(candidate.get("plannerHint") or ""),
            str(candidate.get("verificationGate") or ""),
            str(candidate.get("transferRationale") or ""),
            *[str(value) for value in candidate.get("applicabilityRequirements") or []],
            *[str(value) for value in candidate.get("exclusionConditions") or []],
            *[str(value) for value in candidate.get("verificationTasks") or []],
        ]
    ).casefold()
    missing: list[str] = []
    for normalized_name, display_name in source_names.items():
        if normalized_name in submitted_names:
            continue
        pattern = rf"(?<![\w]){re.escape(normalized_name)}(?![\w])"
        if re.search(pattern, prose, flags=re.UNICODE):
            missing.append(display_name)
    return sorted(missing, key=str.casefold)


def _deep_record_reviews(review: dict[str, Any]) -> list[dict[str, Any]]:
    if str(review.get("safeArtifactOnly")).casefold() != "true":
        raise ValueError("deep review artifact must be safeArtifactOnly=true")
    values = review.get("deepResearchRecords") or []
    if not isinstance(values, list):
        raise ValueError("deep review deepResearchRecords must be a list")
    normalized: list[dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict):
            raise ValueError("deep research record must be an object")
        components = item.get("components") or []
        if not isinstance(components, list):
            raise ValueError("deep research record components must be a list")
        typed_payload = item.get("typedPayload") or {}
        if not isinstance(typed_payload, dict):
            raise ValueError("deep research record typedPayload must be an object")
        normalized.append(
            {
                "sampleId": _required(item, "sampleId"),
                "researchGroupId": _required(item, "researchGroupId"),
                "caseRef": _required(item, "caseRef"),
                "safeEvidenceRefs": _safe_evidence_refs(item),
                "recordKind": _required(item, "recordKind"),
                "title": _required(item, "title"),
                "summary": _required(item, "summary"),
                "content": _required(item, "content"),
                "contentLanguage": str(item.get("contentLanguage") or "zh-CN"),
                "lengthExceptionReason": str(item.get("lengthExceptionReason") or "") or None,
                "components": [_component_payload(component) for component in components],
                "conditions": _optional_string_list(item, "conditions"),
                "failureConditions": _optional_string_list(item, "failureConditions"),
                "typedPayload": typed_payload,
                "classKey": str(item.get("classKey") or "") or None,
                "ascendancyKey": str(item.get("ascendancyKey") or "") or None,
                "extractionMethodVersion": str(
                    item.get("extractionMethodVersion") or "deep_research_mvp_v1"
                ),
                "gamePatch": str(item.get("gamePatch") or "unknown"),
                "passiveTreeVersion": str(item.get("passiveTreeVersion") or "unknown"),
                "pobVersionOrCommit": str(item.get("pobVersionOrCommit") or "unknown"),
            }
        )
    return normalized


def _source_skill_evidence_diagnostics(
    *,
    review: dict[str, Any],
    source_skill_manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    empty = {
        "available": False,
        "unstructuredSourceSkillMentionCount": 0,
        "unstructuredSourceSkillMentions": [],
        "unstructuredSourceSupportMentionCount": 0,
        "unstructuredSourceSupportMentions": [],
        "unrepresentedActiveSkillGroupCount": 0,
        "unrepresentedActiveSkillGroups": [],
        "supportCoverageBlockedByStructuredOmission": False,
        "unrepresentedSkillGroupsAreDiagnosticOnly": True,
        "structuredMentionClosureEnforced": True,
    }
    if not isinstance(source_skill_manifest, dict):
        return empty
    groups = [
        item
        for item in source_skill_manifest.get("activeSkillGroups") or []
        if isinstance(item, dict)
    ]
    if not groups:
        return {**empty, "available": True}

    records = _deep_record_reviews(review)
    core_skill_mention_names = _core_skill_mention_names(records)
    structured_skills: set[str] = set()
    structured_supports: set[str] = set()
    packaged_supports: set[str] = set()
    evidence_kinds = {"skill_package", "mechanic_chain", "rotation"}
    for record in records:
        is_evidence = record.get("recordKind") in evidence_kinds
        for package in (record.get("typedPayload") or {}).get("supportPackages") or []:
            for support_key in package.get("supportKeys") or []:
                tail = str(support_key).strip().rsplit("/", 1)[-1].casefold()
                if tail:
                    packaged_supports.add(tail)
        for component in record.get("components") or []:
            name = str(component.get("candidateName") or "").strip().casefold()
            if not name:
                continue
            component_key = str(component.get("componentKey") or "").strip()
            if component_key.startswith("support:") or (
                not component_key and component.get("role") == "support_modifier"
            ):
                structured_supports.add(name)
            elif component_key.startswith("skill:") or component.get("role") != "support_modifier":
                structured_skills.add(name)
    evidence_records = [record for record in records if record.get("recordKind") in evidence_kinds]
    record_text_parts: dict[str, list[str]] = {}
    for record in evidence_records:
        kind = str(record.get("recordKind") or "")
        record_text_parts.setdefault(kind, []).extend(
            [
                str(record.get("title") or ""),
                str(record.get("summary") or ""),
                str(record.get("content") or ""),
                *[str(value) for value in record.get("conditions") or []],
                *[str(value) for value in record.get("failureConditions") or []],
            ]
        )
    record_text = {kind: " ".join(parts).casefold() for kind, parts in record_text_parts.items()}

    active_mentions: list[dict[str, Any]] = []
    support_mentions: list[dict[str, Any]] = []
    unrepresented_groups: list[dict[str, Any]] = []
    seen_active_names: set[str] = set()
    seen_support_names: set[str] = set()
    support_blocked = False
    for group in groups:
        group_ref = str(group.get("groupRef") or "")
        active_names = [
            str(item.get("name") or "").strip()
            for item in group.get("activeSkills") or []
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        support_items = [
            item
            for item in group.get("supports") or []
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        support_names = [str(item.get("name") or "").strip() for item in support_items]
        support_gem_ids = [str(item.get("gemId") or "").strip() for item in support_items]
        represented = any(name.casefold() in structured_skills for name in active_names)
        if not represented:
            unrepresented_groups.append(
                {
                    "groupRef": group_ref,
                    "activeSkillNames": active_names,
                    "supportCount": len(support_names),
                }
            )
        for name in active_names:
            normalized = name.casefold()
            if normalized in structured_skills or normalized in seen_active_names:
                continue
            record_kinds = sorted(
                kind for kind, text in record_text.items() if normalized and normalized in text
            )
            if not record_kinds:
                continue
            seen_active_names.add(normalized)
            active_mentions.append(
                {
                    "name": name,
                    "groupRef": group_ref,
                    "recordKinds": record_kinds,
                    "supportCount": len(support_names),
                }
            )
        for name in support_names:
            normalized = name.casefold()
            if normalized in structured_supports or normalized in seen_support_names:
                continue
            record_kinds = sorted(
                kind for kind, text in record_text.items() if normalized and normalized in text
            )
            if not record_kinds:
                continue
            seen_support_names.add(normalized)
            support_mentions.append(
                {
                    "name": name,
                    "groupRef": group_ref,
                    "recordKinds": record_kinds,
                }
            )
        active_in_core = any(name.casefold() in core_skill_mention_names for name in active_names)
        if active_in_core and len(support_names) >= 2:
            unstructured_supports = [
                name
                for name, gem_id in zip(support_names, support_gem_ids)
                if name.casefold() not in structured_supports
                and gem_id.casefold() not in packaged_supports
            ]
            if len(unstructured_supports) >= 2:
                support_blocked = True

    return {
        "available": True,
        "unstructuredSourceSkillMentionCount": len(active_mentions),
        "unstructuredSourceSkillMentions": active_mentions,
        "unstructuredSourceSupportMentionCount": len(support_mentions),
        "unstructuredSourceSupportMentions": support_mentions,
        "unrepresentedActiveSkillGroupCount": len(unrepresented_groups),
        "unrepresentedActiveSkillGroups": unrepresented_groups[:12],
        "unrepresentedActiveSkillGroupsTruncated": len(unrepresented_groups) > 12,
        "supportCoverageBlockedByStructuredOmission": support_blocked,
        "unrepresentedSkillGroupsAreDiagnosticOnly": True,
        "structuredMentionClosureEnforced": True,
    }


def _evaluate_case_coverage(
    *,
    review: dict[str, Any],
    accepted_records: list[dict[str, Any]],
    graph_service: graph_tools.GraphQueryService | None = None,
    source_evidence_diagnostics: dict[str, Any] | None = None,
) -> tuple[dict[str, str], list[str]]:
    declared = review.get("caseCoverage")
    advisories: list[str] = []
    if declared is None:
        declared = {}
        advisories.append(
            "Legacy safe review omitted caseCoverage; coverage was inferred from accepted records."
        )
    if not isinstance(declared, dict):
        raise ValueError("deep review caseCoverage must be an object")
    unknown = sorted(set(declared) - CASE_COVERAGE_DIMENSIONS)
    if unknown:
        raise ValueError("deep review caseCoverage has unknown dimensions: " + ", ".join(unknown))
    record_kinds = {str(item.get("recordKind") or "") for item in accepted_records}
    source_evidence_diagnostics = source_evidence_diagnostics or {}
    inferred = {
        "supports": _support_packages_cover_core_skill_groups(accepted_records)
        and not source_evidence_diagnostics.get(
            "supportCoverageBlockedByStructuredOmission", False
        ),
        "rotation": "rotation" in record_kinds,
        "passiveAscendancy": _has_explicit_ascendancy_responsibility(
            accepted_records, graph_service=graph_service
        ),
        "gearRoles": _has_explicit_gear_responsibilities(accepted_records),
        "resourceDefense": bool(record_kinds & {"resource_engine", "defense_engine"}),
    }
    coverage: dict[str, str] = {}
    for dimension in sorted(CASE_COVERAGE_DIMENSIONS):
        status = str(declared.get(dimension) or "").strip()
        if status and status not in CASE_COVERAGE_STATUSES:
            raise ValueError(
                f"deep review caseCoverage.{dimension} must be one of "
                + ", ".join(sorted(CASE_COVERAGE_STATUSES))
            )
        if status == "not_applicable":
            coverage[dimension] = status
        elif inferred[dimension]:
            coverage[dimension] = "covered"
        else:
            coverage[dimension] = "evidence_missing"
            if status == "covered":
                advisories.append(
                    f"caseCoverage.{dimension} declared covered but no matching accepted record was found."
                )
    omitted_skills = [
        str(item.get("name") or "")
        for item in source_evidence_diagnostics.get("unstructuredSourceSkillMentions") or []
        if str(item.get("name") or "")
    ]
    if omitted_skills:
        advisories.append(
            "Source active skills named in skill/mechanic/rotation conclusions were omitted from "
            "structured components: "
            + _bounded_join_diagnostics(omitted_skills)
            + ". Review their role and support ownership; this diagnostic does not decide whether "
            "they are Family identity skills."
        )
    omitted_supports = [
        str(item.get("name") or "")
        for item in source_evidence_diagnostics.get("unstructuredSourceSupportMentions") or []
        if str(item.get("name") or "")
    ]
    if omitted_supports:
        advisories.append(
            "Source supports named in conclusions were omitted from structured support components: "
            + _bounded_join_diagnostics(omitted_supports)
            + ". Text-only mentions stay advisory; coverage blocking only applies when an evidence "
            "record (skill_package/mechanic_chain/rotation) already structured the active skill of a "
            "Family-core skill group while at least two of its supports remain completely "
            "unpackaged. Non-core skill groups are diagnostic-only."
        )
    unsupported_pairs = [
        (
            f"{item.get('skillName')} [{item.get('skillKey')}] + "
            f"{item.get('supportName')} [{item.get('supportKey')}]"
        )
        for item in source_evidence_diagnostics.get("unsupportedSourceSupportPairs") or []
        if item.get("skillName")
        and item.get("skillKey")
        and item.get("supportName")
        and item.get("supportKey")
    ]
    if unsupported_pairs:
        advisories.append(
            "Static support contracts rejected source single-active-skill socket pairs: "
            + _bounded_join_diagnostics(unsupported_pairs)
            + ". Acceptance defers only records that submit the same stable-key pair or state "
            "the exact source names together in one claim; identical display names can resolve "
            "to different active-skill keys."
        )
    return coverage, advisories


def _bounded_join_diagnostics(items: list[str], *, limit: int = 700) -> str:
    """Join diagnostic entries with a hard length bound so program-generated
    acceptance caveats can never trip the copy-safety long-prose gate."""
    if not items:
        return ""
    text = ", ".join(items)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip(", ") + f", ... +{len(items)} entries total"


def _core_skill_identity_keys(records: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Map each research group to its Family-core skill stable keys.

    Shared by the supports coverage check and the structured-omission closure so both
    checks reason about the same core skill set (primary/clear/boss/triggered payload
    components, automatic family skills, and explicit familyCoreSkillKeys).
    """
    records_by_group: dict[str, list[dict[str, Any]]] = {}
    for item in records:
        records_by_group.setdefault(str(item.get("researchGroupId") or ""), []).append(item)
    per_group: dict[str, set[str]] = {}
    for group_id, group_records in records_by_group.items():
        identity_records = [
            item
            for item in group_records
            if item.get("recordKind") in research_identity.FAMILY_IDENTITY_RECORD_KINDS
        ]
        normalized_identity_records = [
            {
                "record_kind": str(item.get("recordKind") or ""),
                "component_mentions": [
                    {
                        "component_key": str(component.get("componentKey") or ""),
                        "role": str(component.get("role") or ""),
                    }
                    for component in item.get("components") or []
                    if isinstance(component, dict)
                ],
                "typed_payload": item.get("typedPayload") or {},
            }
            for item in identity_records
        ]
        keys = {
            str(component.get("componentKey") or "")
            for item in identity_records
            for component in item.get("components") or []
            if str(component.get("role") or "")
            in {"primary_damage", "clear_skill", "boss_skill", "triggered_payload"}
            and str(component.get("componentKey") or "").startswith("skill:")
        }
        keys.update(research_identity.automatic_family_skill_keys(normalized_identity_records))
        keys.update(
            str(value)
            for item in identity_records
            for value in (item.get("typedPayload") or {}).get("familyCoreSkillKeys") or []
            if str(value).startswith("skill:")
        )
        per_group[group_id] = keys
    return per_group


def _core_skill_mention_names(records: list[dict[str, Any]]) -> set[str]:
    """casefolded candidate names of Family-core skill components across the review."""
    per_group_keys = _core_skill_identity_keys(records)
    name_by_key: dict[str, str] = {}
    for item in records:
        for component in item.get("components") or []:
            key = str(component.get("componentKey") or "")
            name = str(component.get("candidateName") or "").strip()
            if key and name:
                name_by_key.setdefault(key, name)
    names: set[str] = set()
    for keys in per_group_keys.values():
        for key in keys:
            name = name_by_key.get(key)
            if name:
                names.add(name.casefold())
    return names


def _support_packages_cover_core_skill_groups(
    accepted_records: list[dict[str, Any]],
) -> bool:
    per_group_keys = _core_skill_identity_keys(accepted_records)
    records_by_group: dict[str, list[dict[str, Any]]] = {}
    for item in accepted_records:
        records_by_group.setdefault(str(item.get("researchGroupId") or ""), []).append(item)
    if not records_by_group:
        return False
    for group_id, group_records in records_by_group.items():
        core_skill_keys = per_group_keys.get(group_id, set())
        package_supports: dict[str, set[str]] = {}
        exceptions: set[str] = set()
        for item in group_records:
            typed_payload = item.get("typedPayload") or {}
            for package in typed_payload.get("supportPackages") or []:
                if not isinstance(package, dict):
                    continue
                skill_key = str(package.get("skillKey") or "")
                package_supports.setdefault(skill_key, set()).update(
                    str(value) for value in package.get("supportKeys") or [] if str(value)
                )
            for exception in typed_payload.get("supportCoverageExceptions") or []:
                if not isinstance(exception, dict):
                    continue
                if exception.get("reason") in {"source_coverage_gap", "not_applicable"}:
                    exceptions.add(str(exception.get("skillKey") or ""))
        if not core_skill_keys or any(
            len(package_supports.get(skill_key, set())) < 2 and skill_key not in exceptions
            for skill_key in core_skill_keys
        ):
            return False
    return True


def _propagate_group_ascendancy_scope(deep_payload: dict[str, Any]) -> None:
    """Fill an unambiguous resolved ascendancy across one research group.

    Review records are authored independently, while the Family identity is inferred from the
    whole group. When exactly one ascendancy is present either as a direct field or as a resolved
    ``ascendancy_shell`` component, preserving it on every durable record keeps record-level
    filtering aligned with the Family without guessing through names or prose.
    """

    records_by_group: dict[str, list[dict[str, Any]]] = {}
    for record in deep_payload.get("deep_research_records") or []:
        records_by_group.setdefault(str(record.get("research_group_id") or ""), []).append(record)
    for records in records_by_group.values():
        ascendancy_keys = {
            str(record.get("ascendancy_key") or "").strip()
            for record in records
            if str(record.get("ascendancy_key") or "").strip()
        }
        ascendancy_keys.update(
            str(mention.get("component_key") or "").strip()
            for record in records
            for mention in record.get("component_mentions") or []
            if isinstance(mention, dict)
            and mention.get("role") == "ascendancy_shell"
            and str(mention.get("component_key") or "").startswith("ascendancy:")
        )
        if len(ascendancy_keys) != 1:
            continue
        ascendancy_key = next(iter(ascendancy_keys))
        for record in records:
            if not record.get("ascendancy_key"):
                record["ascendancy_key"] = ascendancy_key


def _has_explicit_ascendancy_responsibility(
    accepted_records: list[dict[str, Any]],
    *,
    graph_service: graph_tools.GraphQueryService | None,
) -> bool:
    belongs_to = {
        (edge.source_key, edge.target_key)
        for edge in (graph_service.snapshot.edges if graph_service is not None else ())
        if edge.edge_type == "belongs_to"
    }
    for item in accepted_records:
        if item.get("recordKind") not in {
            "passive_package",
            "class_or_ascendancy_principle",
        }:
            continue
        components = item.get("components") or []
        ascendancy_keys = {
            str(component.get("componentKey") or "")
            for component in components
            if component.get("role") == "ascendancy_shell"
        }
        if not ascendancy_keys:
            continue
        component_keys = {
            str(component.get("componentKey") or "")
            for component in components
            if component.get("role") in research_models.ASCENDANCY_RESPONSIBILITY_ROLES
        }
        responsibilities = (item.get("typedPayload") or {}).get("ascendancyResponsibilities")
        if not isinstance(responsibilities, list):
            continue
        if any(
            isinstance(responsibility, dict)
            and str(responsibility.get("componentKey") or "") in component_keys
            and str(responsibility.get("responsibility") or "").strip()
            and any(
                (str(responsibility.get("componentKey") or ""), ascendancy_key) in belongs_to
                for ascendancy_key in ascendancy_keys
            )
            for responsibility in responsibilities
        ):
            return True
    return False


def _has_explicit_gear_responsibilities(accepted_records: list[dict[str, Any]]) -> bool:
    identity_types = {
        "primary_skill_source",
        "identity_enabler",
        "scaling",
        "resource_or_spirit",
    }
    for item in accepted_records:
        if item.get("recordKind") != "gear_synergy":
            continue
        gear_keys = {
            str(component.get("componentKey") or "")
            for component in item.get("components") or []
            if component.get("role") in {"unique_enabler", "gear_base", "weapon_base"}
        }
        responsibilities = (item.get("typedPayload") or {}).get("gearResponsibilities")
        if not isinstance(responsibilities, list):
            continue
        if any(
            isinstance(responsibility, dict)
            and str(responsibility.get("componentKey") or "") in gear_keys
            and responsibility.get("responsibilityType") in identity_types
            and str(responsibility.get("responsibility") or "").strip()
            for responsibility in responsibilities
        ):
            return True
    return False


def _record_kind_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in records:
        kind = str(item.get("recordKind") or "")
        counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))


def _record_kind_advisories(records: list[dict[str, Any]]) -> list[str]:
    expected_shapes = {
        "rotation": "player_action_sequence",
        "mechanic_chain": "state_causal_chain",
    }
    advisories: list[str] = []
    for item in records:
        kind = str(item.get("recordKind") or "")
        expected = expected_shapes.get(kind)
        if not expected:
            continue
        actual = str((item.get("typedPayload") or {}).get("knowledgeShape") or "")
        if actual != expected:
            advisories.append(
                f"{item.get('title')}: {kind} should declare "
                f"typedPayload.knowledgeShape={expected}; actual={actual or 'missing'}."
            )
    return advisories


def _normalize_pattern_type(value: str) -> str:
    match = _canonical_enum_match(value, PATTERN_TYPE_VALUES)
    return match or value


def _normalize_axes(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        token = _enum_token(value)
        normalized_value = AXIS_ALIASES.get(
            token, _canonical_enum_match(value, DESIGN_AXIS_VALUES) or token
        )
        normalized.append(normalized_value)
    return normalized


def _canonical_enum_match(value: str, allowed_values: set[str]) -> str | None:
    compact_value = _compact_enum_token(value)
    matches = [
        allowed
        for allowed in sorted(allowed_values)
        if (compact_allowed := _compact_enum_token(allowed))
        and (compact_value == compact_allowed or compact_allowed in compact_value)
    ]
    return matches[0] if len(matches) == 1 else None


def _compact_enum_token(value: str) -> str:
    return "".join(char for char in str(value or "").casefold() if char.isalnum())


def _enum_token(value: str) -> str:
    text = str(value or "").strip()
    if "_" in text:
        return "_".join(part for part in text.casefold().split("_") if part)
    if "-" in text:
        return "_".join(part for part in text.casefold().split("-") if part)
    return "".join(char for char in text.casefold() if char.isalnum() or char == "_")


def _component_payload(component: Any) -> dict[str, Any]:
    if not isinstance(component, dict):
        raise ValueError("deep review component must be an object")
    role = _enum_token(_required(component, "role"))
    expected_node_types = component.get("expectedNodeTypes") or ROLE_NODE_TYPES.get(role, [])
    if not isinstance(expected_node_types, list):
        raise ValueError("deep review component expectedNodeTypes must be a list")
    return {
        "candidateName": _required(component, "candidateName"),
        "componentKey": str(component.get("componentKey") or "").strip(),
        "role": role,
        "resolverQuery": str(
            component.get("resolverQuery") or component.get("candidateName") or ""
        ),
        "expectedNodeTypes": [
            str(value).strip() for value in expected_node_types if str(value).strip()
        ],
        "scope": str(
            component.get("scope") or ("player" if role in PLAYER_COMPONENT_ROLES else "any")
        ),
    }


def _durable_version_context(value: dict[str, str] | None) -> dict[str, str]:
    current = _local_certified_version_context()
    context = dict(value or {})
    submitted_pob_raw = _known_version(context.get("pobVersionOrCommit"))
    submitted_pob_version = freshness_providers.resolve_pob_version_enum(submitted_pob_raw)
    if submitted_pob_raw and submitted_pob_version is None:
        raise ValueError("research submitted an unsupported PoB version enum: " + submitted_pob_raw)
    normalized = {
        "gamePatch": _known_version(context.get("gamePatch")) or current.get("gamePatch", ""),
        "passiveTreeVersion": _known_version(context.get("passiveTreeVersion"))
        or current.get("passiveTreeVersion", ""),
        "pobVersionOrCommit": submitted_pob_version or current.get("pobVersionOrCommit", ""),
        "status": _known_version(context.get("status")) or "provided_by_acceptance_caller",
    }
    missing = [
        key
        for key in ("gamePatch", "passiveTreeVersion", "pobVersionOrCommit")
        if not normalized[key]
    ]
    if missing:
        raise ValueError(
            "durable research acceptance requires known version context: " + ", ".join(missing)
        )
    return normalized


def _local_certified_version_context() -> dict[str, str]:
    compatibility = freshness_providers.current_local_compatibility()
    if compatibility is None:
        return {}
    return {
        "gamePatch": compatibility.game_patch,
        "passiveTreeVersion": compatibility.passive_tree,
        "pobVersionOrCommit": compatibility.pob_version,
        "status": "application_current_version",
    }


def _known_version(value: Any) -> str:
    normalized = str(value or "").strip()
    return "" if normalized.casefold() in {"", "unknown", "none", "null"} else normalized


def _reason_counts(deferred: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in deferred:
        reason = str(item.get("reason") or "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def _required(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"deep review missing required field: {key}")
    return value


def _string_list(payload: dict[str, Any], key: str) -> list[str]:
    values = payload.get(key) or []
    if not isinstance(values, list) or not values:
        raise ValueError(f"deep review field must be a non-empty list: {key}")
    return [str(item) for item in values]


def _optional_string_list(payload: dict[str, Any], key: str) -> list[str]:
    values = payload.get(key) or []
    if not isinstance(values, list):
        raise ValueError(f"deep review field must be a list: {key}")
    return [str(item) for item in values if str(item).strip()]


def _safe_evidence_refs(payload: dict[str, Any]) -> list[str]:
    plural = payload.get("safeEvidenceRefs") or []
    if not isinstance(plural, list):
        raise ValueError("deep review safeEvidenceRefs must be a list")
    refs = sorted(
        {
            str(value).strip()
            for value in [payload.get("safeEvidenceRef"), *plural]
            if str(value or "").strip()
        }
    )
    if not refs:
        raise ValueError("deep review missing required field: safeEvidenceRef or safeEvidenceRefs")
    return refs


def _load_safe_json(path: Path, *, expected_safe: bool) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"safe review file failed to parse as UTF-8 JSON: {path} "
            f"({type(exc).__name__}: {exc}); if the file carries a UTF-8 BOM, re-save it "
            "without BOM (utf-8-sig compatible)"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(f"safe artifact must be a JSON object: {path}")
    if expected_safe:
        _assert_safe(payload)
    return payload


def _graph_service() -> graph_tools.GraphQueryService:
    index_path = paths.user_data_dir() / "physical_graph" / "snapshot_index.sqlite"
    return graph_tools.service_from_snapshot_index(str(index_path))


def _write_safe_report(report: dict[str, Any], json_output: Path, md_output: Path) -> None:
    _assert_safe(report)
    json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_output.write_text(_markdown(report), encoding="utf-8")


def _assert_safe(report: dict[str, Any]) -> None:
    _assert_valid_unicode(report)
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    leaks = [marker for marker in RAW_MARKERS if marker in serialized]
    if leaks:
        raise ValueError(f"unsafe deep review acceptance report markers: {', '.join(leaks)}")
    if copy_safety.find_forbidden_paths(report):
        raise ValueError("unsafe deep review acceptance report contains forbidden raw fields")
    flags = _copyability_flags_for_safe_text(report)
    if flags:
        raise ValueError(f"unsafe deep review acceptance report failed copy-safety: {flags}")


def _assert_valid_unicode(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _assert_valid_unicode(child, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _assert_valid_unicode(child, path=f"{path}[{index}]")
        return
    if not isinstance(value, str):
        return
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError(f"invalid unicode surrogate in deep review artifact at {path}")
    mojibake_markers = ("鍚", "鏃", "鐢", "鑳", "璇", "锛", "绛", "嬪", "熸", "浣")
    if sum(value.count(marker) for marker in mojibake_markers) >= 3:
        raise ValueError(f"invalid unicode mojibake in deep review artifact at {path}")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"invalid unicode in deep review artifact at {path}") from exc


def _copyability_flags_for_safe_text(value: Any, *, key: str = "") -> list[str]:
    text_fields = {
        "title",
        "summary",
        "titleZh",
        "summaryZh",
        "content",
        "reason",
        "caveats",
        "plannerHint",
        "planner_hint",
        "verificationTasks",
        "verification_tasks",
        "verificationGate",
        "verification_gate",
        "transferRationale",
        "transfer_rationale",
        "applicabilityRequirements",
        "applicability_requirements",
        "exclusionConditions",
        "exclusion_conditions",
        "deferredCandidates",
    }
    flags: set[str] = set()
    if isinstance(value, dict):
        for child_key, child in value.items():
            flags.update(_copyability_flags_for_safe_text(child, key=str(child_key)))
    elif isinstance(value, list):
        for child in value:
            flags.update(_copyability_flags_for_safe_text(child, key=key))
    elif isinstance(value, str) and key in text_fields:
        flags.update(copy_safety.durable_knowledge_flags(value))
    return sorted(flags)


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 4.5 Deep Review Acceptance",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Accepted patterns: `{report.get('acceptedPatternCount')}`",
        f"- Transfer candidates: `{report.get('acceptedTransferCandidateCount')}`",
        f"- Promoted transfer patterns: `{report.get('promotedTransferPatternCount')}`",
        f"- Single-component observations: `{report.get('singleComponentObservationCount')}`",
        f"- Case-only observations: `{report.get('caseOnlyObservationCount')}`",
        f"- Accepted deep records: `{report.get('acceptedDeepRecordCount')}`",
        f"- Created canonical deep records: `{report.get('createdDeepRecordCount')}`",
        f"- Updated canonical deep records: `{report.get('updatedDeepRecordCount')}`",
        f"- Added source evidence: `{report.get('addedDeepRecordEvidenceCount')}`",
        f"- Created Build Families: `{report.get('createdBuildFamilyCount')}`",
        f"- Added Build Family evidence: `{report.get('addedBuildFamilyEvidenceCount')}`",
        f"- Unresolved deep-record mentions: `{report.get('unresolvedDeepRecordComponentCount')}`",
        f"- Unresolved unique components: `{report.get('unresolvedUniqueComponentCount')}`",
        f"- Deep records without knowledge identity: `{report.get('unkeyedDeepRecordCount')}`",
        f"- Mechanic audit entries: `{report.get('mechanicAuditEntryCount')}`",
        f"- Mechanic audit pinned revisions: `{report.get('mechanicAuditPinnedRevisionCount')}`",
        f"- Mechanic audit schema issues: `{report.get('mechanicAuditSchemaIssueCount')}`",
        f"- Mechanic audit live evidence: `{report.get('mechanicAuditLiveEvidenceStatus')}`",
        (
            "- Unaudited high-risk mechanic records: "
            f"`{report.get('mechanicAuditUnauditedHighRiskRecordCount')}`"
        ),
        f"- Deferred candidates: `{report.get('deferredCandidateCount')}`",
        "",
        "## Case Coverage",
        "",
    ]
    for dimension, status in (report.get("caseCoverage") or {}).items():
        lines.append(f"- {dimension}: `{status}`")
    lines.extend(["", "## Record Kinds", ""])
    for record_kind, count in (report.get("recordKindCounts") or {}).items():
        lines.append(f"- {record_kind}: `{count}`")
    lines.extend(["", "## Quality Advisories", ""])
    lines.extend(f"- {item}" for item in report.get("caseCoverageAdvisories", []))
    lines.extend(f"- {item}" for item in report.get("recordKindAdvisories", []))
    lines.extend(
        [
            "",
            "## Caveats",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report.get("caveats", []))
    lines.extend(["", "## Accepted Patterns", ""])
    for pattern in report.get("acceptedPatterns", []):
        lines.extend(
            [
                f"- {pattern.get('titleZh')}",
                f"  - confidence: `{pattern.get('confidenceTier')}`",
                f"  - transfer scope: `{pattern.get('transferScope')}`",
                f"  - sample: `{pattern.get('sampleId')}`",
                f"  - components: `{', '.join(pattern.get('componentKeys') or [])}`",
            ]
        )
    lines.extend(["", "## Single-Component Observations", ""])
    for observation in report.get("singleComponentObservations", []):
        lines.extend(
            [
                f"- {observation.get('titleZh')}",
                f"  - sample: `{observation.get('sampleId')}`",
                f"  - components: `{', '.join(observation.get('componentKeys') or [])}`",
            ]
        )
    lines.extend(["", "## Deep Records With Unresolved Components", ""])
    for item in report.get("deepRecordsWithUnresolvedComponents", []):
        lines.append(
            f"- {item.get('titleZh')} ({item.get('recordKind')}): "
            f"`{item.get('unresolvedComponentCount')}`"
        )
    lines.extend(["", "## Deep Records Without Knowledge Identity", ""])
    for item in report.get("deepRecordsWithoutKnowledgeIdentity", []):
        lines.append(f"- {item.get('titleZh')} ({item.get('recordKind')})")
    lines.extend(["", "## Deferred", ""])
    for item in report.get("deferredCandidates", []):
        lines.append(f"- {item.get('titleZh')}: `{item.get('reason')}`")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=str(DB_PATH))
    parser.add_argument("--json-output", default=str(JSON_OUTPUT))
    parser.add_argument("--md-output", default=str(MD_OUTPUT))
    parser.add_argument("--review-file", default=str(REVIEW_FILE))
    parser.add_argument("--primary-mapping-report", default=str(PRIMARY_MAPPING_REPORT))
    parser.add_argument("--secondary-mapping-report", default=str(SECONDARY_MAPPING_REPORT))
    parser.add_argument(
        "--component-mapping-report",
        action="append",
        default=[str(DEEP_COMPONENT_MAPPING_REPORT)]
        if DEEP_COMPONENT_MAPPING_REPORT.exists()
        else [],
    )
    args = parser.parse_args(argv)
    report = accept_deep_review_candidates(
        db_path=args.db_path,
        json_output=args.json_output,
        md_output=args.md_output,
        review_file=args.review_file,
        primary_mapping_report=args.primary_mapping_report,
        secondary_mapping_report=args.secondary_mapping_report,
        component_mapping_reports=list(args.component_mapping_report or []),
    )
    print(
        json.dumps(
            {"status": report["status"], "acceptedPatternCount": report["acceptedPatternCount"]},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
