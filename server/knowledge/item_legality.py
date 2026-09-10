"""Single source-aware legality authority for generated and imported PoB item text."""

from __future__ import annotations

from typing import Any

from server.runtime import craft_receipts

from . import db, itemparse


def audit_jewel_input(
    item_text: str,
    *,
    craft_receipt_ref: str | None = None,
    slot: str | None = None,
    require_recognized_affixes: bool = False,
) -> dict[str, Any]:
    """Validate jewel identity and provenance before equipment or numeric probes.

    Unrecognized ordinary affixes are an evidence gap, not proof of illegality. Numeric probes
    cannot silently omit them; equipment retains the shared audit's existing diagnostic policy.
    """
    structure = itemparse.semantic_item_structure(item_text)
    if craft_receipt_ref is None and (
        structure.get("corrupted")
        or structure.get("runeNames")
        or any(
            value.get("kind") == "rune"
            for value in structure.get("effects") or []
            if isinstance(value, dict)
        )
    ):
        return {"ok": False, "errorCode": "special_source_provenance_required"}
    parsed = itemparse.parse_item(item_text)
    base = db.get_item(str(parsed.get("base") or ""))
    if not base or "jewel" not in (base.get("tags") or []):
        return {"ok": False, "errorCode": "item_is_not_jewel"}
    if (
        str(parsed.get("rarity") or "").casefold() in {"rare", "magic"}
        and parsed.get("itemLevel") is None
    ):
        return {"ok": False, "errorCode": "jewel_item_level_missing"}
    audit = audit_item(
        item_text, slot=slot, craft_receipt_ref=craft_receipt_ref, require_special_provenance=True
    )
    if not audit.get("ok"):
        return {"ok": False, "errorCode": "item_legality_check_failed", "itemLegality": audit}
    if require_recognized_affixes and audit.get("unrecognizedAffixCount"):
        return {
            "ok": False,
            "errorCode": "candidate_jewel_unrecognized_affixes",
            "reasonClass": "evidence_gap",
            "verificationRequired": True,
            "itemLegality": audit,
        }
    return {"ok": True, "itemStructure": structure, "itemLegality": audit}


def audit_item(
    item_text: str,
    *,
    craft_receipt_ref: str | None = None,
    slot: str | None = None,
    require_special_provenance: bool = False,
    runtime_context: dict[str, Any] | None = None,
    prepared_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve trusted provenance, then run the shared deterministic item audit."""

    provenance = prepared_receipt
    resolution_error: str | None = None
    if provenance is None:
        resolution = craft_receipts.resolve_receipt(
            item_text,
            receipt_ref=craft_receipt_ref,
            slot=slot,
            runtime_context=runtime_context,
        )
        if resolution.get("status") == "verified":
            provenance = resolution.get("receipt")
        elif craft_receipt_ref is not None:
            resolution_error = str(resolution.get("errorCode") or "craft_receipt_not_trusted")

    audit = itemparse.audit_item_legality(
        item_text,
        trusted_provenance=provenance,
        require_special_provenance=require_special_provenance,
    )
    if resolution_error is not None:
        issues = [resolution_error, *[str(value) for value in audit.get("issues") or []]]
        audit["issues"] = list(dict.fromkeys(issues))
        audit["ok"] = False
        audit["provenanceStatus"] = "rejected"
        audit["requestedCraftReceiptRef"] = craft_receipt_ref
    return audit
