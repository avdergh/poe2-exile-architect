"""Typed single-case workflow. Persists only isolated runtime and completion metadata."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import secrets

from server.knowledge import research_packet
from server.knowledge.copy_safety import copyability_flags
from . import analysis, intake, knowledge, localization, measurements, storage, validation, icons
from .models import Bilingual, StudyLesson
from .storage import StudyError
from .language import normalize_language


def start(
    *,
    user_language: str,
    output_language: str | None = None,
    source_file: str | None = None,
    source_url: str | None = None,
    source_patch: str = "unknown",
) -> dict:
    user_language = normalize_language(user_language)
    selected_language = (
        normalize_language(output_language) if output_language is not None else user_language
    )
    if source_patch != "unknown" and not re.fullmatch(r"\d+\.\d+\.\d+[a-z]*", source_patch):
        raise StudyError("study_source_patch_invalid")
    xml, source_type = intake.read_source(source_file, source_url)
    run_ref = "study-run:" + secrets.token_hex(16)
    meta = {
        "schemaVersion": storage.SCHEMA,
        "runRef": run_ref,
        "createdAt": storage.now(),
        "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        "sourceHash": storage.fingerprint(xml.encode("utf-8")),
        "sourceType": source_type,
        "sourcePatch": source_patch,
        "userLanguage": user_language,
        "outputLanguage": selected_language,
        "languageSelection": "explicit_user_override"
        if output_language is not None
        else "follow_user",
        "status": "reading",
        "evidence": {},
        "coverage": {},
    }
    observed = analysis.inventory(xml, meta)
    source_packet = analysis.packet(xml, meta)
    manifest = research_packet.inspect_packet(source_packet)
    # None of the caller's paths, source URL, original character identity or XML enters run.json.
    meta.update(
        {
            "sections": list(research_packet.RESEARCH_READ_ORDER),
            "build": observed["build"],
            "activeSets": observed["activeSets"],
            "treeVersion": observed["treeVersion"],
            "inventoryHash": storage.fingerprint(observed),
        }
    )
    directory = storage.directory(run_ref)
    directory.mkdir(parents=True, exist_ok=False)
    storage.atomic_bytes(directory / "quarantine" / "source.xml", xml.encode("utf-8"))
    storage.atomic_json(directory / "quarantine" / "inventory.json", observed)
    storage.atomic_json(directory / "run.json", meta)
    return {
        **_public(meta),
        "manifest": {key: manifest[key] for key in ("sections", "recommendedReadOrder")},
        "componentCount": len(observed["components"]),
    }


def _public(meta):
    return {
        key: meta.get(key)
        for key in (
            "runRef",
            "status",
            "sourceHash",
            "sourcePatch",
            "userLanguage",
            "outputLanguage",
            "languageSelection",
            "expiresAt",
            "build",
            "activeSets",
            "treeVersion",
            "coverage",
            "completion",
        )
    }


def _source(directory, meta):
    try:
        data = (directory / "quarantine" / "source.xml").read_bytes()
    except OSError as exc:
        raise StudyError("study_source_unavailable") from exc
    if storage.fingerprint(data) != meta["sourceHash"]:
        raise StudyError("study_source_hash_mismatch")
    return data.decode("utf-8")


def _inventory(directory, meta):
    _source(directory, meta)
    observed = storage.read_json(directory / "quarantine" / "inventory.json")
    if storage.fingerprint(observed) != meta["inventoryHash"]:
        raise StudyError("study_inventory_hash_mismatch")
    for ref, translated in meta.get("translations", {}).items():
        if (
            ref in observed["components"]
            and translated["en"] == observed["components"][ref]["name"]["en"]
        ):
            observed["components"][ref]["name"] = translated
    return observed


def review_terminology(
    run_ref: str,
    *,
    component_ref: str,
    chinese_name: str,
    source_url: str,
    bilingual_excerpt: str,
    review_basis: dict,
    same_entity_reviewed: bool,
    official_publisher_reviewed: bool,
) -> dict:
    if same_entity_reviewed is not True or official_publisher_reviewed is not True:
        raise StudyError("study_translation_semantic_review_required")
    basis = Bilingual.model_validate(review_basis).model_dump()
    with storage.locked(run_ref) as (directory, meta):
        if meta.get("completion"):
            raise StudyError("study_explanation_already_completed")
        observed = _inventory(directory, meta)
        component = observed["components"].get(component_ref)
        if not component:
            raise StudyError("study_translation_component_unknown")
        translated = localization.reviewed_translation(
            component["name"]["en"], chinese_name, source_url, bilingual_excerpt
        )
        ref = storage.record_evidence(
            meta,
            kind="terminology_review",
            payload={"name": translated, "reviewBasis": basis},
            subjects=[component_ref],
        )
        translated["translationEvidenceRef"] = ref
        meta.setdefault("translations", {})[component_ref] = translated
        storage.atomic_json(directory / "run.json", meta)
        return {
            "name": translated,
            "evidenceRef": ref,
            "authority": "agent_reviewed",
            "purpose": "educational_only",
            "knowledgeWritten": False,
        }


def inspect(run_ref: str) -> dict:
    with storage.locked(run_ref, allow_expired=True) as (_directory, meta):
        result = _public(meta)
        result["sourceExpired"] = datetime.fromisoformat(meta["expiresAt"]) <= datetime.now(
            timezone.utc
        )
        return result


def read(run_ref: str, section: str, cursor: int = 0, limit: int = 20) -> dict:
    with storage.locked(run_ref) as (directory, meta):
        xml = _source(directory, meta)
        source = analysis.packet(xml, meta)
        result = research_packet.read_packet_section(
            source, section=section, cursor=cursor, limit=limit
        )
        observed = _inventory(directory, meta)
        # Source reads are useful only within this exact source; complete section coverage is tracked separately.
        refs = _section_subjects(section, result.get("items", []), observed)
        ref = storage.record_evidence(meta, kind="source_read", payload=result, subjects=refs)
        progress = meta["coverage"].setdefault(section, {"nextCursor": 0, "complete": False})
        if cursor == progress["nextCursor"] and not progress["complete"]:
            progress.update(
                {"nextCursor": result.get("nextCursor"), "complete": result.get("complete") is True}
            )
        result["evidenceRef"] = ref
        if all(meta["coverage"].get(name, {}).get("complete") for name in meta["sections"]):
            meta["status"] = "analyzing"
        result["componentRefs"] = refs
        result["components"] = [observed["components"][key] for key in refs]
        storage.atomic_json(directory / "run.json", meta)
        return result


def _section_subjects(section, items, observed):
    refs = []
    for ref, component in observed["components"].items():
        location = observed["locators"][ref]
        for row in items:
            match = False
            if section == "skills" and location["kind"] == "gem":
                match = (
                    row.get("skillSetId") == location["skillSetId"]
                    and row.get("groupIndex") == location["groupIndex"]
                )
            elif section == "skill-groups" and location["kind"] == "gem":
                match = row.get("groupRef") == component.get("groupRef")
            elif section in {"gear", "jewels"} and location["kind"] == "item":
                match = (
                    row.get("itemId") == location["itemId"] and row.get("slot") == location["slot"]
                )
            elif section == "passives" and location["kind"] == "passive":
                match = (
                    row.get("nodeId") == location["nodeId"]
                    and row.get("specId") == location["specId"]
                )
            if match:
                refs.append(ref)
                break
    return refs


def search(run_ref: str, query: str, section: str | None = None) -> dict:
    with storage.locked(run_ref) as (directory, meta):
        return research_packet.search_packet(
            analysis.packet(_source(directory, meta), meta), query=query, section=section
        )


def contract(run_ref: str) -> dict:
    from .icon_catalog import load_catalog
    from .component_icons import extend_catalog

    with storage.locked(run_ref) as (directory, meta):
        observed = _inventory(directory, meta)
        source_gems = {
            c["identity"]
            for c in observed["components"].values()
            if c["kind"] in {"skill", "support"}
        }
        catalog = extend_catalog(load_catalog(), observed["components"])
        icon_options = [
            e
            for e in catalog.values()
            if e.get("kind") == "granted_skill" and e.get("grantingGemId") in source_gems
        ]
        return {
            "schema": StudyLesson.model_json_schema(),
            "sourceHash": meta["sourceHash"],
            "components": list(observed["components"].values()),
            "coverage": meta["coverage"],
            "delivery": "learning_document",
            "outputLanguage": meta["outputLanguage"],
            "languagePriority": "highest",
            "additionalSkillIcons": icon_options,
            "componentIconOptions": [
                e
                for e in catalog.values()
                if e.get("kind") not in {"active", "support", "granted_skill"}
            ],
            "rules": [
                "HIGHEST PRIORITY: the entire guide, title, navigation, tables, diagrams, notes and chat introduction must use outputLanguage locked from the user's request. English game names do not select English prose. Unverified official translations remain English names only; review actual prose language, not merely the language field.",
                "Author the complete H5 learning reader separately from analysis. Keep full explanations in continuous responsive sections, add exact equipment/passive/augment icons, and explain what unfamiliar names are. Concepts are definitions, not guessed gem icons. No passive-tree visualization.",
                "Use {{componentRef}} tokens for game names. Labels resolve through official terminology or English fallback.",
                "Read all source sections and review every enabled skill container. Search is not reading coverage.",
                "Explain each equipment item and gem using source facts, its actual role, causal interactions, conditions, tradeoffs and failure modes.",
                "For each gem explain level/quality, actual effect and support targets; for each group explain output mode, sequence and support logic.",
                "Group allocated passives into functional clusters; explain sought attributes, path costs and every notable/keystone/ascendancy effect.",
                "Separate hit, ailment, trigger, proxy and resource/recovery chains. Explain startup, sustain, payoff, gaps and no-add Boss behavior.",
                "Source reads establish presence, not causal effect. Supported claims also require corroboration.",
                "No boilerplate reassurance, adjective-based component summaries, invented author intent, numbers, translations or uptime.",
                "Structural validation is not a semantic quality score; the Agent must actually review the mechanism depth and source conditions.",
                "Translate material limitations into practical explanations beside the affected skill, resource or play pattern. Preserve uncertainty; do not paste verification receipts, generic audit disclaimers or a diagnostic checklist into learner prose.",
                "Guide units must preserve all component, skill-group, mechanism and topic coverage. Topic identifiers are internal; visible headings and ordering should help the reader learn. teachingReview is an Agent review, not an automatic quality score.",
                "Study evidence is educational only. Never call Research/Phase7 writers for this run.",
            ],
        }


def query_knowledge(run_ref: str, kind: str, payload: dict) -> dict:
    with storage.locked(run_ref) as (directory, meta):
        result = knowledge.query(kind, payload)
        if result.get("status") in {"unavailable", "error", "not_found", "rejected"}:
            return result
        ref = storage.record_evidence(
            meta, kind="knowledge", payload={"query": payload, "result": result}
        )
        storage.atomic_json(directory / "run.json", meta)
        return {"purpose": "educational_only", "evidenceRef": ref, "result": result}


def review_evidence(
    run_ref: str,
    *,
    subject_refs: list[str],
    source_ref: str,
    conclusion: dict,
    relevance: dict,
    finding: str,
) -> dict:
    if finding not in {"supports", "contradicts", "silent"}:
        raise StudyError("study_review_finding_invalid")
    payload = {
        "sourceRef": source_ref,
        "conclusion": Bilingual.model_validate(conclusion).model_dump(),
        "relevance": Bilingual.model_validate(relevance).model_dump(),
        "finding": finding,
    }
    if set(copyability_flags(payload)) - {"long_guide_prose_like"}:
        raise StudyError("study_review_raw_material")
    with storage.locked(run_ref) as (directory, meta):
        observed = _inventory(directory, meta)
        if not subject_refs or set(subject_refs) - set(observed["components"]):
            raise StudyError("study_review_component_unknown")
        ref = storage.record_evidence(
            meta, kind="agent_reviewed", payload=payload, subjects=subject_refs
        )
        meta["evidence"][ref]["finding"] = finding
        meta["evidence"][ref]["review"] = payload
        storage.atomic_json(directory / "run.json", meta)
        return {"evidenceRef": ref, "authority": "agent_reviewed", "purpose": "educational_only"}


def observe(
    run_ref: str, *, group_index: int, skill_name: str, component_ref: str | None = None
) -> dict:
    with storage.locked(run_ref) as (directory, meta):
        observed = _inventory(directory, meta)
        if component_ref is not None and component_ref not in observed["locators"]:
            raise StudyError("study_counterfactual_component_unknown")
        result = measurements.measure(
            _source(directory, meta),
            group_index=group_index,
            skill_name=skill_name,
            locator=observed["locators"].get(component_ref),
        )
        result.update(
            {
                "sourceHash": meta["sourceHash"],
                "sourcePatch": meta["sourcePatch"],
                "componentRef": component_ref,
            }
        )
        if result.get("status") == "selection_required":
            return result
        ref = storage.record_evidence(meta, kind="measurement", payload=result)
        meta.setdefault("measurements", {})[ref] = result
        storage.atomic_json(directory / "run.json", meta)
        return {**result, "measurementRef": ref}


def validate_lesson(run_ref: str, lesson: dict) -> dict:
    with storage.locked(run_ref) as (directory, meta):
        parsed, issues = validation.validate(
            lesson, meta, _inventory(directory, meta)["components"]
        )
        if issues:
            return {"status": "needs_revision", "issues": issues}
        return {
            "status": "valid",
            "lessonHash": storage.fingerprint(parsed.model_dump()),
            "purpose": "educational_only",
            "knowledgeWritten": False,
        }


def complete(run_ref: str, lesson: dict) -> dict:
    from . import delivery, render

    with storage.locked(run_ref) as (directory, meta):
        observed = _inventory(directory, meta)
        parsed, issues = validation.validate(lesson, meta, observed["components"])
        if issues:
            return {"status": "needs_revision", "issues": issues}
        try:
            published = delivery.publish(directory, parsed, observed["components"])
        except icons.IconCoverageError as exc:
            return {"status": "needs_icons", "issues": exc.issues, "knowledgeWritten": False}
        completion = {
            **published,
            "language": parsed.language,
            "delivery": "learning_document",
            "format": "h5",
            "componentCount": len(parsed.components),
            "skillGroupCount": len(parsed.skillGroups),
            "passiveClusterCount": len(parsed.passivePlan.clusters),
            "mechanismCount": len(parsed.mechanisms),
        }
        meta["completion"] = completion
        meta["status"] = "ready_for_delivery"
        storage.atomic_json(directory / "run.json", meta)
        return {
            "status": "ready_for_delivery",
            **completion,
            "chatIntroduction": render.resolve(
                parsed.guide.chatIntroduction, observed["components"], parsed.language
            ),
            "knowledgeWritten": False,
        }


def cleanup(run_ref: str, *, abandon: bool = False) -> dict:
    with storage.locked(run_ref, allow_expired=True) as (directory, meta):
        expired = datetime.fromisoformat(meta["expiresAt"]) <= datetime.now(timezone.utc)
        if not (meta.get("completion") or expired or abandon):
            raise StudyError("study_cleanup_requires_delivery_or_abandonment")
        for name in ("source.xml", "inventory.json"):
            (directory / "quarantine" / name).unlink(missing_ok=True)
        meta["status"] = "cleaned"
        meta["cleanedAt"] = storage.now()
        meta.pop("evidence", None)
        meta.pop("measurements", None)
        storage.atomic_json(directory / "run.json", meta)
        return {**_public(meta), "rawSourceRemoved": True, "knowledgeWritten": False}
