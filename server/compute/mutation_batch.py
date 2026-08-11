"""Atomic batches for Agent-authored mechanical PoB mutations.

The batch deliberately excludes every optimizer.  It only reduces model/tool round trips after the
Agent has already decided the exact class, level, skills, items, passives and configuration.
"""

from __future__ import annotations

from collections.abc import Callable
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .state import build_state_hash


FunctionalBatchKind = Literal[
    "bootstrap",
    "mechanism_shell",
    "skill_loadout",
    "passive_delta",
    "required_gear",
    "ordinary_gear",
    "config",
]

MutationKind = Literal[
    "new_build",
    "set_class",
    "set_level",
    "set_main_skill",
    "add_skill_group",
    "set_config",
    "equip_item",
    "unequip_item",
    "equip_jewel",
    "allocate_passive",
    "deallocate_passive",
]

MAX_FUNCTIONAL_BATCH_OPERATIONS = 16
MAX_FUNCTIONAL_BATCH_PAYLOAD_BYTES = 128_000

_WEAPON_SLOTS = frozenset(
    {
        "Weapon 1",
        "Weapon 2",
        "Weapon 1 Swap",
        "Weapon 2 Swap",
    }
)
_GEAR_SLOTS = frozenset(
    {
        "Helmet",
        "Body Armour",
        "Gloves",
        "Boots",
        "Belt",
        "Amulet",
        "Ring 1",
        "Ring 2",
        "Flask 1",
        "Flask 2",
        "Charm 1",
        "Charm 2",
        "Charm 3",
    }
)
_JEWEL_SLOT = re.compile(r"^Jewel \d+$")
_SCOPE_LIMITS: dict[FunctionalBatchKind, int] = {
    "bootstrap": 3,
    "mechanism_shell": 6,
    "skill_loadout": 8,
    "passive_delta": 16,
    "required_gear": 4,
    "ordinary_gear": 10,
    "config": 1,
}
_SCOPE_OPERATIONS: dict[FunctionalBatchKind, frozenset[MutationKind]] = {
    "bootstrap": frozenset({"new_build", "set_class", "set_level"}),
    "mechanism_shell": frozenset(
        {
            "set_main_skill",
            "add_skill_group",
            "equip_item",
            "unequip_item",
        }
    ),
    "skill_loadout": frozenset({"add_skill_group"}),
    "passive_delta": frozenset({"allocate_passive", "deallocate_passive"}),
    "required_gear": frozenset({"equip_item", "unequip_item", "equip_jewel"}),
    "ordinary_gear": frozenset({"equip_item", "unequip_item", "equip_jewel"}),
    "config": frozenset({"set_config"}),
}
_RECOVERY_REQUIRED_ATTRIBUTE = "_poe2_mutation_batch_recovery_required"


def _snake_to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


