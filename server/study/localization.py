"""Official, identity-bound terminology; untranslated names stay in English."""

from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import html
from html.parser import HTMLParser

TOKEN = re.compile(r"\{\{([a-z0-9-]+)\}\}")
CATALOG = Path(__file__).with_name("data") / "official_terms.json"
OFFICIAL_HOSTS = {
    "pathofexile2.com",
    "www.pathofexile2.com",
    "www.pathofexile.com",
    "pathofexile.com",
    "poe2.qq.com",
}


class _PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)


def reviewed_translation(english: str, chinese: str, source_url: str, excerpt: str) -> dict:
    """Bind an Agent-reviewed bilingual quote to a freshly read official page, without a DB write."""
    from .storage import StudyError, fingerprint

    parsed = urlparse(source_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in OFFICIAL_HOSTS
        or parsed.port
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or any(
            part.casefold() in {"forum", "account", "character-window", "api"}
            for part in parsed.path.split("/")
        )
    ):
        raise StudyError("study_translation_requires_official_page")
    if not chinese.strip() or len(chinese) > 120 or len(excerpt) > 1500:
        raise StudyError("study_translation_invalid_quote")
    try:
        with urlopen(
            Request(source_url, headers={"User-Agent": "ExileArchitect-Study/1.0"}), timeout=15
        ) as response:  # noqa: S310 - official public page allowlist
            final = urlparse(response.url)
            if final.hostname != parsed.hostname or final.scheme != "https":
                raise StudyError("study_translation_redirect_rejected")
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise StudyError("study_translation_page_too_large")
        page = html.unescape(raw.decode("utf-8"))
    except (OSError, UnicodeError) as exc:
        raise StudyError("study_translation_source_unavailable") from exc

    def normalized(value):
        return " ".join(value.split())

    parsed_text = _PageText()
    parsed_text.feed(page)
    if (
        (
            normalized(excerpt) not in normalized(page)
            and normalized(excerpt) not in normalized(" ".join(parsed_text.parts))
        )
        or english not in excerpt
        or chinese not in excerpt
    ):
        raise StudyError("study_translation_quote_not_bound")
    return {
        "en": english,
        "zh": chinese,
        "translationStatus": "official_source_agent_reviewed",
        "translationSource": source_url,
        "translationSourceHash": fingerprint(raw),
    }


def resolve_name(english: str, identity: str, patch: str, *, catalog: Path | None = None) -> dict:
    fallback = {"en": english, "zh": english, "translationStatus": "english_fallback"}
    try:
        data = json.loads((catalog or CATALOG).read_text(encoding="utf-8"))
        if data.get("schemaVersion") != "official_terms_v1":
            return fallback
        hits = [
            entry
            for entry in data["entries"]
            if (
                entry.get("identity") == identity
                and entry.get("en") == english
                and patch in entry.get("patches", [])
                and entry.get("locale") == "zh-CN"
                and entry.get("provenance") in {"official_page", "official_client"}
                and urlparse(entry.get("sourceUrl", "")).hostname in OFFICIAL_HOSTS
                and re.fullmatch(r"[a-f0-9]{64}", entry.get("sourceHash", ""))
                and entry.get("zh")
                and entry.get("reviewedAt")
            )
        ]
    except (OSError, ValueError, KeyError, TypeError):
        return fallback
    if len(hits) != 1:
        return fallback
    return {
        "en": english,
        "zh": hits[0]["zh"],
        "translationStatus": "official",
        "translationSource": hits[0]["sourceUrl"],
        "translationSourceHash": hits[0]["sourceHash"],
    }


def resolve_text(value: dict, language: str, components: dict) -> str:
    return TOKEN.sub(lambda m: components[m[1]]["name"][language], value[language])


def unresolved_tokens(value, components: dict) -> list[str]:
    if isinstance(value, str):
        return [match for match in TOKEN.findall(value) if match not in components]
    if isinstance(value, dict):
        return [ref for child in value.values() for ref in unresolved_tokens(child, components)]
    if isinstance(value, list):
        return [ref for child in value for ref in unresolved_tokens(child, components)]
    return []
