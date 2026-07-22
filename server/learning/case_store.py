"""Case-bound quarantine for Phase 7 reference build sources."""

from __future__ import annotations

import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from collections.abc import Collection
from typing import Any, Literal
from uuid import UUID, uuid4

from server import paths
from server.knowledge import copy_safety, mature_pobb_payload


SourceMode = Literal["direct", "source_file", "automatic"]
MAX_SOURCE_BYTES = 25 * 1024 * 1024


def quarantine_dir() -> Path:
    return (paths.comparative_learning_dir() / "quarantine").resolve()


def intake_reference_source(
    *,
    source: str,
    source_mode: SourceMode,
    source_ref: str = "",
    reject_source_hashes: Collection[str] = (),
) -> dict[str, Any]:
    """Normalize a source into a private case directory and return safe metadata only."""

    if source_mode not in {"direct", "source_file", "automatic"}:
        return _rejected("invalid_source_mode")
    if not isinstance(source, str) or not source.strip():
        return _rejected("source_required")
    if len(source.encode("utf-8", errors="ignore")) > MAX_SOURCE_BYTES:
        return _rejected("source_too_large")

    build_source = source.strip()
    source_type = "pob_source"
    payload_source = "explicit_pob_source"
    if source_mode == "source_file":
        try:
            file_path = Path(build_source).expanduser().resolve()
        except (OSError, ValueError):
            return _rejected("source_file_invalid")
        if not file_path.is_file():
            return _rejected("source_file_not_found")
        try:
            if file_path.stat().st_size > MAX_SOURCE_BYTES:
                return _rejected("source_too_large")
        except OSError:
            return _rejected("source_file_read_failed")
        try:
            build_source = file_path.read_text(encoding="utf-8").strip()
        except (UnicodeDecodeError, OSError):
            return _rejected("source_file_read_failed")
        source_type = "local_source_file"
        payload_source = "local_source_file"
        safe_ref = f"source-file:{hashlib.sha256(str(file_path).encode('utf-8')).hexdigest()[:16]}"
    elif source_mode == "automatic":
        source_type = "poe_ninja"
        payload_source = "poe_ninja_collector"
        safe_ref = _safe_source_ref(source_ref or "automatic-collector")
    else:
        source_type = "pob_link_or_code"
        payload_source = "explicit_pob_source"
        safe_ref = _safe_source_ref(source_ref or source)

    if "PathOfBuilding" in build_source and "<" in build_source[:200]:
        row = {
            "payloadSource": payload_source,
            "sourceType": source_type,
            "sourceRef": safe_ref,
            "pobModelability": "partial",
            "sourcePayload": {
                "kind": f"phase7_{source_mode}_reference",
                "sourceRef": safe_ref,
            },
            "rawXml": build_source,
        }
    else:
        normalized = mature_pobb_payload.build_payload_row_from_build_source(
            source_ref=safe_ref,
            build_source=build_source,
            payload_source=payload_source,
            source_type=source_type,
            payload_kind=f"phase7_{source_mode}_reference",
        )
        if not normalized.get("ok"):
            return _rejected(str(normalized.get("error") or "build_import_failed"))
        row = normalized["payloadRow"]
    xml = str(row.get("rawXml") or "")
    if len(xml.encode("utf-8", errors="ignore")) > MAX_SOURCE_BYTES:
        return _rejected("source_too_large")
    parsed = _safe_xml_metadata(xml)
    if parsed is None:
        return _rejected("reference_xml_invalid")
    source_hash = hashlib.sha256(xml.encode("utf-8")).hexdigest()
    if source_hash in reject_source_hashes:
        return _rejected("duplicate_reference_source")
    case_id = str(uuid4())
    root = quarantine_dir()
    final_dir = root / case_id
    temp_dir = root / f".{case_id}.{uuid4().hex}.tmp"
    safe_manifest = {
        "schemaVersion": 1,
        "caseId": case_id,
        "sourceMode": source_mode,
        "sourceType": source_type,
        "safeSourceRef": safe_ref,
        "sourceHash": source_hash,
        "discoveredLevel": parsed["level"],
        "localOnly": True,
        "quarantineOnly": True,
        "containsRawMaterial": False,
    }
    quarantine_payload = {
        "schemaVersion": 1,
        "caseId": case_id,
        "payloadRow": row,
        "sourceHash": source_hash,
        "quarantineOnly": True,
    }
    try:
        root.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir()
        (temp_dir / "manifest.json").write_text(
            json.dumps(safe_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (temp_dir / "source.json").write_text(
            json.dumps(quarantine_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp_dir.replace(final_dir)
    except OSError:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return _rejected("quarantine_write_failed")
    return {"status": "intaked", "case": safe_manifest, "containsRawMaterial": False}


def safe_case_manifest(case_id: str) -> dict[str, Any] | None:
    case_dir = _case_dir(case_id)
    if case_dir is None:
        return None
    try:
        payload = json.loads((case_dir / "manifest.json").read_text(encoding="utf-8"))
    except (UnicodeDecodeError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("caseId") != case_id:
        return None
    if payload.get("containsRawMaterial") is not False:
        return None
    return payload


def read_reference_xml(case_id: str) -> str | None:
    """Internal-only raw read used to load a claimed reference into Headless PoB."""

    case_dir = _case_dir(case_id)
    manifest = safe_case_manifest(case_id)
    if case_dir is None or manifest is None:
        return None
    try:
        payload = json.loads((case_dir / "source.json").read_text(encoding="utf-8"))
        row = payload.get("payloadRow") if isinstance(payload, dict) else None
        xml = row.get("rawXml") if isinstance(row, dict) else None
    except (UnicodeDecodeError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(xml, str) or _safe_xml_metadata(xml) is None:
        return None
    if hashlib.sha256(xml.encode("utf-8")).hexdigest() != manifest.get("sourceHash"):
        return None
    return xml


def _case_dir(case_id: str) -> Path | None:
    try:
        canonical = str(UUID(case_id))
    except (AttributeError, TypeError, ValueError):
        return None
    if canonical != case_id:
        return None
    root = quarantine_dir()
    candidate = (root / canonical).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_dir() else None


def _safe_xml_metadata(xml: str) -> dict[str, Any] | None:
    try:
        root = ET.fromstring(xml)
    except (ET.ParseError, TypeError):
        return None
    if root.tag not in {"PathOfBuilding", "PathOfBuilding2"}:
        return None
    build = root.find("Build")
    if build is None:
        return None
    try:
        level = int(build.attrib.get("level") or "0")
    except ValueError:
        return None
    if not 1 <= level <= 100:
        return None
    return {"level": level}


def _safe_source_ref(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith(("http://", "https://")):
        return copy_safety.safe_url_ref(text)
    return f"source-hash:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"


def _rejected(error_code: str) -> dict[str, Any]:
    return {
        "status": "rejected",
        "errorCode": error_code,
        "containsRawMaterial": False,
    }