class BuildMutationOperation(BaseModel):
    """One exact, non-search mutation inside an atomic batch."""

    model_config = ConfigDict(
        alias_generator=_snake_to_camel,
        extra="forbid",
        populate_by_name=True,
        strict=True,
    )

    operation: MutationKind
    class_name: str | None = Field(default=None, min_length=1, max_length=80)
    ascendancy: str | None = Field(default=None, min_length=1, max_length=120)
    level: int | None = Field(default=None, ge=1, le=100)
    skill: str | None = Field(default=None, min_length=1, max_length=12_000)
    in_full_dps: bool = False
    options: dict[str, Any] | None = Field(default=None, max_length=120)
    custom_mods: str | None = Field(default=None, max_length=12_000)
    raw: str | None = Field(default=None, min_length=1, max_length=40_000)
    slot: str | None = Field(default=None, min_length=1, max_length=120)
    craft_receipt_ref: str | None = Field(
        default=None,
        pattern=r"^craft-legality:[a-f0-9]{64}$",
    )
    socket: int | None = Field(default=None, ge=0)
    node: str | int | None = None

    @model_validator(mode="after")
    def _operation_contract(self) -> "BuildMutationOperation":
        required: dict[str, set[str]] = {
            "new_build": set(),
            "set_class": {"class_name"},
            "set_level": {"level"},
            "set_main_skill": {"skill"},
            "add_skill_group": {"skill"},
            "set_config": set(),
            "equip_item": {"raw"},
            "unequip_item": {"slot"},
            "equip_jewel": {"raw"},
            "allocate_passive": {"node"},
            "deallocate_passive": {"node"},
        }
        values = {
            "class_name": self.class_name,
            "ascendancy": self.ascendancy,
            "level": self.level,
            "skill": self.skill,
            "options": self.options,
            "custom_mods": self.custom_mods,
            "raw": self.raw,
            "slot": self.slot,
            "craft_receipt_ref": self.craft_receipt_ref,
            "socket": self.socket,
            "node": self.node,
        }
        missing = sorted(key for key in required[self.operation] if values[key] is None)
        if missing:
            raise ValueError(f"{self.operation} requires: {', '.join(missing)}")
        if self.operation == "set_config" and self.options is None and self.custom_mods is None:
            raise ValueError("set_config requires options or custom_mods")
        allowed: dict[str, set[str]] = {
            "new_build": set(),
            "set_class": {"class_name", "ascendancy"},
            "set_level": {"level"},
            "set_main_skill": {"skill"},
            "add_skill_group": {"skill", "in_full_dps"},
            "set_config": {"options", "custom_mods"},
            "equip_item": {"raw", "slot", "craft_receipt_ref"},
            "unequip_item": {"slot"},
            "equip_jewel": {"raw", "socket"},
            "allocate_passive": {"node"},
            "deallocate_passive": {"node"},
        }
        explicitly_set = set(self.model_fields_set) - {"operation"}
        unexpected = sorted(explicitly_set - allowed[self.operation])
        if unexpected:
            raise ValueError(f"{self.operation} does not accept: {', '.join(unexpected)}")
        if isinstance(self.node, str) and not self.node.strip():
            raise ValueError("passive node cannot be blank")
        return self


ResultDecorator = Callable[[BuildMutationOperation, dict[str, Any]], dict[str, Any]]


