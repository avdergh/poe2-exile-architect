"""Read PoB XML inputs using the pinned Lua decoder's value semantics.

``runtime/lua/xml.lua`` preserves literal attribute whitespace and decodes only five
named entities; numeric and unknown entities become empty strings. ElementTree alone
normalizes whitespace and interprets numeric references, so it cannot bind PoB inputs.
This adapter makes a private parsing projection only. Never serialize it back to PoB.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET


XML_INPUT_SEMANTICS_VERSION = "pob_xml_input_v1"
_ENTITIES = {"lt": "<", "gt": ">", "amp": "&", "apos": "'", "quot": '"'}
_ENTITY = re.compile(r"&(.*?);", re.DOTALL)
_TOKEN = re.compile(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>|<[^>]*>", re.DOTALL)
_START = re.compile(r"<([A-Za-z0-9:]+)(.*?)(/?)>\Z", re.DOTALL)
_ATTRIBUTE = re.compile(r'''\s+([A-Za-z0-9]+)=(["'])(.*?)\2''', re.DOTALL)


def _decode_content(value: str) -> str:
    # Lua gsub performs one pass: &amp;#10; remains literal &#10;, not a newline.
    return _ENTITY.sub(lambda match: _ENTITIES.get(match.group(1), ""), value)


def _escape_for_et(value: str, *, attribute: bool = False) -> str:
    escaped = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # These references are generated after Lua decoding solely for the ET projection.
    escaped = escaped.replace("\r", "&#13;")
    if attribute:
        escaped = escaped.replace('"', "&quot;").replace("\n", "&#10;").replace("\t", "&#9;")
    return escaped


def _project_start_tag(token: str) -> str:
    match = _START.fullmatch(token)
    if match is None:
        raise ET.ParseError("unsupported PoB XML declaration or element")
    tag, attributes, closing = match.groups()
    projected: list[str] = []
    offset = 0
    seen: set[str] = set()
    while attributes[offset:].strip():
        attribute = _ATTRIBUTE.match(attributes, offset)
        if attribute is None:
            raise ET.ParseError("unsupported PoB XML attribute syntax")
        key, _quote, raw_value = attribute.groups()
        if key in seen or "<" in raw_value or ">" in raw_value:
            raise ET.ParseError("ambiguous PoB XML attribute")
        seen.add(key)
        projected.append(f' {key}="{_escape_for_et(_decode_content(raw_value), attribute=True)}"')
        offset = attribute.end()
    return f"<{tag}{''.join(projected)}{closing}>"


def parse_pob_xml(xml: str) -> ET.Element:
    """Return a read-only XML tree with PoB's unnormalized input values.

    Structural validation remains fail-closed. DTDs, duplicate attributes and syntax the
    Lua attribute reader cannot unambiguously recognize are not accepted as evidence.
    """
    pieces: list[str] = []
    offset = 0
    for match in _TOKEN.finditer(xml):
        pieces.append(_escape_for_et(_decode_content(xml[offset:match.start()])))
        token = match.group()
        if token.startswith("<!--"):
            pass  # Lua strips comments before parsing, including their entity contents.
        elif token.startswith("<![CDATA["):
            pieces.append(_escape_for_et(token[9:-3]))
        elif token.startswith("<?") or token.startswith("</"):
            pieces.append(token)
        else:
            pieces.append(_project_start_tag(token))
        offset = match.end()
    pieces.append(_escape_for_et(_decode_content(xml[offset:])))
    return ET.fromstring("".join(pieces))


def requires_preserved_input_semantics(xml: str) -> bool:
    """Identify old ET-based readbacks that must be recomputed, without relabelling them."""
    current = parse_pob_xml(xml)
    try:
        legacy = ET.fromstring(xml)
    except ET.ParseError:
        return True
    return ET.tostring(current) != ET.tostring(legacy)
