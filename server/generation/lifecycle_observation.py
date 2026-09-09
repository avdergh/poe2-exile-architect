"""Snapshot-backed lifecycle mechanism evidence shared by checks and formal verification.

Only typed external declarations are retained in the engine session. Every use re-observes the
current snapshot; cached caller booleans and lifecycle pass results never authorize a mechanism.
"""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from typing import Any
import xml.etree.ElementTree as ET

from server.compute import completeness
from server.compute.pob_xml_input import parse_pob_xml
from server.compute.state import build_state_hash
from server.knowledge.lifecycle_verification import LifecycleStageVerificationState

from . import preflight


OBSERVATION_VERSION = "lifecycle_mechanism_observation_v1"
_SESSION_ATTRIBUTE = "_poe2_lifecycle_observation_states"
_SESSION_LIMIT = 48
_DERIVED_STATE_FIELDS = frozenset({
    "mainSkillSocketed", "main_skill_socketed",
    "mainSkillSocketEvidence", "main_skill_socket_evidence",
    "ascendancyOrKeySupport", "ascendancy_or_key_support",
    "singleTargetDuty", "single_target_duty",
    "buildDefiningComponent", "build_defining_component",
    "mechanismObservation", "mechanism_observation",
})


def normalize_target(value: Any) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    return {
        "groupIndex": int(payload.get("groupIndex") or 0),
        "activeIndex": int(payload.get("activeIndex") or 0),
        "skillName": str(payload.get("skillName") or "").strip(),
    }


def declaration_payload(
    state: LifecycleStageVerificationState | dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate declarations and discard legacy dictionary copies of server-owned observations."""
    if isinstance(state, LifecycleStageVerificationState):
        parsed = state
    else:
        payload = state or {}
        if isinstance(payload, dict):
            # Direct Python callers historically supplied these fields. Ignore only the known
            # derived observations, then retain the typed contract for every other input field.
            payload = {key: value for key, value in payload.items() if key not in _DERIVED_STATE_FIELDS}
        parsed = LifecycleStageVerificationState.model_validate(payload)
    return parsed.model_dump(
        mode="json", by_alias=True, exclude_none=True, exclude={"mana_flask_equipped"}
    )


def observe_state(
    xml: str,
    *,
    build: dict[str, Any],
    observation_target: dict[str, Any] | None,
    state: LifecycleStageVerificationState | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Observe declared duties/components against one snapshot and its selected offense group.

    The caller owns the engine transaction and validates its exact skill selection. This helper
    does not infer a build-defining component from a main skill, an item name or a level band.
    """
    effective = declaration_payload(state)
    target = normalize_target(observation_target)
    group_index = target["groupIndex"] or None
    main_evidence = preflight.inspect_main_skill_socketed(
        xml, offense_skill_group_index=group_index
    )
    effective["mainSkillSocketed"] = bool(main_evidence.get("socketed"))
    effective["mainSkillSocketEvidence"] = main_evidence
    skill_evidence = preflight.inspect_lifecycle_skill_evidence(
        xml,
        single_target_skill_name=effective.get("singleTargetSkillName"),
        offense_skill_group_index=group_index,
    )
    effective["ascendancyOrKeySupport"] = skill_evidence.get("ascendancyOrKeySupport")
    single_target = dict(skill_evidence.get("singleTargetDuty") or {})
    single_target["evidenceRefs"] = list(effective.get("singleTargetEvidenceRefs") or [])
    single_target["verified"] = bool(
        single_target.get("verified") and single_target["evidenceRefs"]
    )
    effective["singleTargetDuty"] = single_target
    component = preflight.inspect_lifecycle_component_evidence(
        xml,
        component_kind=effective.get("buildDefiningComponentKind"),
        component_name=effective.get("buildDefiningComponentName"),
    )
    component["componentKey"] = effective.get("buildDefiningComponentKey")
    component["evidenceRefs"] = list(effective.get("buildDefiningEvidenceRefs") or [])
    component["verified"] = bool(
        component.get("verified") and component["componentKey"] and component["evidenceRefs"]
    )
    if not effective.get("buildDefiningComponentKind"):
        component["verified"] = None
    effective["buildDefiningComponent"] = component
    # The evaluated level overrides stale caller hints, including engines whose get_build omits it.
    try:
        build_node = parse_pob_xml(xml).find("Build")
        actual_level = int(build_node.get("level") or 0) if build_node is not None else 0
    except (ET.ParseError, TypeError, ValueError):
        actual_level = 0
    if not 1 <= actual_level <= 100:
        actual_level = int(build.get("level") or 0)
    if 1 <= actual_level <= 100:
        effective["level"] = actual_level
    gear = completeness.equipped_item_metadata(
        xml, allocated_jewel_socket_ids=build.get("allocatedPassiveJewelSocketIds")
    )
    if not gear:
        gear = build.get("gear") if isinstance(build.get("gear"), dict) else {}
    effective["manaFlaskEquipped"] = any(
        str(slot).casefold().startswith("flask")
        and isinstance(item, dict)
        and "mana flask" in f"{item.get('name') or ''} {item.get('base') or ''}".casefold()
        for slot, item in gear.items()
    )
    effective["mechanismObservation"] = {
        "observationVersion": OBSERVATION_VERSION,
        "stateHash": build_state_hash(xml),
        "observationTarget": target,
        "evidenceSource": "typed_declaration_and_evaluated_snapshot",
    }
    return effective


def remember_state(
    engine: Any,
    *,
    state_hash: str,
    observation_target: dict[str, Any],
    state: LifecycleStageVerificationState | dict[str, Any] | None,
) -> bool:
    """Retain safe declarations only after the caller's exact-state observation guard passed."""
    key = _state_key(state_hash, observation_target)
    if key is None:
        return False
    payload = declaration_payload(state)
    session = getattr(engine, _SESSION_ATTRIBUTE, None)
    if not isinstance(session, OrderedDict):
        session = OrderedDict()
        setattr(engine, _SESSION_ATTRIBUTE, session)
    session[key] = deepcopy(payload)
    session.move_to_end(key)
    while len(session) > _SESSION_LIMIT:
        session.popitem(last=False)
    return True


def state_for_target(
    engine: Any,
    *,
    state_hash: str,
    observation_target: dict[str, Any],
) -> dict[str, Any] | None:
    """Return only declarations bound to this engine, semantic snapshot and exact output."""
    key = _state_key(state_hash, observation_target)
    session = getattr(engine, _SESSION_ATTRIBUTE, None)
    if key is None or not isinstance(session, OrderedDict) or key not in session:
        return None
    session.move_to_end(key)
    return deepcopy(session[key])


def _state_key(
    state_hash: str,
    observation_target: dict[str, Any],
) -> tuple[str, int, int, str] | None:
    target = normalize_target(observation_target)
    if (
        not state_hash
        or target["groupIndex"] < 1
        or target["activeIndex"] < 1
        or not target["skillName"]
    ):
        return None
    return (
        state_hash,
        target["groupIndex"],
        target["activeIndex"],
        target["skillName"].casefold(),
    )