def apply_build_mutation_batch(
    engine: Any,
    *,
    batch_kind: FunctionalBatchKind,
    operations: list[BuildMutationOperation],
    expected_state_hash: str | None = None,
    result_decorator: ResultDecorator | None = None,
) -> dict[str, Any]:
    """Apply one small functional mutation batch and roll back only that batch on failure."""

    contract_error, contract_details = _validate_batch_contract(
        batch_kind=batch_kind,
        operations=operations,
        expected_state_hash=expected_state_hash,
    )
    if contract_error is not None:
        return {
            **_rejected(contract_error, batch_kind=batch_kind),
            **contract_details,
        }
    with engine.transaction_lock():
        recovery_bootstrap = batch_kind == "bootstrap" and operations[0].operation == "new_build"
        if bool(getattr(engine, _RECOVERY_REQUIRED_ATTRIBUTE, False)) and not recovery_bootstrap:
            return {
                **_rejected("mutation_batch_recovery_required", batch_kind=batch_kind),
                "recoveryRequired": True,
                "recoveryAction": "run_bootstrap_from_new_build",
            }
        try:
            input_xml = engine.get_xml()
        except Exception:  # noqa: BLE001 - never expose engine internals.
            return _rejected("mutation_batch_snapshot_failed", batch_kind=batch_kind)
        input_hash = build_state_hash(input_xml)
        if expected_state_hash is not None and expected_state_hash != input_hash:
            return {
                **_rejected("build_state_conflict", batch_kind=batch_kind),
                "expectedStateHash": expected_state_hash,
                "actualStateHash": input_hash,
                "recoveryHint": (
                    "The active build changed since your expected state (any mutating tool — "
                    "equip_item, add_skill_group, plan_gear, set_config, etc. — updates the "
                    "state hash). Re-read the latest outputStateHash / stateHash from your "
                    "previous call and pass it as expected_state_hash."
                ),
            }

        step_results: list[dict[str, Any]] = []
        raw_results: list[dict[str, Any]] = []
        advisories: list[dict[str, Any]] = []
        for index, operation in enumerate(operations):
            try:
                raw_result = _apply_operation(engine, operation)
                if result_decorator is not None:
                    raw_result = result_decorator(operation, raw_result)
            except Exception:  # noqa: BLE001 - return a stable error and restore the snapshot.
                return _rollback(
                    engine,
                    batch_kind=batch_kind,
                    input_xml=input_xml,
                    input_hash=input_hash,
                    failed_index=index,
                    failed_operation=operation.operation,
                    error_code="mutation_operation_failed",
                    step_results=step_results,
                )
            if not isinstance(raw_result, dict):
                raw_result = {"ok": True}
            if raw_result.get("ok") is False:
                return _rollback(
                    engine,
                    batch_kind=batch_kind,
                    input_xml=input_xml,
                    input_hash=input_hash,
                    failed_index=index,
                    failed_operation=operation.operation,
                    error_code=str(raw_result.get("errorCode") or "mutation_operation_rejected"),
                    step_results=step_results,
                    failure_details={
                        "engineError": str(raw_result.get("error") or "")
                        or "engine rejected the operation without a message",
                        **(
                            {"legalityIssues": raw_result.get("legalityCheck", {}).get("issues")}
                            if isinstance(raw_result.get("legalityCheck"), dict)
                            else {}
                        ),
                    },
                )
            semantic_error, semantic_details = _operation_postcondition_error(
                batch_kind=batch_kind,
                operation=operation,
                result=raw_result,
            )
            if semantic_error is not None:
                return _rollback(
                    engine,
                    batch_kind=batch_kind,
                    input_xml=input_xml,
                    input_hash=input_hash,
                    failed_index=index,
                    failed_operation=operation.operation,
                    error_code=semantic_error,
                    step_results=step_results,
                    failure_details=semantic_details,
                )
            safe_step = {
                "index": index,
                "operation": operation.operation,
                "ok": True,
            }
            selector = _operation_selector(operation)
            if selector is not None:
                safe_step["selector"] = selector
            warning_codes = _warning_codes(raw_result)
            if warning_codes:
                safe_step["advisories"] = warning_codes
                advisories.append(
                    {
                        "index": index,
                        "operation": operation.operation,
                        "codes": warning_codes,
                    }
                )
            if isinstance(raw_result.get("illegalAffixes"), list):
                safe_step["illegalAffixCount"] = len(raw_result["illegalAffixes"])
            step_results.append(safe_step)
            raw_results.append(raw_result)

        try:
            postconditions, postcondition_error = _scope_postconditions(
                engine,
                batch_kind=batch_kind,
                operations=operations,
                raw_results=raw_results,
            )
        except Exception:  # noqa: BLE001 - restore on read-back/postcondition failures too.
            return _rollback(
                engine,
                batch_kind=batch_kind,
                input_xml=input_xml,
                input_hash=input_hash,
                failed_index=len(operations),
                failed_operation="scope_postconditions",
                error_code="mutation_batch_postcondition_failed",
                step_results=step_results,
            )
        if postcondition_error is not None:
            return _rollback(
                engine,
                batch_kind=batch_kind,
                input_xml=input_xml,
                input_hash=input_hash,
                failed_index=len(operations),
                failed_operation="scope_postconditions",
                error_code=postcondition_error,
                step_results=step_results,
                failure_details=postconditions,
            )
        try:
            output_hash = build_state_hash(engine.get_xml())
        except Exception:  # noqa: BLE001
            return _rollback(
                engine,
                batch_kind=batch_kind,
                input_xml=input_xml,
                input_hash=input_hash,
                failed_index=len(operations),
                failed_operation="final_snapshot",
                error_code="mutation_batch_final_snapshot_failed",
                step_results=step_results,
            )
        setattr(engine, _RECOVERY_REQUIRED_ATTRIBUTE, False)
        return {
            "status": "applied",
            "ok": True,
            "batchKind": batch_kind,
            "operationCount": len(operations),
            "scopeOperationLimit": _SCOPE_LIMITS[batch_kind],
            "operations": step_results,
            "advisories": advisories,
            "postconditions": postconditions,
            "inputStateHash": input_hash,
            "outputStateHash": output_hash,
            "changed": output_hash != input_hash,
            "atomic": True,
            "rollbackScope": "current_functional_batch_only",
            "recoveryRequired": False,
            "optimizerOperationsAllowed": False,
            "noRawMaterial": True,
        }


