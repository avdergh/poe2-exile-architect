"""Small provider-facing league token normalizer.

Freshness keeps its existing canonical claims.  Live providers use this helper only to match
display names, URL slugs and punctuation variants without changing their public response shape.
"""

from __future__ import annotations

import re
import urllib.parse


def normalize_league_token(value: str | None) -> str:
    """Case-fold one display name, slug or URL basename into a comparison token."""

    text = urllib.parse.unquote(str(value or "").strip())
    parsed = urllib.parse.urlparse(text)
    path = parsed.path or text
    if "/" in path:
        text = path.rstrip("/").rsplit("/", 1)[-1]
    else:
        text = path
    return re.sub(r"[^a-z0-9]+", "", text.casefold())
