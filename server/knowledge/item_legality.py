"""Single source-aware legality authority for generated and imported PoB item text."""

from __future__ import annotations

from typing import Any

from server.runtime import craft_receipts

from . import itemparse


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
