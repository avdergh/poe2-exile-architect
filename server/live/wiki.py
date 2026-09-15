"""Live wiki lookup — the long-tail escape hatch (the ONLY runtime wiki read).

When a mechanic/skill/item isn't in the bundled corpus, this fetches a concise extract from
the PoE2 Wiki's MediaWiki API on demand. It is a *targeted slice* (lead plus early mechanics
sections, capped locally), never a returned page dump, and it degrades gracefully to
"unavailable" if the wiki is unreachable.

This is a deliberate, narrow exception to the offline-first invariant (see CLAUDE.md invariant
#3): a single, user-triggered, read-only lookup — not bundled redistribution. PoE2 Wiki content
is CC BY-NC-SA 3.0; the result carries its source URL + license so callers attribute it.
"""

from __future__ import annotations

import json
import html
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

API = "https://www.poe2wiki.net/api.php"
PAGE_URL = "https://www.poe2wiki.net/wiki/{}"
PERMANENT_URL = "https://www.poe2wiki.net/index.php?oldid={}"
LICENSE = "CC BY-NC-SA 3.0"
SOURCE = "PoE2 Wiki (poe2wiki.net)"
UA = {"User-Agent": "poe2-exile-architect/0.1 (+https://github.com/avdergh/poe2-exile-architect)"}
MAX_CHARS = 2500  # targeted slice, not a page dump
DEFAULT_RETRY_AFTER_SECONDS = 60


def _rate_limit_result(topic: str, error: urllib.error.HTTPError) -> dict[str, Any]:
    """Report one server refusal; this function never sleeps or retries a request."""
    now = datetime.now(timezone.utc)
    raw = str(error.headers.get("Retry-After", "") if error.headers else "").strip()
    delay = DEFAULT_RETRY_AFTER_SECONDS
    source = "default_suggestion"
    try:
        if re.fullmatch(r"[0-9]+", raw):
            delay = int(raw)
        else:
            retry_at = parsedate_to_datetime(raw)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            delay = max(0, math.ceil((retry_at - now).total_seconds()))
        # Treat an out-of-range server date/delay as an unusable header.
        now + timedelta(seconds=delay)
        source = "retry_after_header"
    except (TypeError, ValueError, OverflowError):
        delay = DEFAULT_RETRY_AFTER_SECONDS
    return {
        "available": False,
        "errorCode": "rate_limited",
        "error": "Wiki request rate limited (HTTP 429).",
        "topic": topic,
        "retryAfterSeconds": delay,
        "retryAt": (now + timedelta(seconds=delay)).isoformat().replace("+00:00", "Z"),
        "retryAfterSource": source,
        "note": "Suggested next attempt time only; the server may still limit a later request.",
    }


def _api(params: dict, timeout: float = 12.0) -> dict:
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read())


def _extract(title: str) -> dict | None:
    res = _api(
        {
            "action": "query",
            "prop": "extracts|info|revisions",
            "explaintext": 1,
            "exsectionformat": "plain",
            "rvlimit": 1,
            "rvprop": "ids|timestamp",
            "redirects": 1,
            "titles": title,
        }
    )
    query = res.get("query", {})
    match_kind = "redirect" if query.get("redirects") else "direct"
    for _pid, p in query.get("pages", {}).items():
        if "missing" in p:
            return None
        text = (p.get("extract") or "").strip()
        if not text:
            return None
        real = p.get("title") or title
        revisions = p.get("revisions") or []
        latest_revision = revisions[0] if revisions and isinstance(revisions[0], dict) else {}
        page_id = int(p.get("pageid") or _pid)
        revision_id = int(latest_revision.get("revid") or p.get("lastrevid") or 0)
        revision_timestamp = str(latest_revision.get("timestamp") or "")
        return {
            "title": real,
            "text": text[:MAX_CHARS],
            "url": PAGE_URL.format(urllib.parse.quote(real.replace(" ", "_"))),
            "pageId": page_id,
            "revisionId": revision_id,
            "revisionTimestamp": revision_timestamp,
            "permanentUrl": PERMANENT_URL.format(revision_id) if revision_id else None,
            "sourceRef": (
                f"poe2wiki:page:{page_id}:rev:{revision_id}"
                if page_id > 0 and revision_id > 0
                else None
            ),
            "matchKind": match_kind,
        }
    return None


def lookup_mechanic(
    topic: str,
    *,
    cursor: int | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Fetch one direct page or return paged search candidates for Agent review.

    Page identity never authorizes semantic relevance. A direct/redirect result includes a bounded
    extract; a full-text fallback returns candidates only, which the Agent must select and fetch by
    exact title before recording a mechanic-audit judgment.
    """
    topic = (topic or "").strip()
    if not topic:
        return {"available": False, "error": "empty topic"}
    try:
        rec = _extract(topic)
        if rec is None:
            page_size = max(1, min(int(limit), 20))
            offset = max(0, int(cursor or 0))
            s = _api(
                {
                    "action": "query",
                    "list": "search",
                    "srsearch": topic,
                    "srlimit": page_size,
                    "sroffset": offset,
                    "srprop": "snippet",
                },
                timeout=12.0,
            )
            hits = s.get("query", {}).get("search", [])
            if not hits:
                return {
                    "available": True,
                    "found": False,
                    "topic": topic,
                    "requestedTopic": topic,
                    "resultKind": "search_candidates",
                    "candidates": [],
                    "continuation": None,
                }
            candidates = []
            for hit in hits:
                raw_snippet = str(hit.get("snippet") or "")
                snippet = html.unescape(re.sub(r"<[^>]+>", "", raw_snippet)).strip()
                candidates.append(
                    {
                        "title": str(hit.get("title") or ""),
                        "pageId": int(hit.get("pageid") or 0),
                        "snippet": snippet[:600],
                        "matchKind": "search_candidate",
                    }
                )
            next_offset = (s.get("continue") or {}).get("sroffset")
            return {
                "available": True,
                "found": False,
                "topic": topic,
                "requestedTopic": topic,
                "resultKind": "search_candidates",
                "candidates": candidates,
                "continuation": ({"cursor": int(next_offset)} if next_offset is not None else None),
                "note": "Search results are candidates only. Fetch a selected exact title, read "
                "its content, and let the Research Agent judge supports/contradicts/silent.",
            }
        return {
            "available": True,
            "found": True,
            "topic": topic,
            "requestedTopic": topic,
            "resultKind": rec["matchKind"],
            "title": rec["title"],
            "text": rec["text"],
            "url": rec["url"],
            "pageId": rec["pageId"],
            "revisionId": rec["revisionId"],
            "revisionTimestamp": rec["revisionTimestamp"],
            "permanentUrl": rec["permanentUrl"],
            "sourceRef": rec["sourceRef"],
            "matchKind": rec["matchKind"],
            "candidates": [],
            "continuation": None,
            "excerptKind": "lead_and_early_sections",
            "license": LICENSE,
            "source": SOURCE,
            "attribution": f"{SOURCE}, {LICENSE} — {rec['permanentUrl'] or rec['url']}",
            "note": "A page was retrieved with revision-pinned provenance; found does not mean "
            "the page supports the requested claim. The Research Agent must read it and record "
            "supports/contradicts/silent with independent corroboration.",
        }
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return _rate_limit_result(topic, e)
        return {"available": False, "error": f"wiki unreachable: {e}", "topic": topic}
    except Exception as e:  # noqa: BLE001 - network/timeout: degrade gracefully
        return {"available": False, "error": f"wiki unreachable: {e}", "topic": topic}
