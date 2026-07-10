"""Ingest a curated set of PoE2 wiki mechanics pages (build-time only).

This is the auto-refreshable "how mechanics work" tier of the corpus. Pages are fetched from
the community PoE2 Wiki's MediaWiki API as clean plaintext extracts, cached under
``data/raw/wiki/``, and written to the ``mechanics`` table by build_corpus.

Licensing: PoE2 Wiki content is **CC BY-NC-SA 3.0**. We store it in its own segregated table,
stamp every row with its source URL + license, and surface attribution in tool output. This
keeps the wiki tier a clearly-attributed aggregation, separate from our own (Tier-1) prose.
Scraping happens here, at build time / in CI — never at runtime (invariant #4).
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WIKI_RAW = REPO_ROOT / "data" / "raw" / "wiki"

API = "https://www.poe2wiki.net/api.php"
PAGE_URL = "https://www.poe2wiki.net/wiki/{}"
LICENSE = "CC BY-NC-SA 3.0"
SOURCE = "PoE2 Wiki (poe2wiki.net)"
UA = {"User-Agent": "poe-bd-creator/0.1 (+https://github.com/avdergh/poe-bd-creator)"}
MAX_CHARS = 9000  # keep each page lean; the lead + mechanics are what matter

# Curated mechanics pages (foundation + common + documented "weird" ones). Titles are the
# wiki's canonical titles; missing/renamed pages are skipped gracefully and logged. Add freely
# here — the cron re-fetches the list every run, so coverage grows without shipping a build.
PAGES: list[str] = [
    # core defences & pools
    "Resistance",
    "Energy shield",
    "Armour",
    "Evasion",
    "Life",
    "Mana",
    "Spirit",
    "Block",
    # damage pipeline
    "Damage",
    "Damage conversion",
    "Damage over time",
    "Hit",
    "Critical hit",
    "Penetration",
    "Exposure",
    "Curse",
    # ailments & status
    "Ailment",
    "Poison",
    "Ignite",
    "Bleeding",
    "Shock",
    "Chill",
    "Freeze",
    "Electrocute",
    "Stun",
    # recovery
    "Leech",
    "Life regeneration",
    "Recoup",
    # offense scaling & skills
    "Skill",
    "Support gem",
    "Minion",
    "Reservation",
    "Culling strike",
    "Accuracy",
    "Attack",
    "Spell",
    "Projectile",
    "Area of effect",
    # build identity / keystones
    "Keystone",
    "Chaos Inoculation",
    # documented "weird" mechanics that bit real builds
    "Plague Bearer",
    "The Raven's Flock",
]


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


def _is_heading(line: str) -> bool:
    """Heuristic: a short line with no sentence-ending punctuation is a section header."""
    line = line.strip()
    return 0 < len(line) <= 60 and not re.search(r"[.:!?,)]$", line)


def _trim_extract(text: str) -> str:
    """Drop empty sections (a header followed by no body) and collapse blank-line runs.

    MediaWiki plaintext extracts render template-driven sections (Related skills, Version
    history, …) as bare headers with no content; strip them so the corpus stays readable.
    """
    text = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
    lines = text.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        cur = lines[i].strip()
        if not cur:
            i += 1
            continue
        if _is_heading(cur):
            body: list[str] = []
            j = i + 1
            while j < n and not (lines[j].strip() and _is_heading(lines[j].strip())):
                if lines[j].strip():
                    body.append(lines[j].strip())
                j += 1
            if body:  # keep the header only when it has real content
                out.append(cur)
                out.extend(body)
            i = j
        else:
            out.append(cur)
            i += 1
    return "\n".join(out)


def _api(params: dict) -> dict:
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.loads(r.read())


def _fetch_extract(title: str) -> dict | None:
    """Return {title,text,url} for a page, or None if the page is missing."""
    res = _api(
        {
            "action": "query",
            "prop": "extracts",
            "explaintext": 1,
            "exsectionformat": "plain",
            "redirects": 1,
            "titles": title,
        }
    )
    pages = res.get("query", {}).get("pages", {})
    for _pid, p in pages.items():
        if "missing" in p:
            return None
        text = _trim_extract(p.get("extract") or "")
        if not text:
            return None
        real_title = p.get("title") or title
        return {
            "title": real_title,
            "text": text[:MAX_CHARS],
            "url": PAGE_URL.format(urllib.parse.quote(real_title.replace(" ", "_"))),
        }
    return None


def fetch_all(refresh: bool = False, delay: float = 0.4) -> dict[str, int]:
    """Fetch + cache every curated page. Polite (one request per page, small delay).

    Resilient: a page that fails or is missing is skipped (cached copy kept if present), so a
    transient wiki hiccup degrades coverage rather than wiping the tier.
    """
    WIKI_RAW.mkdir(parents=True, exist_ok=True)
    fetched = skipped = cached = 0
    for title in PAGES:
        dest = WIKI_RAW / f"{_slug(title)}.json"
        if dest.exists() and not refresh:
            cached += 1
            continue
        try:
            rec = _fetch_extract(title)
        except Exception as e:  # noqa: BLE001 - network hiccup: keep any cached copy, move on
            print(f"  wiki: fetch failed for {title!r}: {e}")
            rec = None
        if rec is None:
            if not dest.exists():
                print(f"  wiki: no page for {title!r} (skipped)")
                skipped += 1
            time.sleep(delay)
            continue
        dest.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        fetched += 1
        time.sleep(delay)
    return {"fetched": fetched, "cached": cached, "skipped": skipped}


def load_pages() -> list[dict]:
    """Read cached wiki pages into mechanics records (id,title,text,url,license,source)."""
    out: list[dict] = []
    if not WIKI_RAW.exists():
        return out
    for path in sorted(WIKI_RAW.glob("*.json")):
        try:
            rec = json.loads(path.read_text("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        title = rec.get("title")
        text = _trim_extract(rec.get("text") or "")  # also trim cached (pre-trim) extracts
        if not title or not text:
            continue
        out.append(
            {
                "id": _slug(title),
                "title": title,
                "text": text,
                "url": rec.get("url") or PAGE_URL.format(urllib.parse.quote(title)),
                "license": LICENSE,
                "source": SOURCE,
            }
        )
    return out
