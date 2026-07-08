"""Quarantine-only helpers for extracting raw import material from poe.ninja build pages."""

from __future__ import annotations

from typing import Any
import hashlib
import html
import re

from ..compute import pob_code

_TITLE = re.compile(r"<title>Builds - .*? - Path of Exile 2 - poe\.ninja</title>", re.IGNORECASE)
_Pob2 = re.compile(r"pob2://poeninja/overview/code\?[^\"'\s<>]+", re.IGNORECASE)
_INPUT_VALUE = re.compile(
    r'aria-label="Import code for Path of Building"[^>]*value="([^"]+)"', re.IGNORECASE
)
_INPUT_TAG = re.compile(
    r'<input[^>]*aria-label="Import code for Path of Building"[^>]*>', re.IGNORECASE | re.DOTALL
)
_VALUE_ATTR = re.compile(r'value="([^"]+)"', re.IGNORECASE)
_SNAPSHOT_INPUT_VALUE = re.compile(
    r'aria-label=(?:\\")?Import code for Path of Building(?:\\")?.*?value=(?:\\")?([^\\"]+)(?:\\")?|'
    r'aria-label="Import code for Path of Building".*?value="([^"]+)"',
    re.IGNORECASE,
)
_SNAPSHOT_POB2 = re.compile(r"pob2://poeninja/overview/code\?[^\s\"']+", re.IGNORECASE)
_SNAPSHOT_PROFILE = re.compile(
    r'heading\s+(?:"|\\")?([^"\\\n]+)(?:"|\\")?\s+\[level=1\][\s\S]{0,200}?Level\s+([0-9]+)\s+([^\n]+)',
    re.IGNORECASE,
)


def extract_import_code_from_rendered_html(page_html: str) -> dict[str, Any]:
    """Extract a PoB import code from rendered poe.ninja build-page HTML."""
    if not isinstance(page_html, str) or not page_html.strip():
        return {"ok": False, "error": "page_html_required"}
    if not _TITLE.search(page_html):
        return {"ok": False, "error": "not_a_poe_ninja_build_page"}

    match = _INPUT_VALUE.search(page_html)
    code = ""
    if match:
        code = html.unescape((match.group(1) or match.group(2) or "")).strip()
    if not code:
        tag_match = _INPUT_TAG.search(page_html)
        if tag_match:
            value_match = _VALUE_ATTR.search(tag_match.group(0))
            if value_match:
                code = html.unescape(value_match.group(1)).strip()
    if not code:
        return {"ok": False, "error": "import_code_not_found"}
    if not _is_supported_import_code_shape(code):
        return {"ok": False, "error": "import_code_not_found"}

    deep_link = _safe_deep_link(_Pob2.search(page_html))
    return {
        "ok": True,
        "importCode": code,
        "pob2DeepLinkRef": _safe_ref(deep_link, prefix="pob2-hash") if deep_link else None,
    }


def extract_import_code_from_dom_snapshot(snapshot_text: str) -> dict[str, Any]:
    """Extract a PoB import code from the browser DOM snapshot text form."""
    if not isinstance(snapshot_text, str) or not snapshot_text.strip():
        return {"ok": False, "error": "snapshot_text_required"}

    match = _SNAPSHOT_INPUT_VALUE.search(snapshot_text)
    if not match:
        return {"ok": False, "error": "import_code_not_found"}

    code = html.unescape((match.group(1) or match.group(2) or "")).strip()
    if not _is_supported_import_code_shape(code):
        return {"ok": False, "error": "import_code_not_found"}

    deep_link = _safe_deep_link(_SNAPSHOT_POB2.search(snapshot_text))
    profile_match = _SNAPSHOT_PROFILE.search(snapshot_text)
    profile = None
    if profile_match:
        character_name = profile_match.group(1)
        profile = {
            "characterRef": _safe_ref(character_name, prefix="character-hash"),
            "level": int(profile_match.group(2)),
            "ascendancyOrClass": profile_match.group(3).strip(),
        }
    return {
        "ok": True,
        "importCode": code,
        "pob2DeepLinkRef": _safe_ref(deep_link, prefix="pob2-hash") if deep_link else None,
        "profileSummary": profile,
    }


def build_payload_row_from_import_code(
    *,
    source_ref: str,
    import_code: str,
    quarantine_pob2_deep_link: str | None = None,
) -> dict[str, Any]:
    """Convert an extracted poe.ninja import code into a raw payload row."""
    if not isinstance(source_ref, str) or not source_ref.strip():
        return {"ok": False, "error": "source_ref_required"}
    if not isinstance(import_code, str) or not import_code.strip():
        return {"ok": False, "error": "import_code_required"}

    try:
        xml = pob_code.to_xml(import_code)
    except pob_code.PobCodeError as exc:
        return {"ok": False, "error": "ninja_import_failed", "detail": str(exc)}

    return {
        "ok": True,
        "payloadRow": {
            "payloadSource": "poe_ninja_page_import_code",
            "sourceType": "poe_ninja",
            "sourceRef": source_ref.strip(),
            "sourceHashRef": _safe_ref(source_ref.strip(), prefix="source-hash"),
            "pobModelability": "partial",
            "sourcePayload": {
                "kind": "poe_ninja_import_code",
                "pob2DeepLinkRef": _safe_ref(
                    quarantine_pob2_deep_link,
                    prefix="pob2-hash",
                )
                if quarantine_pob2_deep_link
                else None,
                "quarantinePob2DeepLink": quarantine_pob2_deep_link,
            },
            "rawImportCode": import_code.strip(),
            "rawXml": xml,
        },
    }


def _is_supported_import_code_shape(code: str) -> bool:
    """Accept historical fixtures plus real PoB codes with non-eNrt deflate headers."""
    text = str(code or "").strip()
    if text.startswith("eNrt"):
        return True
    try:
        pob_code.to_xml(text)
    except pob_code.PobCodeError:
        return False
    return True


def _safe_deep_link(match: re.Match[str] | None) -> str | None:
    if match is None:
        return None
    return html.unescape(match.group(0)).strip()


def _safe_ref(value: str | None, *, prefix: str) -> str:
    return f"{prefix}:{hashlib.sha256(str(value or '').encode('utf-8')).hexdigest()[:16]}"
