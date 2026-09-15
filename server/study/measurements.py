"""Non-Judge measurements in disposable PoB processes; never touch the Create engine."""

from __future__ import annotations

import math
from pathlib import Path

from server.compute.engine import PobEngine
from server.compute.pob_xml_input import XML_INPUT_SEMANTICS_VERSION, parse_pob_xml
from server.compute.state import build_state_hash
from server.judge import hard_legality
from server.knowledge.research_packet import active_set_identity, config_set_identity
from server.compute.pob_config import active_custom_modifier_hash
from server.knowledge.research_readback import STAT_KEYS
from .storage import StudyError, fingerprint

METRICS = list(
    dict.fromkeys(
        [
            "TotalDPS",
            "AverageDamage",
            "Speed",
            "Life",
            "LifeUnreserved",
            "LifeCost",
            "LifePerSecondCost",
            *STAT_KEYS,
        ]
    )
)


def _read(engine, group_index: int, skill_name: str) -> dict:
    selection = engine.select_judge_skill(
        offense_skill_group_index=group_index, expected_skill_name=skill_name
    )
    if selection.get("status") != "selected":
        raise StudyError("study_exact_output_unavailable")
    selected = selection["selectedSkill"]
    capability = engine.call(
        "inspect_support_evaluation_capability",
        index=selected["groupIndex"],
        activeIndex=selected["activeIndex"],
        objectiveKeys=["TotalDPS"],
    )
    result = engine.get_stats(METRICS).get("stats", {})
    numbers = {
        key: value
        for key, value in result.items()
        if type(value) in (int, float) and math.isfinite(value)
    }
    xml = engine.get_xml()
    observed_root = parse_pob_xml(xml)
    config_identity = config_set_identity(observed_root)
    audit = hard_legality.audit_active_build(
        engine, snapshot_xml=xml, source_context="study_reference"
    )
    build = engine.get_build()
    active_weapon_set = build.get("activeWeaponSet")
    runtime_groups = engine.call("list_skill_groups").get("groups", [])
    runtime_effect = next(
        (
            effect
            for group in runtime_groups
            if group.get("index") == selected["groupIndex"]
            for effect in group.get("activeSkills", [])
            if effect.get("index") == selected["activeIndex"]
        ),
        {},
    )
    return {
        "stateHash": build_state_hash(xml),
        "activeSets": active_set_identity(observed_root)["activeSets"],
        "customModifierHash": active_custom_modifier_hash(
            observed_root, config_identity["activeConfigSet"]
        ),
        "calculationContext": selection["calculationContext"],
        "activeWeaponSet": active_weapon_set,
        "resources": {
            key: build.get(key)
            for key in (
                "spiritAvailable",
                "spiritRequested",
                "spiritOverBy",
                "spiritUnreserved",
                "attributes",
                "attributeRequirements",
                "normalPassivePointsUsed",
                "weaponSet1PointsUsed",
                "weaponSet2PointsUsed",
                "weaponSetPointsAvailable",
            )
        },
        "selectedSkill": selected,
        "effectiveLevel": runtime_effect.get("effectiveLevel"),
        "stats": numbers,
        "capability": capability,
        "hardFailures": audit.get("hardFailures", []),
        "audit": audit,
    }


