"""Transactional equipment writes with canonical read-back and provenance verification."""

from __future__ import annotations

from contextlib import nullcontext
import re
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

    if slot is not None and re.fullmatch(r"Jewel \d+", slot):
        return equip_jewel_verified(
            engine, raw=raw, socket=int(slot.split()[1]), craft_receipt_ref=craft_receipt_ref
        )

    requested_structure = itemparse.semantic_item_structure(raw)
    requested_audit = item_legality.audit_item(
        raw,
        craft_receipt_ref=craft_receipt_ref,
        slot=slot,
        require_special_provenance=True,
        require_explicit_craft_receipt=True,
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
    if getattr(engine, _RECOVERY_ATTRIBUTE, False):
        return {
            "ok": False,
            "errorCode": "mutation_batch_recovery_required",
            "recoveryRequired": True,
        }
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
            "outputStateHash": build_state_hash(engine.get_xml()),
            **({"socketDecisionCarried": carried} if carried else {}),
        }

    # Restore and retry the complete raw item once. The bridge parses an independent item;
    # an empty-slot recalculation here would discard dependent offhands before replacement.
    if not _restore(engine, snapshot, input_hash, "item-readback-retry-restore"):
        setattr(engine, _RECOVERY_ATTRIBUTE, True)
        return {
            "ok": False,
            "errorCode": "item_readback_rollback_failed",
            "rolledBack": False,
            "recoveryRequired": True,
        }
    try:
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
        "outputStateHash": build_state_hash(engine.get_xml()),
        "cleanSlotRetry": True,
        **({"socketDecisionCarried": carried} if carried else {}),
    }


def equip_jewel_verified(
    engine: Any,
    *,
    raw: str,
    socket: int | None,
    craft_receipt_ref: str | None = None,
    expected_state_hash: str | None = None,
) -> dict[str, Any]:
    """Fill/replace one explicit, already allocated socket without spending passive points.

    New socket acquisition still belongs to evaluate/apply_next_jewel_socket_decision. This
    transaction validates the item's own legality during construction; final whole-build
    attributes/resources and quality are checked by Checkpoint/Judge.
    """
    if type(socket) is not int or socket < 0:
        return {"ok": False, "errorCode": "explicit_jewel_socket_required"}
    slot = f"Jewel {socket}"
    input_audit = item_legality.audit_jewel_input(
        raw, slot=slot, craft_receipt_ref=craft_receipt_ref
    )
    if not input_audit.get("ok"):
        return input_audit
    structure = input_audit["itemStructure"]
    with engine.transaction_lock():
        if getattr(engine, _RECOVERY_ATTRIBUTE, False):
            return {
                "ok": False,
                "errorCode": "mutation_batch_recovery_required",
                "recoveryRequired": True,
            }
        try:
            snapshot = engine.get_xml()
            input_hash = build_state_hash(snapshot)
        except Exception:  # noqa: BLE001 - no write has started.
            return {"ok": False, "errorCode": "jewel_equip_snapshot_failed"}
        if expected_state_hash is not None and input_hash != expected_state_hash:
            return {"ok": False, "errorCode": "build_state_conflict", "actualStateHash": input_hash}
        sockets = engine.list_jewel_sockets().get("sockets") or []
        target = next((row for row in sockets if row.get("socket") == socket), None)
        if not target or target.get("allocated") is not True:
            return {"ok": False, "errorCode": "jewel_socket_not_allocated"}
        try:
            result = engine.equip_jewel(raw, socket=socket)
            if (
                not isinstance(result, dict)
                or not result.get("ok")
                or result.get("socket") != socket
            ):
                return _rollback_failure(engine, snapshot, input_hash, "jewel_equip_failed")
            verified = _verify_actual_item(
                engine,
                raw=raw,
                requested_structure=structure,
                slot=slot,
                craft_receipt_ref=craft_receipt_ref,
            )
            if not verified.get("ok"):
                return _rollback_failure(
                    engine,
                    snapshot,
                    input_hash,
                    str(verified.get("errorCode") or "jewel_readback_mismatch"),
                )
            return {
                **result,
                "slot": slot,
                "itemLegality": verified["itemLegality"],
                "readbackVerified": True,
                "socketOperation": "existing_allocated_socket",
                "inputStateHash": input_hash,
                "outputStateHash": build_state_hash(engine.get_xml()),
            }
        except Exception:  # noqa: BLE001 - restore before exposing any failure.
            return _rollback_failure(engine, snapshot, input_hash, "jewel_equip_failed")


def _verify_actual_item(
    engine: Any,
    *,
    raw: str,
    requested_structure: dict[str, Any],
    slot: str,
    craft_receipt_ref: str | None,
) -> dict[str, Any]:
    socket_ids = None
    if slot.startswith("Jewel "):
        socket_ids = [
            row["socket"]
            for row in engine.list_jewel_sockets().get("sockets") or []
            if row.get("allocated") is True
        ]
    actual = completeness.equipped_item_text(
        engine.get_xml(), slot, allocated_jewel_socket_ids=socket_ids
    )
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
    if slot.startswith("Jewel "):
        gear = completeness.equipped_item_metadata(
            engine.get_xml(), require_special_provenance=True, allocated_jewel_socket_ids=socket_ids
        )
        if "jewel_limit_exceeded" in (
            gear.get(slot, {}).get("affixLegality", {}).get("issues") or []
        ):
            return {"ok": False, "errorCode": "jewel_limit_exceeded"}
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
    requested_structure = itemparse.semantic_item_structure(requested_text)
    actual_structure = itemparse.semantic_item_structure(actual_text)
    return bool(
        requested.get("ok")
        and actual.get("ok")
        and str(requested.get("rarity") or "").casefold() == "unique"
        and str(actual.get("rarity") or "").casefold() == "unique"
        and str(requested.get("name") or "").strip().casefold()
        == str(actual.get("name") or "").strip().casefold()
        and str(requested.get("base") or "").strip().casefold()
        == str(actual.get("base") or "").strip().casefold()
        and all(
            requested_structure.get(key) == actual_structure.get(key)
            for key in ("corrupted", "runeSockets", "runeNames")
        )
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
