"""Live wiki lookup — the long-tail escape hatch (the ONLY runtime wiki read).

When a mechanic/skill/item isn't in the bundled corpus, this fetches a concise extract from
the PoE2 Wiki's MediaWiki API on demand. It is a *targeted slice* (lead extract + link), never
a page dump, and it degrades gracefully to "unavailable" if the wiki is unreachable.

This is a deliberate, narrow exception to the offline-first invariant (see CLAUDE.md invariant
#3): a single, user-triggered, read-only lookup — not bundled redistribution. PoE2 Wiki content
is CC BY-NC-SA 3.0; the result carries its source URL + license so callers attribute it.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

API = "https://www.poe2wiki.net/api.php"
PAGE_URL = "https://www.poe2wiki.net/wiki/{}"
LICENSE = "CC BY-NC-SA 3.0"
SOURCE = "PoE2 Wiki (poe2wiki.net)"
UA = {"User-Agent": "poe-bd-creator/0.1 (+https://github.com/avdergh/poe-bd-creator)"}
MAX_CHARS = 2500  # targeted slice, not a page dump


def _api(params: dict, timeout: float = 12.0) -> dict:
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read())


def _extract(title: str) -> dict | None:
    res = _api(
        {
            "action": "query",
            "prop": "extracts",
            "explaintext": 1,
            "exintro": 1,
            "exsectionformat": "plain",
            "redirects": 1,
            "titles": title,
        }
    )
    for _pid, p in res.get("query", {}).get("pages", {}).items():
        if "missing" in p:
            return None
        text = (p.get("extract") or "").strip()
        if not text:
            return None
        real = p.get("title") or title
        return {
            "title": real,
            "text": text[:MAX_CHARS],
            "url": PAGE_URL.format(urllib.parse.quote(real.replace(" ", "_"))),
        }
    return None


def lookup_mechanic(topic: str) -> dict[str, Any]:
    """Fetch a concise wiki extract for `topic` live (best-effort). Tries the title directly,
    then a search, returning the top result's lead extract with attribution."""
    topic = (topic or "").strip()
    if not topic:
        return {"available": False, "error": "empty topic"}
    try:
        rec = _extract(topic)
        if rec is None:
            # fall back to search → best title → extract
            s = _api(
                {"action": "query", "list": "search", "srsearch": topic, "srlimit": 1},
                timeout=12.0,
            )
            hits = s.get("query", {}).get("search", [])
            if not hits:
                return {"available": True, "found": False, "topic": topic, "results": []}
            rec = _extract(hits[0]["title"])
            if rec is None:
                return {"available": True, "found": False, "topic": topic, "results": []}
        return {
            "available": True,
            "found": True,
            "topic": topic,
            "title": rec["title"],
            "text": rec["text"],
            "url": rec["url"],
            "license": LICENSE,
            "source": SOURCE,
            "attribution": f"{SOURCE}, {LICENSE} — {rec['url']}",
            "note": "Live wiki fetch (time-sensitive, may be wrong/outdated). Engine remains the "
            "source of truth for numbers. Attribute the source when you quote it.",
        }
    except Exception as e:  # noqa: BLE001 - network/timeout: degrade gracefully
        return {"available": False, "error": f"wiki unreachable: {e}", "topic": topic}
