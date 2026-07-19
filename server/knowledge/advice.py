"""Curated PoE2 build-optimization advice (knowledge layer, offline).

``server/BUILD_ADVICE.md`` contains planning heuristics rather than versioned mechanical
authority. It is parsed into H2 sections so ``build_advice`` can return targeted slices instead
of dumping the whole document.
"""

from __future__ import annotations

import re
from pathlib import Path

# server/knowledge/advice.py -> server/BUILD_ADVICE.md
_DOC = Path(__file__).resolve().parents[1] / "BUILD_ADVICE.md"
_AUTHORITY_NOTICE = (
    "This document contains planning heuristics, not versioned mechanical authority. "
    "For patch-sensitive facts, the current pinned PoB data, physical graph, and current corpus "
    "take precedence."
)


def _load() -> str:
    try:
        return _DOC.read_text(encoding="utf-8")
    except OSError:
        return ""


def _sections() -> dict[str, str]:
    """Map each level-2 section title to its body (heading line included)."""
    out: dict[str, str] = {}
    for part in re.split(r"(?m)^## ", _load())[1:]:
        title = part.splitlines()[0].strip()
        # drop the trailing horizontal rule that separates sections in the source
        body = re.sub(r"\n+---\s*$", "", ("## " + part).strip()).strip()
        out[title] = body
    return out


def topics() -> list[str]:
    return list(_sections().keys())


def advise(topic: str = "") -> dict[str, object]:
    """Return the framing + topic list (no topic) or a matching section (fuzzy)."""
    secs = _sections()
    titles = list(secs.keys())
    if not titles:
        return {"error": "build advice document unavailable", "authority": _AUTHORITY_NOTICE}
    if not topic.strip():
        intro = _load().split("\n## ", 1)[0].strip()
        return {"intro": intro, "topics": titles, "authority": _AUTHORITY_NOTICE}
    t = topic.strip().lower()
    # prefer a title match, then fall back to a keyword hit in the body
    for title, body in secs.items():
        if t in title.lower() or title.lower() in t:
            return {
                "topic": title,
                "text": body,
                "topics": titles,
                "authority": _AUTHORITY_NOTICE,
            }
    for title, body in secs.items():
        if t in body.lower():
            return {
                "topic": title,
                "text": body,
                "topics": titles,
                "authority": _AUTHORITY_NOTICE,
            }
    return {
        "error": f"no advice section for '{topic}'",
        "topics": titles,
        "authority": _AUTHORITY_NOTICE,
    }
