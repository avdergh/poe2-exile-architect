"""Shared state and measurement contracts for ordinary equipment searches."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from functools import wraps
import math
from typing import Any

from ..knowledge import itemparse
from ..knowledge.item_base_sources import ItemBaseSourceError
from . import completeness
from .state import build_state_hash
from ..runtime.compute_control import ComputeStopped, check_compute_budget, current_compute_control


_RECOVERY = "_poe2_mutation_batch_recovery_required"


class ItemSearchError(ValueError):
    def __init__(self, code: str, **details: Any):
        super().__init__(code)
        self.code = code
        self.details = details


def capture_selection(engine: Any) -> dict[str, Any] | None:
    """Capture MAIN/CALCS/effect/weapon-set identity separately from the semantic XML hash."""
    info = getattr(engine, 'info', None)
    if not isinstance(info, dict) or int(info.get('runtimeContract') or 0) < 15:
        return None  # Legacy test doubles; live engines must satisfy paths.POB_RUNTIME_CONTRACT.
    result = engine.call('item_replacement_selection')
    if not isinstance(result, dict) or not isinstance(result.get('main'), dict) or not isinstance(result.get('calcs'), dict):
        raise ItemSearchError('item_selection_evidence_missing')
    return result


def selection_matches(engine: Any, expected: dict[str, Any] | None) -> bool:
    return expected is None or capture_selection(engine) == expected


def _restore(engine: Any, snapshot: str, expected: str, selection: dict[str, Any] | None = None) -> bool:
    try:
        engine.load_build_xml(snapshot)
        return build_state_hash(engine.get_xml()) == expected and selection_matches(engine, selection)
    except Exception:  # noqa: BLE001 - recovery is proven by readback, not an exception message.
        return False


def restore_state(engine: Any, snapshot: str) -> None:
    if not _restore(engine, snapshot, build_state_hash(snapshot)):
        setattr(engine, _RECOVERY, True)
        raise ItemSearchError("item_search_restore_failed", recoveryRequired=True, rolledBack=False)


@contextmanager
def preserved_state(engine: Any):
    """Protect a nested counterfactual; it never becomes the next planning input."""
    snapshot = engine.get_xml()
    state_hash = build_state_hash(snapshot)
    selection = capture_selection(engine)
    try:
        yield snapshot
    finally:
        restored = _restore(engine, snapshot, state_hash, selection)
        if not restored:
            setattr(engine, _RECOVERY, True)
            raise ItemSearchError(
                "item_search_restore_failed", recoveryRequired=True, rolledBack=False
            )


def read_only_search(function):
    """Keep public searches atomic and surface restoration failures without item authorization."""

    @wraps(function)
    def guarded(engine, *args, **kwargs):
        if getattr(engine, _RECOVERY, False):
            return {
                "ok": False,
                "errorCode": "build_state_recovery_required",
                "recoveryRequired": True,
            }
        lock = getattr(engine, "transaction_lock", None)
        with lock() if callable(lock) else nullcontext():
            if getattr(engine, _RECOVERY, False):
                return {
                    "ok": False,
                    "errorCode": "build_state_recovery_required",
                    "recoveryRequired": True,
                }
            try:
                snapshot = engine.get_xml()
            except Exception:  # noqa: BLE001 - no mutation has been authorized without a snapshot.
                return {"ok": False, "errorCode": "item_search_snapshot_failed"}
            state_hash = build_state_hash(snapshot)
            selection = capture_selection(engine)
            stopped: ComputeStopped | None = None
            try:
                result = function(engine, *args, **kwargs)
            except ComputeStopped as exc:
                stopped = exc
                result = {'ok': False, 'errorCode': exc.reason}
            except ItemSearchError as exc:
                result = {"ok": False, "errorCode": exc.code, **exc.details}
            except ItemBaseSourceError as exc:
                result = {'ok': False, 'errorCode': str(exc)}
            except Exception:  # noqa: BLE001 - restore first and expose a bounded tool error.
                result = {"ok": False, "errorCode": "item_search_failed"}
            try:
                restored = build_state_hash(engine.get_xml()) == state_hash and selection_matches(engine, selection)
            except Exception:  # noqa: BLE001
                restored = False
            if (
                not restored
                or result.get("recoveryRequired") is True
                or getattr(engine, _RECOVERY, False)
            ):
                restored = _restore(engine, snapshot, state_hash, selection)
            if not restored:
                setattr(engine, _RECOVERY, True)
                return {
                    "ok": False,
                    "errorCode": "item_search_restore_failed",
                    "rolledBack": False,
                    "recoveryRequired": True,
                }
            setattr(engine, _RECOVERY, False)
            if stopped is not None:
                raise stopped
            return {
                **result,
                "stateHash": state_hash,
                "readOnly": True,
                "rolledBack": True,
                "recoveryRequired": False,
            }

    return guarded


def finite_stats(value: Any, keys: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or any(
        isinstance(value.get(key), bool)
        or not isinstance(value.get(key), (int, float))
        or not math.isfinite(value[key])
        for key in keys
    ):
        raise ItemSearchError("item_measurement_incomplete", requiredKeys=list(keys))
    return value


def baseline_stats(
    engine: Any, slot: str, keys: list[str], build: dict[str, Any], context: Any
) -> dict[str, Any]:
    """Keep a missing-weapon attack baseline unknown; never substitute zero for missing stats."""
    value = engine.get_stats(keys).get("stats")
    try:
        return finite_stats(value, keys)
    except ItemSearchError:
        check = build.get("mainSkillWeaponCheck") or {}
        if not (
            isinstance(value, dict)
            and slot == "Weapon 1"
            and build.get("activeWeaponSet") == 1
            and not (build.get("gear") or {}).get(slot)
            and completeness.equipped_item_text_from_engine(engine, slot) is None
            and isinstance(context, dict)
            and context.get("skillName")
            and check.get("skillName") == context["skillName"]
            and check.get("compatible") is False
            and check.get("weaponTypes")
            and check.get("equippedWeaponTypes") == []
            and all(key in {"TotalDPS", "FullDPS"} for key in keys if value.get(key) is None)
            and all(
                value.get(key) is None
                or (
                    not isinstance(value[key], bool)
                    and isinstance(value[key], (int, float))
                    and math.isfinite(value[key])
                )
                for key in keys
            )
        ):
            raise
        return {key: value.get(key) for key in keys}


def clear_slot(engine: Any, slot: str) -> None:
    result = engine.unequip_item(slot)
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise ItemSearchError("item_slot_clear_failed", slot=slot)
    if completeness.equipped_item_text_from_engine(engine, slot) is not None:
        raise ItemSearchError("item_slot_clear_not_applied", slot=slot)


def resistances_without_slot(engine: Any, slot: str) -> dict[str, Any]:
    """Ask PoB after removing the old item, including its Rune and conditional contributions."""
    with preserved_state(engine):
        clear_slot(engine, slot)
        response = engine.get_defenses()
        return dict(
            finite_stats(
                response.get("resistances") if isinstance(response, dict) else None,
                ["fire", "cold", "lightning", "chaos"],
            )
        )


def evaluate_items(
    engine: Any, slot: str, items: list[str], keys: list[str]
) -> list[dict[str, Any]]:
    """Only complete, same-context measurements may enter ranking or no-gain decisions."""
    if not items:
        return []
    if current_compute_control() is not None:
        output = []
        # Lua RPCs are atomic. Yield cancellation at a bounded native-batch return boundary,
        # without degrading the normal synchronous path into per-item full restores.
        for offset in range(0, len(items), 16):
            check_compute_budget()
            try:
                output.extend(_evaluate_item_batch(engine, slot, items[offset:offset + 16], keys))
            except ItemSearchError as exc:
                if isinstance(exc.details.get('candidateIndex'), int):
                    exc.details['candidateIndex'] += offset
                raise
            check_compute_budget()
        return output
    return _evaluate_item_batch(engine, slot, items, keys)


def _evaluate_item_batch(
    engine: Any, slot: str, items: list[str], keys: list[str]
) -> list[dict[str, Any]]:
    before = build_state_hash(engine.get_xml())
    selection = capture_selection(engine)
    response = engine.eval_items(slot, items, keys=keys, replacement_context=True)
    if (
        not isinstance(response, dict)
        or response.get("ok") is False
        or response.get("recoveryRequired") is True
    ):
        raise ItemSearchError(
            "item_candidate_evaluation_failed",
            slot=slot,
            recoveryRequired=isinstance(response, dict)
            and response.get("recoveryRequired") is True,
        )
    if (
        response.get("contextVersion") != "item_replacement_context_v1"
        or response.get("rolledBack") is not True
    ):
        raise ItemSearchError("item_candidate_evaluation_unverified", slot=slot)
    if build_state_hash(engine.get_xml()) != before or not selection_matches(engine, selection):
        raise ItemSearchError("item_candidate_state_changed", slot=slot)
    values = response.get("results")
    if not isinstance(values, list) or len(values) != len(items):
        raise ItemSearchError(
            "item_measurement_count_mismatch", slot=slot, expectedCount=len(items)
        )
    failures = response.get("failureCodes")
    if failures is not None and (not isinstance(failures, list) or len(failures) != len(items)):
        raise ItemSearchError(
            "item_measurement_count_mismatch", slot=slot, expectedCount=len(items)
        )
    for index, stats in enumerate(values):
        try:
            if failures and failures[index] not in (False, None):
                raise ItemSearchError("item_measurement_incomplete")
            finite_stats(stats, keys)
        except ItemSearchError as exc:
            raise ItemSearchError(
                exc.code,
                slot=slot,
                candidateIndex=index,
                failureCodes=response.get("failureCodes") or [],
            ) from exc
    return values


def capture_context(engine: Any) -> Any:
    response = engine.inspect_item_replacement_context()
    if not isinstance(response, dict) or response.get("ok") is not True:
        raise ItemSearchError("item_calculation_context_missing")
    return response.get("calculationContext")


def verify_context(engine: Any, context: Any, *, slot: str) -> None:
    """Select only the uniquely verified original output after a temporary equip."""
    if context is not None:
        resolved = engine.inspect_item_replacement_context(expected_context=context)
        if not isinstance(resolved, dict) or resolved.get("ok") is not True:
            raise ItemSearchError("item_calculation_context_mismatch", slot=slot)
        target = resolved.get("calculationContext") or {}
        if target.get("selectionMatches") is True:
            return
        selected = engine.call(
            "set_skill_group_state",
            index=target["groupIndex"],
            activeSkillIndex=target["activeSkillIndex"],
            makeMain=True,
        )
        if not isinstance(selected, dict) or selected.get("ok") is not True:
            raise ItemSearchError("item_calculation_context_mismatch", slot=slot)
        verified = engine.inspect_item_replacement_context(expected_context=context)
        if not isinstance(verified, dict) or verified.get("ok") is not True:
            raise ItemSearchError("item_calculation_context_mismatch", slot=slot)
        # Legacy fake engines omit this field; runtime contract 15 always emits it.
        if (verified.get("calculationContext") or {}).get("selectionMatches") is False:
            raise ItemSearchError("item_calculation_context_mismatch", slot=slot)


def equip_candidate(engine: Any, raw: str, slot: str, context: Any) -> str:
    """Stage the complete proposed item, without old Rune inheritance or target substitution."""
    result = engine.add_item(raw, slot=slot)
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise ItemSearchError("item_candidate_equip_failed", slot=slot)
    actual = completeness.equipped_item_text_from_engine(engine, slot)
    if (
        not actual
        or itemparse.semantic_item_structure(actual)["itemFingerprint"]
        != itemparse.semantic_item_structure(raw)["itemFingerprint"]
    ):
        raise ItemSearchError("item_candidate_readback_mismatch", slot=slot)
    verify_context(engine, context, slot=slot)
    return actual
