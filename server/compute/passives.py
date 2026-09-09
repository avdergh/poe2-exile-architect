"""Transactional, Agent-selected passive edits using the pinned PoB implementation."""

from __future__ import annotations

from typing import Any, Literal

from . import equipment
from .state import build_state_hash

PassiveAttribute = Literal["Strength", "Dexterity", "Intelligence"]


def mutate_passive(
    engine: Any,
    *,
    node: str | int,
    operation: Literal["allocate", "attribute"],
    attribute: PassiveAttribute | None = None,
    expected_state_hash: str | None = None,
) -> dict[str, Any]:
    """Change one selected node/path, preserving the input on a failed write or readback."""
    with engine.transaction_lock():
        if getattr(engine, equipment._RECOVERY_ATTRIBUTE, False):
            return {
                "ok": False,
                "errorCode": "mutation_batch_recovery_required",
                "recoveryRequired": True,
            }
        try:
            snapshot = engine.get_xml()
            input_hash = build_state_hash(snapshot)
        except Exception:  # noqa: BLE001 - no write has started.
            return {"ok": False, "errorCode": "passive_snapshot_failed"}
        if expected_state_hash is not None and input_hash != expected_state_hash:
            return {"ok": False, "errorCode": "build_state_conflict", "actualStateHash": input_hash}
        try:
            if operation == "attribute":
                result = engine.set_passive_attribute(node, attribute)
            else:
                result = engine.alloc_passive(
                    node, **({"path_attribute": attribute} if attribute else {})
                )
            if not isinstance(result, dict) or not result.get("ok"):
                error = (result or {}).get("errorCode") or "passive_mutation_failed"
                return equipment._rollback_failure(engine, snapshot, input_hash, str(error))
            actual = engine.get_passive(result["node"]["id"])
            if (
                (isinstance(node, int) and actual.get("id") != node)
                or not actual.get("alloc")
                or (operation == "attribute" and actual.get("attribute") != attribute)
            ):
                return equipment._rollback_failure(
                    engine, snapshot, input_hash, "passive_readback_mismatch"
                )
            return {
                **result,
                "node": actual,
                "inputStateHash": input_hash,
                "outputStateHash": build_state_hash(engine.get_xml()),
            }
        except Exception:  # noqa: BLE001 - restore and return safe diagnostics.
            return equipment._rollback_failure(
                engine, snapshot, input_hash, "passive_mutation_failed"
            )
