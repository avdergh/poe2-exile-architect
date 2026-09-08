"""Typed, compare-and-swap mutations for PoB socket groups.

PoB persists socket groups as an ordered array without durable group identifiers.  We avoid
changing its XML format: callers select a group by its current index and an opaque fingerprint of
the group contents.  The engine lock keeps the read/check/mutation sequence atomic, while the Lua
bridge snapshots and rolls back any mutation that fails validation.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from ..knowledge import db
from ..knowledge.skill_equivalence import SkillEquivalenceIndex
from .engine import PobEngine
from .skilltext import normalize_skill_text, requested_gem_names
from .state import build_state_hash, canonical_payload_hash


def set_main_skill(engine: PobEngine, skill: str) -> dict[str, Any]:
    """Set one main group and fail atomically if PoB drops any requested gem."""

    if not callable(getattr(engine, "call", None)):
        return engine.paste_skill(skill)
    return _apply_complete_group(engine, operation="set_main_skill", skill=skill)


def add_skill_group(
    engine: PobEngine,
    skill: str,
    *,
    include_in_full_dps: bool = False,
) -> dict[str, Any]:
    """Add one group and fail atomically if PoB drops any requested gem."""

    if not callable(getattr(engine, "call", None)):
        return engine.add_skill_group(skill, include_in_full_dps=include_in_full_dps)
    return _apply_complete_group(
        engine,
        operation="add_skill_group",
        skill=skill,
        include_in_full_dps=include_in_full_dps,
    )


def list_skill_groups(engine: PobEngine) -> dict[str, Any]:
    with engine.transaction_lock():
        xml = engine.get_xml()
        raw = engine.call("list_skill_groups")
        return _decorate(raw, state_hash=build_state_hash(xml))


def _apply_complete_group(
    engine: PobEngine,
    *,
    operation: str,
    skill: str,
    include_in_full_dps: bool = False,
) -> dict[str, Any]:
    requested, unresolved, normalized = _canonical_skill_request(engine, skill)
    if unresolved:
        return {
            **_error("unknown_skill_gem", "one or more requested gems are unknown"),
            "unresolvedGemNames": unresolved,
        }
    if not requested:
        return _error("skill_text_required", "skill text must contain at least one gem")

    with engine.transaction_lock():
        before_xml = engine.get_xml()
        before_hash = build_state_hash(before_xml)
        before = _decorate(engine.call("list_skill_groups"), state_hash=before_hash)
        if operation == "set_main_skill":
            result = engine.paste_skill(normalized)
        else:
            result = engine.add_skill_group(
                normalized,
                include_in_full_dps=include_in_full_dps,
            )
        if not isinstance(result, dict) or result.get("ok") is False:
            if build_state_hash(engine.get_xml()) != before_hash:
                engine.load_build_xml(before_xml, name="skill-group-failure-rollback")
            if isinstance(result, dict):
                result.setdefault("stateHash", before_hash)
                return result
            return {
                **_error(
                    "invalid_skill_group_mutation_result",
                    "PoB returned an invalid result",
                ),
                "stateHash": before_hash,
            }

        after = _decorate(
            engine.call("list_skill_groups"),
            state_hash=build_state_hash(engine.get_xml()),
        )
        if operation == "set_main_skill":
            target_index = after.get("mainGroupIndex")
        else:
            previous_indices = {
                group.get("index") for group in before.get("groups", []) if isinstance(group, dict)
            }
            new_groups = [
                group
                for group in after.get("groups", [])
                if isinstance(group, dict) and group.get("index") not in previous_indices
            ]
            target_index = new_groups[-1].get("index") if new_groups else None
        target = _group_at(after, int(target_index or 0))
        actual = _canonical_actual_gems(target)
        if Counter(actual) != Counter(requested):
            engine.load_build_xml(before_xml, name="skill-group-completeness-rollback")
            return {
                **_error(
                    "skill_group_incomplete",
                    "PoB did not persist every requested gem; build restored",
                ),
                "requestedGems": requested,
                "appliedGems": actual,
                "droppedGemNames": list((Counter(requested) - Counter(actual)).elements()),
                "stateHash": before_hash,
            }
        return result


def replace_skill_group(
    engine: PobEngine,
    *,
    group_index: int,
    expected_fingerprint: str,
    skill: str,
    expected_state_hash: str | None = None,
) -> dict[str, Any]:
    requested, unresolved, normalized = _canonical_skill_request(engine, skill)
    if unresolved:
        return {
            **_error("unknown_skill_gem", "one or more requested gems are unknown"),
            "unresolvedGemNames": unresolved,
        }
    return _mutate(
        engine,
        method="replace_skill_group",
        group_index=group_index,
        expected_fingerprint=expected_fingerprint,
        expected_state_hash=expected_state_hash,
        expected_gems=requested,
        text=normalized,
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


def configure_source_skill_supports(
    engine: PobEngine,
    *,
    source_group_index: int,
    supports: list[str],
    expected_fingerprint: str,
    expected_state_hash: str | None = None,
) -> dict[str, Any]:
    """Atomically replace supports on one real Tree or Item source group."""

    if source_group_index < 1:
        return _error("invalid_group_index", "source_group_index must be at least 1")
    if not expected_fingerprint:
        return _error(
            "expected_fingerprint_required",
            "read list_skill_groups and pass the selected group's fingerprint",
        )
    if len(supports) > 5:
        return _error("source_support_capacity_exceeded", "a source skill can have at most 5 supports")

    resolved: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    equivalence = SkillEquivalenceIndex.shared()
    for requested in supports:
        name = str(requested or "").strip()
        matching_ids = equivalence.gem_ids(name) if name else ()
        if len(matching_ids) > 1:
            return {
                **_error("ambiguous_support_gem", "a support name resolves to multiple gems"),
                "support": name,
                "candidateGemIds": list(matching_ids),
            }
        gem = db.get_gem(matching_ids[0]) if len(matching_ids) == 1 else db.get_gem(name)
        if gem is None and name:
            gem = _corpus_support_for_runtime_name(engine, name)
        if gem is None:
            return {
                **_error("unknown_support_gem", "one or more requested supports are unknown"),
                "support": name,
            }
        if str(gem.get("gem_type") or "").lower() != "support":
            return {
                **_error("active_skill_not_support", "source supports must all be support gems"),
                "support": str(gem.get("name") or name),
            }
        gem_id = str(gem["id"])
        if gem_id in seen_ids:
            return {
                **_error("duplicate_support", "the same support cannot be requested twice"),
                "support": str(gem["name"]),
            }
        seen_ids.add(gem_id)
        resolved.append(gem)

    with engine.transaction_lock():
        before_xml = engine.get_xml()
        before_hash = build_state_hash(before_xml)
        if expected_state_hash is not None and expected_state_hash != before_hash:
            return _conflict(expected_state_hash, before_hash)
        before = _decorate(engine.call("list_skill_groups"), state_hash=before_hash)
        group = _group_at(before, source_group_index)
        if group is None:
            return _error("skill_group_not_found", "source skill group does not exist")
        if group["fingerprint"] != expected_fingerprint:
            return {
                **_error("skill_group_conflict", "the selected source group changed; refresh and retry"),
                "groupIndex": source_group_index,
                "expectedFingerprint": expected_fingerprint,
                "actualFingerprint": group["fingerprint"],
                "stateHash": before_hash,
            }
        source = str(group.get("source") or "").strip()
        source_kind = str(group.get("sourceKind") or "").strip().casefold()
        real_source = (source.startswith("Tree:") and source_kind == "tree") or (
            source.startswith("Item:") and source_kind == "item"
        )
        if not real_source:
            return {
                **_error(
                    "source_skill_supports_not_modelable",
                    "the selected group is not backed by a current passive, Ascendancy, or item source",
                ),
                "modelabilityBlocker": bool(source),
                "source": source or None,
                "stateHash": before_hash,
            }
        if group.get("noSupports"):
            return {
                **_error("source_skill_no_supports", "source skill does not accept supports"),
                "source": source or None,
                "stateHash": before_hash,
            }
        runtime_supports: list[dict[str, Any]] = []
        for gem in resolved:
            identity = engine.call(
                "resolve_support_gem_identity",
                gemIds=[str(gem["id"])],
                effectIds=list(gem.get("grants") or []),
            )
            if (not isinstance(identity, dict) or identity.get("ok") is not True
                    or identity.get("status") != "resolved" or not identity.get("gemId")
                    or not identity.get("name")):
                return {
                    **_error("support_identity_unresolved", "the current PoB cannot uniquely resolve this support"),
                    "support": str(gem["name"]),
                    "identityStatus": identity.get("status") if isinstance(identity, dict) else "error",
                    "stateHash": before_hash,
                }
            runtime_supports.append(identity)
        try:
            result = engine.call(
                "configure_source_skill_supports",
                index=source_group_index,
                supportGemIds=[str(gem["gemId"]) for gem in runtime_supports],
            )
        except Exception:
            try:
                engine.load_build_xml(before_xml, name="source-support-exception-rollback")
            except Exception:
                pass
            raise
        if not isinstance(result, dict):
            engine.load_build_xml(before_xml, name="source-support-invalid-result-rollback")
            return _error("invalid_source_support_result", "PoB returned an invalid result")
        if result.get("ok") is False:
            if build_state_hash(engine.get_xml()) != before_hash:
                engine.load_build_xml(before_xml, name="source-support-failure-rollback")
            result.setdefault("stateHash", before_hash)
            return result

        after_xml = engine.get_xml()
        after_hash = build_state_hash(after_xml)
        after = _decorate(engine.call("list_skill_groups"), state_hash=after_hash)
        actual_group = _group_at(after, source_group_index)
        expected_supports = [str(gem["name"]) for gem in runtime_supports]
        actual_gems = (actual_group or {}).get("gems") or []
        actual_supports = [
            str(gem.get("name"))
            for gem in actual_gems[1:]
            if isinstance(gem, dict) and gem.get("isSupport")
        ]
        if actual_supports != expected_supports:
            engine.load_build_xml(before_xml, name="source-support-completeness-rollback")
            return {
                **_error(
                    "source_supports_incomplete",
                    "PoB did not preserve every requested source support; build restored",
                ),
                "requestedSupports": expected_supports,
                "appliedSupports": actual_supports,
                "stateHash": before_hash,
            }

        from .supportopt import carry_support_audit_to_configured_state

        carried_audit = carry_support_audit_to_configured_state(
            engine=engine,
            before_state_hash=before_hash,
            after_state_hash=after_hash,
            group_index=source_group_index,
            applied_supports=actual_supports,
        )

        return {
            "ok": True,
            "operation": "configure_source_skill_supports",
            "sourceGroupIndex": source_group_index,
            "source": source,
            "sourceKind": "item" if source.startswith("Item:") else "tree",
            "beforeStateHash": before_hash,
            "afterStateHash": after_hash,
            "stateHash": after_hash,
            "changed": before_hash != after_hash,
            "fingerprint": actual_group.get("fingerprint") if actual_group else None,
            "skillLevel": result.get("skillLevel"),
            "supportCapacity": result.get("capacity"),
            "selectedCommand": result.get("selectedCommand"),
            "requestedSupports": expected_supports,
            "supportApplication": result.get("supportApplication", []),
            "spiritBefore": result.get("spiritBefore"),
            "spiritAfter": result.get("spiritAfter"),
            "supportAudit": carried_audit,
            "group": actual_group,
        }


def _mutate(
    engine: PobEngine,
    *,
    method: str,
    group_index: int,
    expected_fingerprint: str,
    expected_state_hash: str | None,
    expected_gems: list[str] | None = None,
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
        if expected_gems is not None:
            actual = _canonical_actual_gems(_group_at(after, group_index))
            if Counter(actual) != Counter(expected_gems):
                engine.load_build_xml(before_xml, name="skill-group-completeness-rollback")
                return {
                    **_error(
                        "skill_group_incomplete",
                        "PoB did not persist every requested gem; build restored",
                    ),
                    "requestedGems": expected_gems,
                    "appliedGems": actual,
                    "droppedGemNames": list((Counter(expected_gems) - Counter(actual)).elements()),
                    "stateHash": before_hash,
                }
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


def _corpus_support_for_runtime_name(engine: PobEngine, name: str) -> dict[str, Any] | None:
    """Bind an exact PoB display label back to corpus identity without guessing aliases."""
    runtime = engine.call("resolve_support_gem_identity", runtimeName=name)
    if not isinstance(runtime, dict) or runtime.get("ok") is not True or runtime.get("status") != "resolved":
        return None
    corpus_ids = SkillEquivalenceIndex.shared().gem_ids_for_skill_key(str(runtime.get("effectId") or ""))
    if runtime.get("gameId") in corpus_ids:
        return db.get_gem(str(runtime["gameId"]))
    if len(corpus_ids) == 1:
        return db.get_gem(corpus_ids[0])
    return None


def _canonical_skill_request(engine: PobEngine, skill: str) -> tuple[list[str], list[str], str]:
    canonical: list[str] = []
    unresolved: list[str] = []
    lines: list[str] = []
    for line in normalize_skill_text(skill, default_level=None).splitlines():
        names = requested_gem_names(line)
        if not names:
            lines.append(line)
            continue
        name = names[0]
        gem = db.get_gem(name)
        if gem is None:
            gem = _corpus_support_for_runtime_name(engine, name)
        if gem is None:
            unresolved.append(name)
            continue
        canonical_name = str(gem["name"])
        if str(gem.get("gem_type") or "").lower() == "support":
            identity = engine.call(
                "resolve_support_gem_identity", gemIds=[str(gem["id"])],
                effectIds=list(gem.get("grants") or []),
            )
            if (not isinstance(identity, dict) or identity.get("ok") is not True
                    or identity.get("status") != "resolved" or not identity.get("name")):
                unresolved.append(name)
                continue
            canonical_name = str(identity["name"])
        canonical.append(canonical_name)
        # Keep every caller-specified level, quality and count; only the verified name changes.
        lines.append(canonical_name + line[len(name):])
    return canonical, unresolved, "\n".join(lines)


def _canonical_actual_gems(group: dict[str, Any] | None) -> list[str]:
    if not isinstance(group, dict):
        return []
    return [
        str(gem.get("name"))
        for gem in group.get("gems", [])
        if isinstance(gem, dict) and gem.get("name")
    ]


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
