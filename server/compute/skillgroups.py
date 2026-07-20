"""Typed, compare-and-swap mutations for PoB socket groups.

PoB persists socket groups as an ordered array without durable group identifiers.  We avoid
changing its XML format: callers select a group by its current index and an opaque fingerprint of
the group contents.  The engine lock keeps the read/check/mutation sequence atomic, while the Lua
bridge snapshots and rolls back any mutation that fails validation.
"""

from __future__ import annotations

from typing import Any

from .engine import PobEngine
from .skilltext import normalize_skill_text
from .state import build_state_hash, canonical_payload_hash


def list_skill_groups(engine: PobEngine) -> dict[str, Any]:
    with engine.transaction_lock():
        xml = engine.get_xml()
        raw = engine.call("list_skill_groups")
        return _decorate(raw, state_hash=build_state_hash(xml))


def replace_skill_group(
    engine: PobEngine,
    *,
    group_index: int,
    expected_fingerprint: str,
    skill: str,
    expected_state_hash: str | None = None,
) -> dict[str, Any]:
    return _mutate(
        engine,
        method="replace_skill_group",
        group_index=group_index,
        expected_fingerprint=expected_fingerprint,
        expected_state_hash=expected_state_hash,
        text=normalize_skill_text(skill, default_level=None),
    )


def remove_skill_group(
    engine: PobEngine,
    *,
    group_index: int,
    expected_fingerprint: str,
    replacement_main_group_index: int | None = None,
    expected_state_hash: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if replacement_main_group_index is not None:
        params["replacementMainGroupIndex"] = replacement_main_group_index
    return _mutate(
        engine,
        method="remove_skill_group",
        group_index=group_index,
        expected_fingerprint=expected_fingerprint,
        expected_state_hash=expected_state_hash,
        **params,
    )


def set_skill_group_state(
    engine: PobEngine,
    *,
    group_index: int,
    expected_fingerprint: str,
    enabled: bool | None = None,
    in_full_dps: bool | None = None,
    make_main: bool = False,
    active_skill_index: int | None = None,
    label: str | None = None,
    expected_state_hash: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"makeMain": make_main}
    if enabled is not None:
        params["enabled"] = enabled
    if in_full_dps is not None:
        params["includeInFullDPS"] = in_full_dps
    if active_skill_index is not None:
        params["activeSkillIndex"] = active_skill_index
    if label is not None:
        params["label"] = label
    return _mutate(
        engine,
        method="set_skill_group_state",
        group_index=group_index,
        expected_fingerprint=expected_fingerprint,
        expected_state_hash=expected_state_hash,
        **params,
    )


def _mutate(
    engine: PobEngine,
    *,
    method: str,
    group_index: int,
    expected_fingerprint: str,
    expected_state_hash: str | None,
    **params: Any,
) -> dict[str, Any]:
    if group_index < 1:
        return _error("invalid_group_index", "group_index must be at least 1")
    if not expected_fingerprint:
        return _error(
            "expected_fingerprint_required",
            "read list_skill_groups and pass the selected group's fingerprint",
        )

    with engine.transaction_lock():
        before_xml = engine.get_xml()
        before_hash = build_state_hash(before_xml)
        if expected_state_hash is not None and expected_state_hash != before_hash:
            return _conflict(expected_state_hash, before_hash)

        before = _decorate(engine.call("list_skill_groups"), state_hash=before_hash)
        group = _group_at(before, group_index)
        if group is None:
            return _error("skill_group_not_found", f"skill group {group_index} does not exist")
        if group["fingerprint"] != expected_fingerprint:
            return {
                **_error(
                    "skill_group_conflict",
                    "the selected group changed; read list_skill_groups and retry",
                ),
                "groupIndex": group_index,
                "expectedFingerprint": expected_fingerprint,
                "actualFingerprint": group["fingerprint"],
                "stateHash": before_hash,
            }

        try:
            raw_result = engine.call(method, index=group_index, **params)
        except Exception:
            # A low-level callback can fail after touching PoB state but before returning a typed
            # result. Best-effort restoration keeps the public mutation atomic whenever the engine
            # process is still healthy, then preserves the original exception for diagnostics.
            try:
                engine.load_build_xml(before_xml, name="skill-group-exception-rollback")
            except Exception:
                pass
            raise
        if not isinstance(raw_result, dict):
            engine.load_build_xml(before_xml, name="skill-group-rollback")
            return _error("invalid_skill_group_mutation_result", "PoB returned an invalid result")
        if raw_result.get("ok") is False:
            # Lua mutations are fail-closed, but verify/restore here so the public contract does not
            # depend on every future low-level error branch remembering its own rollback.
            if build_state_hash(engine.get_xml()) != before_hash:
                engine.load_build_xml(before_xml, name="skill-group-rollback")
            raw_result.setdefault("stateHash", before_hash)
            return raw_result

        after_xml = engine.get_xml()
        after_hash = build_state_hash(after_xml)
        after = _decorate(engine.call("list_skill_groups"), state_hash=after_hash)
        return {
            "ok": True,
            "operation": method,
            "beforeStateHash": before_hash,
            "afterStateHash": after_hash,
            "changed": before_hash != after_hash,
            "mainGroupIndex": after.get("mainGroupIndex"),
            "groups": after.get("groups", []),
        }


def _decorate(raw: Any, *, state_hash: str) -> dict[str, Any]:
    result = dict(raw) if isinstance(raw, dict) else {}
    groups = result.get("groups")
    if not isinstance(groups, list):
        groups = []
    decorated: list[dict[str, Any]] = []
    for value in groups:
        if not isinstance(value, dict):
            continue
        group = dict(value)
        fingerprint_payload = {key: value for key, value in group.items() if key != "index"}
        group["fingerprint"] = canonical_payload_hash(
            fingerprint_payload,
            prefix="skill-group",
        )
        decorated.append(group)
    result["ok"] = True
    result["stateHash"] = state_hash
    result["groups"] = decorated
    return result


def _group_at(payload: dict[str, Any], index: int) -> dict[str, Any] | None:
    for group in payload.get("groups", []):
        if isinstance(group, dict) and group.get("index") == index:
            return group
    return None


def _conflict(expected: str, actual: str) -> dict[str, Any]:
    return {
        **_error(
            "build_state_conflict",
            "the active build changed after it was read; refresh state and retry",
        ),
        "expectedStateHash": expected,
        "actualStateHash": actual,
    }


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "errorCode": code, "error": message}