def measure(xml: str, *, group_index: int, skill_name: str, locator: dict | None = None) -> dict:
    original_root = parse_pob_xml(xml)
    original_sets = active_set_identity(original_root)["activeSets"]
    config_identity = config_set_identity(original_root)
    original_custom = active_custom_modifier_hash(original_root, config_identity["activeConfigSet"])
    try:
        with PobEngine(show_engine_logs=False) as engine:
            engine.load_build_xml(xml, name="study-source")
            try:
                before = _read(engine, group_index, skill_name)
            except StudyError as exc:
                if str(exc) != "study_exact_output_unavailable":
                    raise
                discovered = engine.call("debug_judge_skill_candidates")
                return {
                    "status": "selection_required",
                    "errorCode": str(exc),
                    "availableOutputs": [
                        {
                            k: candidate.get(k)
                            for k in (
                                "groupIndex",
                                "activeIndex",
                                "skillName",
                                "groupOrigin",
                                "sourceMetric",
                                "caveats",
                            )
                        }
                        for candidate in discovered.get("candidates", [])
                    ],
                    "sourceInputStateHash": build_state_hash(xml),
                    "attemptConsumed": False,
                }
            if (
                before["activeSets"] != original_sets
                or before["customModifierHash"] != original_custom
            ):
                raise StudyError("study_observed_active_sets_mismatch")
            identity = {**engine.ping(), "engineInfo": getattr(engine, "info", {})}
            # Capture the executing bridge and PoB version source, not a caller-supplied model label.
            for label, file in (
                ("bridgeHash", getattr(engine, "script", None)),
                (
                    "versionSourceHash",
                    Path(engine.src_dir) / "Version.lua" if hasattr(engine, "src_dir") else None,
                ),
            ):
                identity[label] = (
                    fingerprint(Path(file).read_bytes()) if file and Path(file).is_file() else None
                )
            result = {
                "schemaVersion": "study_measurement_v1",
                "purpose": "educational_only",
                "sourceInputStateHash": build_state_hash(xml),
                "runtime": identity,
                "xmlInputSemanticsVersion": XML_INPUT_SEMANTICS_VERSION,
                "before": before,
                "status": "observed",
                "attemptConsumed": False,
                "modelScope": "exact_selected_output_only",
                "sourcePatchCertified": False,
            }
            if locator is None:
                before.pop("audit", None)
                return result
            if locator["kind"] == "item":
                changed = engine.unequip_item(locator["slot"])
            elif locator["kind"] == "passive":
                changed = engine.dealloc_passive(int(locator["nodeId"]))
            else:
                raise StudyError("study_counterfactual_requires_item_or_passive")
            if isinstance(changed, dict) and changed.get("ok") is False:
                raise StudyError("study_counterfactual_mutation_rejected")
            try:
                after = _read(engine, group_index, skill_name)
            except StudyError as exc:
                before.pop("audit", None)
                return {**result, "status": "output_unavailable", "reason": str(exc)}
            if before["stateHash"] == after["stateHash"]:
                raise StudyError("study_counterfactual_not_applied")
            regression = hard_legality.compare_audits_for_regression(
                before["audit"], after["audit"]
            )
            comparable = (
                not before["hardFailures"]
                and not after["hardFailures"]
                and before["calculationContext"] == after["calculationContext"]
                and all(
                    before["selectedSkill"].get(key) == after["selectedSkill"].get(key)
                    for key in ("groupIndex", "activeIndex", "skillName", "skillId", "sourceMetric")
                )
                and before["activeSets"] == after["activeSets"]
                and type(before["activeWeaponSet"]) is int
                and before["activeWeaponSet"] in {1, 2}
                and before["activeWeaponSet"] == after["activeWeaponSet"]
                and bool(before["capability"].get("selectedEffectId"))
                and before["capability"].get("selectedEffectId")
                == after["capability"].get("selectedEffectId")
                and before["customModifierHash"] == after["customModifierHash"]
                and all(
                    x["capability"].get("ok") is True
                    and x["capability"].get("numericRanking") == "supported"
                    and x["capability"].get("capabilitySource") == "pob_runtime"
                    for x in (before, after)
                )
                and "TotalDPS" in before["stats"]
                and "TotalDPS" in after["stats"]
            )
            result.update(
                {
                    "after": after,
                    "legalityChange": regression,
                    "status": "comparable" if comparable else "inconclusive",
                }
            )
            if comparable:
                result["delta"] = {
                    key: after["stats"][key] - value
                    for key, value in before["stats"].items()
                    if key in after["stats"]
                }
            before.pop("audit", None)
            after.pop("audit", None)
            result["measurementHash"] = fingerprint(result)
            return result
    except StudyError:
        raise
    except Exception as exc:
        raise StudyError("study_measurement_failed") from exc
