"""Transactional equipment writes with canonical read-back and provenance verification."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from server.knowledge import item_legality, itemparse
from server.runtime import craft_receipts

from . import completeness
from .state import build_state_hash


_RECOVERY_ATTRIBUTE = "_poe2_mutation_batch_recovery_required"


def equip_item_verified(
    engine: Any,
    *,
    raw: str,
    slot: str | None,
    craft_receipt_ref: str | None,
) -> dict[str, Any]:
    """Equip and verify the actual slot text under one re-entrant transaction."""

    requested_structure = itemparse.semantic_item_structure(raw)
    has_special_source = bool(
        requested_structure.get("runeNames")
        or requested_structure.get("corrupted")
        or any(
            isinstance(value, dict) and value.get("kind") == "rune"
            for value in requested_structure.get("effects") or []
        )
    )
    if has_special_source and craft_receipt_ref is None:
        return {"ok": False, "errorCode": "special_source_provenance_required"}
    requested_audit = item_legality.audit_item(
        raw,
        craft_receipt_ref=craft_receipt_ref,
        slot=slot,
        require_special_provenance=True,
    )
    if not requested_audit.get("ok"):
        issues = [str(value) for value in requested_audit.get("issues") or []]
        return {
            "ok": False,
            "errorCode": (
                "special_source_provenance_required"
                if "special_source_provenance_required" in issues
                else "item_legality_check_failed"
            ),
            "itemLegality": requested_audit,
        }
    lock_factory = getattr(engine, "transaction_lock", None)
    with lock_factory() if callable(lock_factory) else nullcontext():
        return _equip_item_verified_locked(
            engine,
            raw=raw,
            slot=slot,
            craft_receipt_ref=craft_receipt_ref,
            requested_structure=requested_structure,
        )


def _equip_item_verified_locked(
    engine: Any,
    *,
    raw: str,
    slot: str | None,
    craft_receipt_ref: str | None,
    requested_structure: dict[str, Any],
) -> dict[str, Any]:
    try:
        snapshot = engine.get_xml()
        input_hash = build_state_hash(snapshot)
    except Exception:  # noqa: BLE001
        return {"ok": False, "errorCode": "item_equip_snapshot_failed"}
    try:
        first = engine.add_item(raw, slot=slot)
    except Exception:  # noqa: BLE001
        return _rollback_failure(engine, snapshot, input_hash, "item_equip_failed")
    if not isinstance(first, dict) or not first.get("ok"):
        return _rollback_failure(
            engine,
            snapshot,
            input_hash,
            str((first or {}).get("errorCode") or "item_equip_failed"),
        )
    actual_slot = str(first.get("slot") or slot or "")
    if not actual_slot:
        return _rollback_failure(engine, snapshot, input_hash, "item_readback_slot_missing")
    try:
        verified = _verify_actual_item(
            engine,
            raw=raw,
            requested_structure=requested_structure,
            slot=actual_slot,
            craft_receipt_ref=craft_receipt_ref,
        )
    except Exception:  # noqa: BLE001
        verified = {"ok": False}
    if verified.get("errorCode") == "augment_limit_exceeded":
        return _rollback_failure(engine, snapshot, input_hash, "augment_limit_exceeded")
    if verified.get("ok"):
        carried = _carry_socket_decision(
            engine,
            input_hash=input_hash,
            output_hash=build_state_hash(engine.get_xml()),
            slot=actual_slot,
            item_fingerprint=str(verified.get("actualItemFingerprint") or ""),
        )
        setattr(engine, _RECOVERY_ATTRIBUTE, False)
        return {
            **first,
            "itemLegality": verified["itemLegality"],
            "readbackVerified": True,
            **({"socketDecisionCarried": carried} if carried else {}),
        }

    # Pinned PoB can inherit Rune state across direct same-slot replacement. The first write gives
    # us the exact implicit slot; restore, clear that slot, and retry once inside this transaction.
    if not _restore(engine, snapshot, input_hash, "item-readback-retry-restore"):
        setattr(engine, _RECOVERY_ATTRIBUTE, True)
        return {
            "ok": False,
            "errorCode": "item_readback_rollback_failed",
            "rolledBack": False,
            "recoveryRequired": True,
        }
    try:
        cleared = engine.unequip_item(actual_slot)
        if not isinstance(cleared, dict) or not cleared.get("ok"):
            raise ValueError("item_slot_clear_failed")
        second = engine.add_item(raw, slot=actual_slot)
        if not isinstance(second, dict) or not second.get("ok"):
            raise ValueError("item_equip_failed")
        second_verified = _verify_actual_item(
            engine,
            raw=raw,
            requested_structure=requested_structure,
            slot=actual_slot,
            craft_receipt_ref=craft_receipt_ref,
        )
        if not second_verified.get("ok"):
            raise ValueError("item_readback_provenance_mismatch")
    except Exception:  # noqa: BLE001
        return _rollback_failure(
            engine,
            snapshot,
            input_hash,
            "item_readback_provenance_mismatch",
        )
    carried = _carry_socket_decision(
        engine,
        input_hash=input_hash,
        output_hash=build_state_hash(engine.get_xml()),
        slot=actual_slot,
        item_fingerprint=str(second_verified.get("actualItemFingerprint") or ""),
    )
    setattr(engine, _RECOVERY_ATTRIBUTE, False)
    return {
        **second,
        "slot": actual_slot,
        "itemLegality": second_verified["itemLegality"],
        "readbackVerified": True,
        "cleanSlotRetry": True,
        **({"socketDecisionCarried": carried} if carried else {}),
    }


def _verify_actual_item(
    engine: Any,
    *,
    raw: str,
    requested_structure: dict[str, Any],
    slot: str,
    craft_receipt_ref: str | None,
) -> dict[str, Any]:
    actual = completeness.equipped_item_text(engine.get_xml(), slot)
    if actual is None:
        return {"ok": False, "errorCode": "item_readback_missing"}
    actual_structure = itemparse.semantic_item_structure(actual)
    audit = item_legality.audit_item(
        actual,
        craft_receipt_ref=craft_receipt_ref,
        slot=slot,
        require_special_provenance=True,
    )
    if not audit.get("ok"):
        return {"ok": False, "errorCode": "item_readback_provenance_mismatch"}
    from . import socket_limits

    if not socket_limits.audit(engine.get_xml()).get("ok"):
        return {"ok": False, "errorCode": "augment_limit_exceeded"}
    if craft_receipt_ref is None:
        same_item = requested_structure.get("itemFingerprint") == actual_structure.get(
            "itemFingerprint"
        )
        if not same_item:
            same_item = _same_unique_identity(raw, actual)
    else:
        requested_resolution = craft_receipts.resolve_receipt(
            raw,
            receipt_ref=craft_receipt_ref,
            slot=slot,
        )
        actual_resolution = craft_receipts.resolve_receipt(
            actual,
            receipt_ref=craft_receipt_ref,
            slot=slot,
        )
        same_item = (
            requested_resolution.get("status") == "verified"
            and actual_resolution.get("status") == "verified"
        )
    return {
        "ok": bool(same_item),
        "errorCode": None if same_item else "item_readback_structure_mismatch",
        "itemLegality": audit,
        "actualItemFingerprint": actual_structure.get("itemFingerprint"),
    }


def _same_unique_identity(requested_text: str, actual_text: str) -> bool:
    """Allow PoB property normalization only for the same corpus-validated Unique."""

    requested = itemparse.parse_item(requested_text)
    actual = itemparse.parse_item(actual_text)
    return bool(
        requested.get("ok")
        and actual.get("ok")
        and str(requested.get("rarity") or "").casefold() == "unique"
        and str(actual.get("rarity") or "").casefold() == "unique"
        and str(requested.get("name") or "").strip().casefold()
        == str(actual.get("name") or "").strip().casefold()
        and str(requested.get("base") or "").strip().casefold()
        == str(actual.get("base") or "").strip().casefold()
        and itemparse._unique_modifiers_match(
            itemparse._unique_modifier_lines(actual_text, include_implicit=True),
            itemparse._unique_modifier_lines(requested_text, include_implicit=True),
        )
    )


def _carry_socket_decision(
    engine: Any,
    *,
    input_hash: str,
    output_hash: str,
    slot: str,
    item_fingerprint: str,
) -> str | None:
    if not item_fingerprint:
        return None
    from . import craftopt

    return craftopt.carry_socket_decision_to_equipped_state(
        engine,
        input_state_hash=input_hash,
        output_state_hash=output_hash,
        slot=slot,
        item_fingerprint=item_fingerprint,
    )


def _rollback_failure(
    engine: Any,
    xml: str,
    state_hash: str,
    error_code: str,
) -> dict[str, Any]:
    restored = _restore(engine, xml, state_hash, "item-readback-final-rollback")
    setattr(engine, _RECOVERY_ATTRIBUTE, not restored)
    return {
        "ok": False,
        "errorCode": error_code,
        "rolledBack": restored,
        "recoveryRequired": not restored,
    }


def _restore(engine: Any, xml: str, state_hash: str, name: str) -> bool:
    try:
        engine.load_build_xml(xml, name=name)
        return build_state_hash(engine.get_xml()) == state_hash
    except Exception:  # noqa: BLE001
        return False
