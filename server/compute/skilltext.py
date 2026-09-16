"""Normalize user-typed skill-gem text into Path of Building's strict paste format.

PoB's socket-group paste parser needs ONE GEM PER LINE in the form ``Name level/quality count``
and silently drops any line it can't match — so a natural inline list like
``Arc 20/20 1 / Lightning Penetration`` (or the spaceless ``Arc/Lightning Penetration``) loses
every support. This module makes the forgiving forms work by (a) splitting the inline separators
people actually type (``/``, `` | ``, ``, ``) onto their own lines — a slash whether or not it has
surrounding spaces, but NEVER the digit/digit ``20/20`` level/quality slash — and (b) optionally
giving bare gem names a caller-selected default plus a trailing instance count.  The Headless PoB
bridge preserves bare names here and applies its pinned-data, character-level-aware default.
"""

from __future__ import annotations

import re

_SEP_SLASH = re.compile(
    r"(?<!\d)/|/(?!\d)"
)  # gem-separator "/" (spaced OR spaceless), but NEVER the digit/digit "20/20" level/quality slash
_SEP_PIPE = re.compile(r"\s*\|\s*")
_SEP_COMMA = re.compile(r"\s*,\s*")
_LQ = re.compile(r"\b\d+/\d+\b")  # a level/quality token
_BARE_NAME = re.compile(r"^[A-Za-z][A-Za-z'. -]*$")  # names may contain a literal hyphen
_HEADER = re.compile(r"^(Label|Slot)\s*:", re.IGNORECASE)


def normalize_skill_text(text: str, *, default_level: int | None = 20) -> str:
    """Return ``text`` reshaped into PoB's one-gem-per-line paste format.

    ``default_level=None`` preserves bare gem names after splitting.  The Headless PoB bridge uses
    that mode so it can choose an active gem level from the pinned gem requirement table and the
    active character level.  The public/default behaviour remains backwards compatible for callers
    that only need text normalization.
    """
    if not text:
        return text
    t = _SEP_SLASH.sub("\n", text)
    t = _SEP_PIPE.sub("\n", t)
    t = _SEP_COMMA.sub("\n", t)
    out: list[str] = []
    for raw in t.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _HEADER.match(line):
            out.append(line)
            continue
        m = _LQ.search(line)
        if m:
            # Has level/quality; ensure a trailing instance count so PoB doesn't drop the line.
            if not re.search(r"\d", line[m.end() :]):
                line = line + "  1"
            out.append(line)
        elif _BARE_NAME.match(line) and default_level is not None:
            # A bare gem name (e.g. "Lightning Penetration") — give it the default L/Q + count.
            out.append(f"{line} {int(default_level)}/20 1")
        else:
            out.append(line)
    return "\n".join(out)


def requested_gem_names(text: str) -> list[str]:
    """Return gem names requested by one normalized socket-group text."""

    names: list[str] = []
    for line in normalize_skill_text(text, default_level=None).splitlines():
        value = line.strip()
        if not value or _HEADER.match(value):
            continue
        value = re.sub(r"\s+\d+/\d+(?:\s+\S+)?\s*$", "", value).strip()
        if value:
            names.append(value)
    return names