def _validate_batch_contract(
    *,
    batch_kind: FunctionalBatchKind,
    operations: list[BuildMutationOperation],
    expected_state_hash: str | None,
) -> tuple[str | None, dict[str, Any]]:
    limit = _SCOPE_LIMITS[batch_kind]
    if not 1 <= len(operations) <= limit:
        return "mutation_batch_scope_size_invalid", {
            "operationCount": len(operations),
            "scopeOperationLimit": limit,
        }
    invalid = [
        {"index": index, "operation": operation.operation}
        for index, operation in enumerate(operations)
        if operation.operation not in _SCOPE_OPERATIONS[batch_kind]
    ]
    if invalid:
        return "mutation_batch_scope_operation_invalid", {"invalidOperations": invalid}

    starts_with_reset = operations[0].operation == "new_build"
    if batch_kind == "bootstrap":
        counts = _operation_counts(operations)
        if counts.get("new_build", 0) > 1 or (
            counts.get("new_build", 0) == 1 and not starts_with_reset
        ):
            return "mutation_batch_reset_must_be_first", {}
        if counts.get("set_class", 0) != 1 or counts.get("set_level", 0) != 1:
            return "mutation_batch_bootstrap_identity_required", {
                "requiredOperations": ["set_class", "set_level"],
            }
    elif any(operation.operation == "new_build" for operation in operations):
        return "mutation_batch_reset_scope_invalid", {}

    if batch_kind == "mechanism_shell":
        if _operation_counts(operations).get("set_main_skill", 0) != 1:
            return "mutation_batch_main_skill_required", {}
        slot_error = _validate_item_slots(operations, allowed_slots=_WEAPON_SLOTS)
        if slot_error is not None:
            return slot_error, {}
    elif batch_kind in {"required_gear", "ordinary_gear"}:
        slot_error = _validate_item_slots(
            operations,
            allowed_slots=_WEAPON_SLOTS | _GEAR_SLOTS,
            allow_jewel_slots=True,
        )
        if slot_error is not None:
            return slot_error, {}
        if any(
            operation.operation == "equip_jewel" and operation.socket is None
            for operation in operations
        ):
            return "mutation_batch_explicit_jewel_socket_required", {}

    if expected_state_hash is None and not (batch_kind == "bootstrap" and starts_with_reset):
        return "mutation_batch_expected_state_hash_required", {}

    duplicate_selector = _duplicate_operation_selector(operations)
    if duplicate_selector is not None:
        return "mutation_batch_duplicate_selector", {"duplicateSelector": duplicate_selector}

    payload_size = len(
        json.dumps(
            [operation.model_dump(by_alias=True, exclude_none=True) for operation in operations],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if payload_size > MAX_FUNCTIONAL_BATCH_PAYLOAD_BYTES:
        return "mutation_batch_payload_too_large", {
            "payloadBytes": payload_size,
            "maximumPayloadBytes": MAX_FUNCTIONAL_BATCH_PAYLOAD_BYTES,
        }
    return None, {}


def _operation_counts(operations: list[BuildMutationOperation]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for operation in operations:
        counts[operation.operation] = counts.get(operation.operation, 0) + 1
    return counts


def _validate_item_slots(
    operations: list[BuildMutationOperation],
    *,
    allowed_slots: frozenset[str],
    allow_jewel_slots: bool = False,
) -> str | None:
    for operation in operations:
        if operation.operation not in {"equip_item", "unequip_item"}:
            continue
        if operation.slot is None:
            return "mutation_batch_explicit_item_slot_required"
        if operation.slot not in allowed_slots:
            if (
                allow_jewel_slots
                and operation.operation == "unequip_item"
                and _JEWEL_SLOT.fullmatch(operation.slot)
            ):
                continue
            return "mutation_batch_item_slot_outside_scope"
        if operation.operation == "equip_item" and _is_quiver_item(operation.raw):
            # AGENTS.md: quivers map to the engine slot "Weapon 2" and are whitelisted in no
            # batch scope; they must go through the standalone equip_item tool.
            return "mutation_batch_quiver_requires_direct_equip"
    return None


def _is_quiver_item(raw: str | None) -> bool:
    """Best-effort quiver detection from PoB item text; unparseable text never blocks."""
    if not raw:
        return False
    try:
        from server.knowledge import itemparse

        parsed = itemparse.parse_item(raw)
    except Exception:  # pragma: no cover - defensive; parse failures must not block batches
        return False
    return str(parsed.get("itemClass") or "").casefold() == "quiver"


def _duplicate_operation_selector(
    operations: list[BuildMutationOperation],
) -> str | None:
    seen: set[str] = set()
    for operation in operations:
        selector = _operation_selector(operation, safe=False)
        if selector is None:
            continue
        if operation.operation in {"equip_item", "unequip_item"}:
            domain = "item"
        elif operation.operation == "equip_jewel":
            domain = "jewel"
        elif operation.operation in {"allocate_passive", "deallocate_passive"}:
            domain = "passive"
        elif operation.operation in {"set_main_skill", "add_skill_group"}:
            domain = "skill"
        else:
            domain = operation.operation
        canonical = f"{domain}:{selector}".casefold()
        if canonical in seen:
            return canonical
        seen.add(canonical)
    return None


def _operation_selector(
    operation: BuildMutationOperation,
    *,
    safe: bool = True,
) -> str | int | None:
    if operation.operation in {"equip_item", "unequip_item"}:
        return operation.slot
    if operation.operation == "equip_jewel":
        return operation.socket
    if operation.operation in {"allocate_passive", "deallocate_passive"}:
        return operation.node
    if operation.operation in {"set_main_skill", "add_skill_group"} and operation.skill:
        normalized = re.sub(r"\s+", " ", operation.skill).strip()
        return None if safe else normalized
    if operation.operation == "set_class":
        return operation.class_name
    if operation.operation == "set_level":
        return operation.level
    return None


def _operation_postcondition_error(
    *,
    batch_kind: FunctionalBatchKind,
    operation: BuildMutationOperation,
    result: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    if operation.operation == "set_class":
        if not _same_text(result.get("class"), operation.class_name):
            return "mutation_batch_identity_postcondition_failed", {"field": "class"}
        if operation.ascendancy is not None and not _same_text(
            result.get("ascendancy"),
            operation.ascendancy,
        ):
            return "mutation_batch_identity_postcondition_failed", {"field": "ascendancy"}
    elif operation.operation == "set_level":
        if result.get("level") != operation.level:
            return "mutation_batch_identity_postcondition_failed", {"field": "level"}
    elif operation.operation == "set_main_skill":
        if not str(result.get("mainSkill") or "").strip():
            return "mutation_batch_main_skill_postcondition_failed", {}
    elif operation.operation in {"equip_item", "unequip_item"}:
        if not _same_text(result.get("slot"), operation.slot):
            return "mutation_batch_item_slot_postcondition_failed", {
                "expectedSlot": operation.slot,
            }
        if operation.operation == "equip_item" and result.get("illegalAffixes"):
            return "mutation_batch_item_legality_rejected", {
                "illegalAffixCount": len(result["illegalAffixes"]),
            }
    elif operation.operation == "equip_jewel":
        if result.get("socket") != operation.socket:
            return "mutation_batch_jewel_socket_postcondition_failed", {
                "expectedSocket": operation.socket,
            }
        if "not allocated" in str(result.get("warning") or "").casefold():
            return "mutation_batch_jewel_socket_unallocated", {
                "socket": operation.socket,
            }
    elif operation.operation in {"allocate_passive", "deallocate_passive"}:
        if not isinstance(result.get("node"), dict):
            return "mutation_batch_passive_postcondition_failed", {
                "node": operation.node,
            }
        if (
            batch_kind == "passive_delta"
            and "over budget" in str(result.get("warning") or "").casefold()
        ):
            return "mutation_batch_passive_budget_rejected", {
                "node": operation.node,
            }
    return None, {}


def _same_text(actual: Any, expected: Any) -> bool:
    return str(actual or "").strip().casefold() == str(expected or "").strip().casefold()


def _scope_postconditions(
    engine: Any,
    *,
    batch_kind: FunctionalBatchKind,
    operations: list[BuildMutationOperation],
    raw_results: list[dict[str, Any]],
) -> tuple[dict[str, Any], str | None]:
    if batch_kind == "bootstrap":
        class_operation = next(
            operation for operation in operations if operation.operation == "set_class"
        )
        level_operation = next(
            operation for operation in operations if operation.operation == "set_level"
        )
        return (
            {
                "status": "passed",
                "class": class_operation.class_name,
                "ascendancy": class_operation.ascendancy or "None",
                "level": level_operation.level,
            },
            None,
        )
    if batch_kind == "mechanism_shell":
        build = engine.get_build()
        main_skill = str(build.get("mainSkill") or "").strip()
        if not main_skill:
            return {"status": "failed", "check": "main_skill"}, (
                "mutation_batch_main_skill_postcondition_failed"
            )
        weapon_check = build.get("mainSkillWeaponCheck")
        if isinstance(weapon_check, dict) and weapon_check.get("compatible") is False:
            return (
                {
                    "status": "failed",
                    "check": "weapon_compatibility",
                    "skillName": weapon_check.get("skillName") or main_skill,
                    "requiredWeaponTypes": weapon_check.get("weaponTypes") or [],
                    "equippedWeaponTypes": weapon_check.get("equippedWeaponTypes") or [],
                },
                "mutation_batch_mechanism_weapon_incompatible",
            )
        return (
            {
                "status": "passed",
                "mainSkill": main_skill,
                "weaponCompatibility": (
                    "compatible" if isinstance(weapon_check, dict) else "not_applicable_or_unknown"
                ),
                "resourceClosureVerification": "deferred_to_generation_checkpoint",
            },
            None,
        )
    if batch_kind == "skill_loadout":
        state = engine.call("list_skill_groups")
        groups = state.get("groups") if isinstance(state, dict) else None
        if not isinstance(groups, list) or len(groups) < len(operations):
            return {"status": "failed", "check": "skill_group_count"}, (
                "mutation_batch_skill_loadout_postcondition_failed"
            )
        return (
            {
                "status": "passed",
                "skillGroupCount": len(groups),
                "addedGroupCount": len(operations),
                "freshFingerprintReadRequiredForPreciseEdits": True,
            },
            None,
        )
    if batch_kind == "passive_delta":
        return (
            {
                "status": "passed",
                "allocatedOperationCount": sum(
                    operation.operation == "allocate_passive" for operation in operations
                ),
                "deallocatedOperationCount": sum(
                    operation.operation == "deallocate_passive" for operation in operations
                ),
                "pointsSpent": sum(int(result.get("pointsSpent") or 0) for result in raw_results),
                "pointsFreed": sum(int(result.get("pointsFreed") or 0) for result in raw_results),
            },
            None,
        )
    if batch_kind in {"required_gear", "ordinary_gear"}:
        return (
            {
                "status": "passed",
                "touchedSelectors": [
                    selector
                    for operation in operations
                    if (selector := _operation_selector(operation)) is not None
                ],
                "deterministicLegalityWarnings": 0,
            },
            None,
        )
    config_operation = operations[0]
    return (
        {
            "status": "passed",
            "appliedOptionKeys": sorted((config_operation.options or {}).keys()),
            "customModsChanged": config_operation.custom_mods is not None,
            "verificationStrength": "engine_accepted",
        },
        None,
    )


def _apply_operation(engine: Any, operation: BuildMutationOperation) -> dict[str, Any]:
    if operation.operation == "new_build":
        return engine.new_build()
    if operation.operation == "set_class":
        return engine.set_class(operation.class_name, ascendancy=operation.ascendancy)
    if operation.operation == "set_level":
        return engine.set_level(operation.level)
    if operation.operation == "set_main_skill":
        return engine.paste_skill(operation.skill)
    if operation.operation == "add_skill_group":
        return engine.add_skill_group(
            operation.skill,
            include_in_full_dps=operation.in_full_dps,
        )
    if operation.operation == "set_config":
        return engine.set_config(
            options=operation.options,
            custom_mods=operation.custom_mods,
        )
    if operation.operation == "equip_item":
        return engine.add_item(operation.raw, slot=operation.slot)
    if operation.operation == "unequip_item":
        return engine.unequip_item(operation.slot)
    if operation.operation == "equip_jewel":
        return engine.equip_jewel(operation.raw, socket=operation.socket)
    if operation.operation == "allocate_passive":
        return engine.alloc_passive(operation.node)
    if operation.operation == "deallocate_passive":
        return engine.dealloc_passive(operation.node)
    raise ValueError("unsupported mutation operation")


def _rollback(
    engine: Any,
    *,
    batch_kind: FunctionalBatchKind,
    input_xml: str,
    input_hash: str,
    failed_index: int,
    failed_operation: str,
    error_code: str,
    step_results: list[dict[str, Any]],
    failure_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rollback_ok = False
    try:
        engine.load_build_xml(input_xml, name="mutation-batch-rollback")
        rollback_ok = build_state_hash(engine.get_xml()) == input_hash
    except Exception:  # noqa: BLE001
        rollback_ok = False
    setattr(engine, _RECOVERY_REQUIRED_ATTRIBUTE, not rollback_ok)
    return {
        "status": "rejected",
        "ok": False,
        "batchKind": batch_kind,
        "errorCode": error_code,
        "failedOperationIndex": failed_index,
        "failedOperation": failed_operation,
        "attemptedOperationsBeforeFailure": step_results,
        "persistedOperationCount": 0 if rollback_ok else None,
        "rolledBack": rollback_ok,
        "inputStateHash": input_hash,
        "currentStateHash": input_hash if rollback_ok else None,
        "atomic": rollback_ok,
        "atomicRequested": True,
        "rollbackScope": "current_functional_batch_only",
        "recoveryRequired": not rollback_ok,
        "failureDetails": failure_details or {},
        "optimizerOperationsAllowed": False,
        "noRawMaterial": True,
    }


def _warning_codes(result: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    if result.get("illegalAffixes"):
        codes.append("illegal_item_affixes")
    if result.get("legalityWarning"):
        codes.append("item_legality_warning")
    if result.get("warning"):
        codes.append("engine_warning")
    raw = result.get("warnings")
    if isinstance(raw, list) and raw:
        codes.append("engine_warnings")
    if result.get("engineLimitation"):
        codes.append("engine_limitation")
    return list(dict.fromkeys(codes))


def _rejected(
    error_code: str,
    *,
    batch_kind: FunctionalBatchKind | None = None,
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "ok": False,
        "errorCode": error_code,
        "batchKind": batch_kind,
        "atomic": True,
        "stateChanged": False,
        "recoveryRequired": False,
        "optimizerOperationsAllowed": False,
        "noRawMaterial": True,
    }
