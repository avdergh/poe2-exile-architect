"""Coverage and provenance gates for Research-depth conversational explanations."""

from __future__ import annotations
from pydantic import ValidationError
from server.knowledge.copy_safety import copyability_flags, find_forbidden_paths
from .localization import unresolved_tokens
from .models import StudyLesson
from .guide import coverage_issues
from .models import CHAPTERS


def validate(payload: dict, meta: dict, components: dict) -> tuple[StudyLesson | None, list[dict]]:
    try:
        lesson = StudyLesson.model_validate(payload)
    except ValidationError as exc:
        return None, [
            {
                "code": "study_explanation_schema",
                "path": ".".join(map(str, x["loc"])),
                "reason": x["type"],
            }
            for x in exc.errors(include_input=False)
        ]
    issues = []

    def issue(code, **context):
        issues.append({"code": code, **context})

    def refs(values, expected, code):
        if set(values) - set(expected):
            issue(code, refs=sorted(set(values) - set(expected)))

    if lesson.sourceHash != meta["sourceHash"]:
        issue("study_explanation_source_mismatch")
    if not meta.get("outputLanguage"):
        issue("study_language_context_missing")
    elif lesson.language != meta["outputLanguage"]:
        issue("study_language_mismatch", expected=meta["outputLanguage"], actual=lesson.language)
    pending = [
        s for s in meta["sections"] if not meta.get("coverage", {}).get(s, {}).get("complete")
    ]
    if pending:
        issue("study_source_read_incomplete", sections=pending)
    flags = set(copyability_flags(payload)) - {
        "full_support_link_like",
        "full_gem_link_like",
        "ordered_passive_path",
        "slot_exact_gear_like",
        "long_guide_prose_like",
    }
    # This strict schema's skillGroups are explanatory reviews, not raw loadouts.
    forbidden_paths = set(find_forbidden_paths(payload)) - {
        "skillGroups",
        "guide.reader.kindLabels.gear",
    }
    if flags or forbidden_paths:
        issue("study_explanation_raw_material", flags=sorted(flags))
    if unresolved_tokens(payload, components):
        issue("study_unknown_name_token")
    evidence = meta.get("evidence", {})

    def evidence_refs(values, subjects=(), supported=False):
        refs(values, evidence, "study_evidence_not_from_run")
        records = [evidence[x] for x in values if x in evidence]
        if any(x.get("sourceHash") != meta["sourceHash"] for x in records):
            issue("study_evidence_source_mismatch")
        read_subjects = {
            s for x in records if x["kind"] == "source_read" for s in x.get("subjectRefs", [])
        }
        if set(subjects) - read_subjects:
            issue(
                "study_component_source_evidence_missing",
                refs=sorted(set(subjects) - read_subjects),
            )
        if supported and not any(
            x["kind"] == "agent_reviewed"
            and x.get("finding") == "supports"
            and set(subjects) <= set(x.get("subjectRefs", []))
            for x in records
        ):
            issue("study_causal_corroboration_missing")

    direct = {
        ref for ref, c in components.items() if c["kind"] in {"skill", "support", "gear", "jewel"}
    }
    explained = {x.componentRef for x in lesson.components}
    if direct != explained:
        issue(
            "study_component_coverage_incomplete",
            missing=sorted(direct - explained),
            extra=sorted(explained - direct),
        )
    for entry in lesson.components:
        refs([entry.componentRef, *entry.synergies], components, "study_component_unknown")
        evidence_refs(entry.evidenceRefs, [entry.componentRef], entry.status == "supported")
        source = components.get(entry.componentRef, {})
        if source.get("kind") in {"skill", "support"}:
            if entry.gemAnalysis is None:
                issue("study_gem_detail_required", ref=entry.componentRef)
            else:
                refs(entry.gemAnalysis.targetRefs, components, "study_gem_target_unknown")
                if source["kind"] == "support" and not entry.gemAnalysis.targetRefs:
                    issue("study_support_target_required", ref=entry.componentRef)
                if source["kind"] == "support" and any(
                    components.get(target, {}).get("groupRef") != source.get("groupRef")
                    or components.get(target, {}).get("kind") != "skill"
                    for target in entry.gemAnalysis.targetRefs
                ):
                    issue("study_support_target_not_in_group", ref=entry.componentRef)
        elif entry.gemAnalysis is not None:
            issue("study_gem_detail_not_applicable", ref=entry.componentRef)
    groups = {c["groupRef"] for c in components.values() if c.get("groupRef")}
    reviewed = {g.groupRef for g in lesson.skillGroups}
    if groups != reviewed:
        issue("study_skill_group_coverage_incomplete", missing=sorted(groups - reviewed))
    for group in lesson.skillGroups:
        members = [r for r, c in components.items() if c.get("groupRef") == group.groupRef]
        evidence_refs(group.evidenceRefs, members)
    passive_refs = {r for r, c in components.items() if c["kind"] in {"passive", "ascendancy"}}
    covered = set()
    key_notes = set()
    for cluster in lesson.passivePlan.clusters:
        refs(cluster.componentRefs, passive_refs, "study_passive_cluster_subject_invalid")
        refs(
            cluster.keyPointNotes, cluster.componentRefs, "study_passive_key_point_outside_cluster"
        )
        covered.update(cluster.componentRefs)
        key_notes.update(cluster.keyPointNotes)
        evidence_refs(cluster.evidenceRefs, cluster.componentRefs)
    if covered != passive_refs:
        issue("study_passive_coverage_incomplete", missing=sorted(passive_refs - covered))
    critical = {
        r
        for r, c in components.items()
        if r in passive_refs
        and (
            set(c.get("nodeTypes", [])) & {"notable", "keystone", "mastery"}
            or c["kind"] == "ascendancy"
            and c.get("stats")
        )
    }
    if critical - key_notes:
        issue("study_key_passive_explanation_missing", missing=sorted(critical - key_notes))
    for chapter in lesson.chapters:
        evidence_refs(chapter.evidenceRefs)
    for mechanism in lesson.mechanisms:
        refs(mechanism.componentRefs, components, "study_mechanism_component_unknown")
        evidence_refs(
            mechanism.evidenceRefs, mechanism.componentRefs, mechanism.status == "supported"
        )
    if not any(m.chapter == "offense" for m in lesson.mechanisms):
        issue("study_output_mechanism_required")
    if not any(m.chapter in {"rotation", "resources"} for m in lesson.mechanisms):
        issue("study_loop_mechanism_required")
    issues.extend(
        coverage_issues(
            lesson.guide,
            components=components,
            groups=groups,
            mechanisms=[m.id for m in lesson.mechanisms],
            topics=CHAPTERS,
        )
    )
    return lesson, issues
