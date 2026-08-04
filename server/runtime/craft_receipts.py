"""Raw-free, content-addressed receipts for PoB-backed special item crafting sources."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from server import paths
from server.knowledge import itemparse
from server.live import update as live_update


SCHEMA_VERSION = 1
_REF = re.compile(r"craft-legality:([a-f0-9]{64})")
_VERSION_FIELDS = (
    "dataVersion",
    "pobCommit",
    "pobVersion",
    "passiveTreeVersion",
    "engineSha256",
)


def option_fingerprint(value: Any) -> str:
    """Hash one PoB-owned crafting option without persisting its raw display text."""

    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def current_runtime_context(engine_info: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = live_update.installed_meta()
    info = engine_info if isinstance(engine_info, dict) else {}
    return {
        "dataVersion": str(live_update.installed_version() or "unknown"),
        "pobCommit": _optional_text(metadata.get("pob_commit")),
        "pobVersion": _optional_text(metadata.get("pob_version")),
        "passiveTreeVersion": _optional_text(
            info.get("treeVersion") or metadata.get("passive_tree")
        ),
        "engineSha256": _optional_text(metadata.get("engine_sha256")),
    }


def prepare_receipt(
    item_text: str,
    *,
    canonical_item_text: str | None = None,
    slot: str,
    item_level: int,
    perfect_essences: list[dict[str, Any]] | None = None,
    runes: list[dict[str, Any]] | None = None,
    corruption: dict[str, Any] | None = None,
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build but do not persist one receipt from already-selected PoB crafting options."""

    structure = itemparse.semantic_item_structure(item_text)
    canonical_structure = (
        itemparse.semantic_item_structure(canonical_item_text)
        if canonical_item_text is not None
        else structure
    )
    accepted_fingerprints = sorted(
        {
            str(structure["itemFingerprint"]),
            str(canonical_structure["itemFingerprint"]),
        }
    )
    sources = {
        "perfectEssences": [
            _essence_source(entry) for entry in (perfect_essences or []) if isinstance(entry, dict)
        ],
        "runes": [_rune_source(entry) for entry in (runes or []) if isinstance(entry, dict)],
        "corruption": (_corruption_source(corruption) if isinstance(corruption, dict) else None),
        "canonicalRuneLineFingerprints": sorted(
            str(entry.get("lineFingerprint") or "")
            for entry in (canonical_structure.get("effects") or [])
            if isinstance(entry, dict) and entry.get("kind") in {"rune", "enchant"}
        ),
    }
    body = {
        "schemaVersion": SCHEMA_VERSION,
        "itemFingerprint": structure["itemFingerprint"],
        "acceptedItemFingerprints": accepted_fingerprints,
        "base": str(structure.get("base") or "").strip(),
        "slotFamily": slot_family(slot),
        "itemLevel": int(item_level),
        "runtimeVersion": dict(runtime_context or current_runtime_context()),
        "sources": sources,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "containsRawItem": False,
    }
    digest = hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()
    return {**body, "receiptRef": f"craft-legality:{digest}"}


def persist_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    error = _receipt_error(receipt)
    if error is not None:
        return {"status": "rejected", "errorCode": error}
    receipt_ref = str(receipt["receiptRef"])
    match = _REF.fullmatch(receipt_ref)
    assert match is not None
    root = paths.craft_legality_receipts_dir()
    receipt_path = root / "receipts" / f"{match.group(1)}.json"
    if receipt_path.exists():
        existing = _read_json(receipt_path)
        if existing != receipt:
            return {"status": "rejected", "errorCode": "craft_receipt_conflict"}
    elif not _write_json_atomic(receipt_path, receipt):
        return {"status": "rejected", "errorCode": "craft_receipt_write_failed"}

    item_fingerprint = str(receipt["itemFingerprint"])
    for accepted_fingerprint in receipt["acceptedItemFingerprints"]:
        index_token = str(accepted_fingerprint).removeprefix("sha256:")
        index_payload = {
            "schemaVersion": SCHEMA_VERSION,
            "itemFingerprint": accepted_fingerprint,
            "receiptRef": receipt_ref,
            "containsRawItem": False,
        }
        if not _write_json_atomic(root / "by-item" / f"{index_token}.json", index_payload):
            return {"status": "rejected", "errorCode": "craft_receipt_index_write_failed"}
    return {
        "status": "recorded",
        "craftReceiptRef": receipt_ref,
        "itemFingerprint": item_fingerprint,
    }


