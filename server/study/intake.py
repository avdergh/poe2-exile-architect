"""Freeze an explicitly selected single input, without Research queues or intake ledgers."""

from __future__ import annotations

from pathlib import Path
import base64
import re
from urllib.parse import urlparse
import zlib
import xml.etree.ElementTree as ET

from server.compute.pob_code import fetch_code
from server.compute.pob_xml_input import parse_pob_xml
from server.knowledge.research_packet import active_set_identity
from .storage import StudyError

MAX_SOURCE_BYTES = 8_000_000


def decode_input(source: str) -> str:
    text = source.strip()
    if len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise StudyError("study_source_too_large")
    if not text.startswith("<"):
        encoded = re.sub(r"\s+", "", text).replace("-", "+").replace("_", "/")
        try:
            data = base64.b64decode(encoded + "=" * (-len(encoded) % 4), validate=True)
            decoder = zlib.decompressobj()
            raw = decoder.decompress(data, MAX_SOURCE_BYTES + 1)
            if len(raw) > MAX_SOURCE_BYTES or not decoder.eof or decoder.unused_data:
                raise ValueError
            text = raw.decode("utf-8")
        except (ValueError, zlib.error) as exc:
            raise StudyError("study_source_invalid_code") from exc
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise StudyError("study_source_unsupported_xml")
    try:
        root = parse_pob_xml(text)
    except (ValueError, ET.ParseError) as exc:
        raise StudyError("study_source_invalid_xml") from exc
    if root.tag not in {"PathOfBuilding", "PathOfBuilding2"} or root.find("Build") is None:
        raise StudyError("study_source_not_pob")
    identity = active_set_identity(root)
    if identity["issues"]:
        raise StudyError("study_source_active_sets_invalid")
    return text


def read_source(source_file: str | None, source_url: str | None) -> tuple[str, str]:
    if bool(source_file) == bool(source_url):
        raise StudyError("study_requires_one_source")
    if source_file:
        path = Path(source_file)
        if not path.is_absolute() or not path.is_file():
            raise StudyError("study_source_requires_absolute_file")
        if path.stat().st_size > MAX_SOURCE_BYTES:
            raise StudyError("study_source_too_large")
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise StudyError("study_source_unreadable") from exc
        return decode_input(text), "local_file"
    parsed = urlparse(source_url or "")
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"pobb.in", "pastebin.com"}
        or parsed.username
        or parsed.password
        or parsed.port
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"/(?:raw/)?[A-Za-z0-9_-]+/?", parsed.path)
    ):
        raise StudyError("study_link_requires_pob_export")
    try:
        text = fetch_code(source_url or "")
    except Exception as exc:
        raise StudyError("study_source_fetch_failed") from exc
    return decode_input(text), "pob_link"
