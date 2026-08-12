"""Quarantine-only helpers for building raw-rich payload rows from pobb.in links."""

from __future__ import annotations

from typing import Any
import re

from ..compute import pob_code
from . import pob_xml_meta

_BUILD_ATTR = re.compile(r"<Build\b([^>]*)>", re.IGNORECASE)
_ATTR = re.compile(r'(\w+)="([^"]*)"')


def build_payload_row_from_build_source(
    *,
    source_ref: str,
    build_source: str,
    payload_source: str,
    source_type: str,
    payload_kind: str,
) -> dict[str, Any]:
    """Normalize a supported build source into one quarantine-only payload row."""
    if not isinstance(source_ref, str) or not source_ref.strip():
        return {"ok": False, "error": "source_ref_required"}
    if not isinstance(build_source, str) or not build_source.strip():
        return {"ok": False, "error": "build_source_required"}

    try:
        xml = pob_code.to_xml(build_source)
    except pob_code.PobCodeError as exc:
        return {"ok": False, "error": "build_import_failed", "detail": str(exc)}

    build_attrs = _build_attributes(xml)
    main_skill = _main_skill(xml)
    payload_row = {
        "payloadSource": payload_source,
        "sourceType": source_type,
        "sourceRef": source_ref.strip(),
        "class": build_attrs.get("className"),
        "ascendancy": build_attrs.get("ascendClassName"),
        "mainSkill": main_skill,
        "pobModelability": "partial",
        "sourcePayload": {"kind": payload_kind, "sourceRef": source_ref.strip()},
        "rawXml": xml,
    }
    if not pob_code.is_link(build_source) and "<PathOfBuilding" not in build_source:
        payload_row["rawImportCode"] = build_source.strip()
    return {"ok": True, "payloadRow": payload_row}


def build_payload_row_from_pobb(url: str) -> dict[str, Any]:
    """Fetch a real pobb.in link and build a quarantine-only raw payload row."""
    if not isinstance(url, str) or not url.strip():
        return {"ok": False, "error": "pobb_url_required"}

    result = build_payload_row_from_build_source(
        source_ref=url.strip(),
        build_source=url.strip(),
        payload_source="pobb_in",
        source_type="pobb_in",
        payload_kind="pobb_in_raw_import",
    )
    if result.get("ok"):
        return result
    return {"ok": False, "error": "pobb_import_failed", "detail": result.get("detail")}


def _build_attributes(xml: str) -> dict[str, str]:
    match = _BUILD_ATTR.search(xml)
    if not match:
        return {}
    attrs = {}
    for key, value in _ATTR.findall(match.group(1)):
        attrs[key] = value
    return attrs


def _main_skill(xml: str) -> str | None:
    return pob_xml_meta.main_skill_from_pob_xml(xml)