def resolve_receipt(
    item_text: str,
    *,
    receipt_ref: str | None = None,
    slot: str | None = None,
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    structure = itemparse.semantic_item_structure(item_text)
    resolved_ref = receipt_ref
    if resolved_ref is None:
        token = str(structure["itemFingerprint"]).removeprefix("sha256:")
        index = _read_json(paths.craft_legality_receipts_dir() / "by-item" / f"{token}.json")
        if isinstance(index, dict) and index.get("itemFingerprint") == structure["itemFingerprint"]:
            resolved_ref = (
                str(index.get("receiptRef")) if isinstance(index.get("receiptRef"), str) else None
            )
    if resolved_ref is None:
        return {
            "status": "missing",
            "errorCode": "craft_receipt_not_found",
            "itemFingerprint": structure["itemFingerprint"],
        }
    receipt = read_receipt(resolved_ref)
    if receipt is None:
        return {"status": "rejected", "errorCode": "craft_receipt_not_trusted"}
    accepted_fingerprints = set(receipt.get("acceptedItemFingerprints") or [])
    if structure["itemFingerprint"] not in accepted_fingerprints:
        return {"status": "rejected", "errorCode": "craft_receipt_item_mismatch"}
    if str(receipt.get("base") or "").casefold() != str(structure.get("base") or "").casefold():
        return {"status": "rejected", "errorCode": "craft_receipt_base_mismatch"}
    if receipt.get("itemLevel") != structure.get("itemLevel"):
        return {"status": "rejected", "errorCode": "craft_receipt_item_level_mismatch"}
    if slot is not None and receipt.get("slotFamily") != slot_family(slot):
        return {"status": "rejected", "errorCode": "craft_receipt_slot_mismatch"}
    current = dict(runtime_context or current_runtime_context())
    if not _version_matches(receipt.get("runtimeVersion"), current):
        return {"status": "rejected", "errorCode": "craft_receipt_version_mismatch"}
    return {"status": "verified", "receipt": receipt}


def read_receipt(receipt_ref: str) -> dict[str, Any] | None:
    match = _REF.fullmatch(str(receipt_ref or ""))
    if match is None:
        return None
    payload = _read_json(
        paths.craft_legality_receipts_dir() / "receipts" / f"{match.group(1)}.json"
    )
    if not isinstance(payload, dict) or _receipt_error(payload) is not None:
        return None
    return payload


def slot_family(slot: str) -> str:
    value = re.sub(r"\s+", " ", str(slot or "")).strip()
    return re.sub(r"\s+[12]$", "", value)


def _essence_source(entry: dict[str, Any]) -> dict[str, Any]:
    line = str(entry.get("line") or "")
    affix_type = str(entry.get("affixType") or "").casefold()
    if not line or affix_type not in {"prefix", "suffix"}:
        raise ValueError("invalid perfect essence source")
    required = entry.get("requiredLevel")
    return {
        "name": str(entry.get("name") or "").strip(),
        "lineFingerprint": itemparse.line_fingerprint(line),
        "optionFingerprint": option_fingerprint(entry.get("option") or {}),
        "affixType": affix_type,
        "group": str(entry.get("group") or "").strip(),
        "requiredLevel": int(required) if isinstance(required, int) else None,
    }


def _rune_source(entry: dict[str, Any]) -> dict[str, Any]:
    name = str(entry.get("name") or "").strip()
    lines = [str(line) for line in (entry.get("lines") or []) if str(line).strip()]
    if not name or not lines:
        raise ValueError("invalid rune source")
    return {
        "name": name,
        "lineFingerprints": [itemparse.line_fingerprint(line) for line in lines],
        "optionFingerprint": option_fingerprint(entry.get("option") or {}),
    }


def _corruption_source(entry: dict[str, Any]) -> dict[str, Any]:
    line = str(entry.get("line") or "")
    if not line:
        raise ValueError("invalid corruption source")
    return {
        "lineFingerprint": itemparse.line_fingerprint(line),
        "optionFingerprint": option_fingerprint(entry.get("option") or {}),
    }


def _receipt_error(receipt: dict[str, Any]) -> str | None:
    if not isinstance(receipt, dict) or receipt.get("schemaVersion") != SCHEMA_VERSION:
        return "craft_receipt_schema_invalid"
    receipt_ref = receipt.get("receiptRef")
    if not isinstance(receipt_ref, str) or _REF.fullmatch(receipt_ref) is None:
        return "craft_receipt_ref_invalid"
    if receipt.get("containsRawItem") is not False:
        return "craft_receipt_contains_raw_item"
    item_fingerprint = receipt.get("itemFingerprint")
    if not isinstance(item_fingerprint, str) or not re.fullmatch(
        r"sha256:[a-f0-9]{64}", item_fingerprint
    ):
        return "craft_receipt_item_fingerprint_invalid"
    accepted_fingerprints = receipt.get("acceptedItemFingerprints")
    if (
        not isinstance(accepted_fingerprints, list)
        or item_fingerprint not in accepted_fingerprints
        or not accepted_fingerprints
        or any(
            not isinstance(value, str) or re.fullmatch(r"sha256:[a-f0-9]{64}", value) is None
            for value in accepted_fingerprints
        )
    ):
        return "craft_receipt_accepted_fingerprints_invalid"
    if not isinstance(receipt.get("base"), str) or not receipt["base"]:
        return "craft_receipt_base_invalid"
    if not isinstance(receipt.get("slotFamily"), str) or not receipt["slotFamily"]:
        return "craft_receipt_slot_invalid"
    if not isinstance(receipt.get("itemLevel"), int):
        return "craft_receipt_item_level_invalid"
    if not isinstance(receipt.get("runtimeVersion"), dict):
        return "craft_receipt_version_invalid"
    sources = receipt.get("sources")
    if not isinstance(sources, dict):
        return "craft_receipt_sources_invalid"
    body = {key: value for key, value in receipt.items() if key != "receiptRef"}
    expected = "craft-legality:" + hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()
    return None if expected == receipt_ref else "craft_receipt_integrity_failed"


def _version_matches(receipt: Any, current: dict[str, Any]) -> bool:
    if not isinstance(receipt, dict):
        return False
    for key in _VERSION_FIELDS:
        left = _optional_text(receipt.get(key))
        right = _optional_text(current.get(key))
        if left is not None and right is not None and left != right:
            return False
    return True


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text and text.casefold() not in {"unknown", "none"} else None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> bool:
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(path)
    except OSError:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True
