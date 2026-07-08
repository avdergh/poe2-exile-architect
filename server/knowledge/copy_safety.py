"""Shared copy-safety helpers for mature-build learning.

These helpers reject raw or reconstructable build material before it can enter manifests,
LLM prompts, LLM outputs, evaluator gaps, or creator-visible context. They intentionally favor
false positives over leaking PoB codes, exact character/build URLs, full gear, passive paths, or
gem links.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlparse

from . import mature_learning


def find_forbidden_paths(value: Any, *, path: str = "") -> list[str]:
    """Find forbidden raw/copyable field names recursively in dict/list payloads."""
    forbidden = {
        _normalize_field_name(field) for field in mature_learning.FORBIDDEN_COPYABLE_FIELDS
    }
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = _join_path(path, _safe_path_segment(key_text))
            if _normalize_field_name(key_text) in forbidden:
                found.append(child_path)
            found.extend(find_forbidden_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]" if path else f"[{index}]"
            found.extend(find_forbidden_paths(child, path=child_path))
    return sorted(found)


def copyability_flags(value: Any) -> list[str]:
    """Return conservative copyability flags for reconstructable build details."""
    fragments = all_text(value)
    text = "\n".join(fragments)
    lower = text.lower()
    flags: set[str] = set()
    if re.search(r"\beNrt[A-Za-z0-9+/_=-]{40,}", text):
        flags.add("pob_code_like_blob")
    if re.search(r"(?:https?://)?(?:www\.)?(?:pobb\.in|pastebin\.com)/[A-Za-z0-9+/_=-]{4,}", text):
        flags.add("copyable_build_link")
    if re.search(r"(?:https?://)?(?:www\.)?poe\.ninja/(?:poe2/)?pob/[^\s)]+", lower):
        flags.add("copyable_build_link")
    if re.search(
        r"(?:https?://)?(?:www\.)?poe\.ninja/(?:poe2/)?builds?/[^\s)]*/character/[^\s)]+",
        lower,
    ):
        flags.add("copyable_build_link")
    if re.search(
        r"(?:https?://)?(?:www\.)?pathofexile\.com/(?:account/view-profile|character-window)/[^\s)]+",
        lower,
    ):
        flags.add("raw_account_or_character_url")
    if re.search(r"(?:supports?|support gems?)\s*:\s*[^.\n,]+(?:,\s*[^.\n,]+){4,}", lower):
        flags.add("full_support_link_like")
    if re.search(
        r"\b[\w' ]{1,32}\s*(?:(?:->|=>|/|[-+>])\s*[\w' ]{1,32}\s*){4,}",
        text,
    ):
        flags.add("full_gem_link_like")
    if re.search(
        r"(passive path|node\s+\d+).{0,80}(->|,|\bthen\b).{0,80}node\s+\d+",
        lower,
    ) or re.search(
        r"passive path\s*:\s*\d+(?:\s*(?:->|,|\bthen\b)\s*\d+){2,}",
        lower,
    ):
        flags.add("ordered_passive_path")
    if re.search(
        r"(ring 1|ring 2|amulet|helmet|body armour|body armor|gloves|boots|weapon|"
        r"offhand|quiver|belt|jewel)\s*:",
        lower,
    ):
        flags.add("slot_exact_gear_like")
    if any(len(fragment) > 1200 for fragment in fragments):
        flags.add("long_guide_prose_like")
    return sorted(flags)


def all_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        parts: list[str] = []
        for key, child in value.items():
            key_text = str(key)
            parts.append(key_text)
            if isinstance(child, str | int | float | bool):
                parts.append(f"{key_text}: {child}")
            parts.extend(all_text(child))
        return parts
    if isinstance(value, list):
        parts = []
        for child in value:
            parts.extend(all_text(child))
        return parts
    return []


def is_empty(value: Any) -> bool:
    return value in (None, "", [], {})


def safe_text(value: Any, *, limit: int = 120) -> str:
    """Return a short non-control text value for already-safe metadata."""
    return re.sub(r"\s+", " ", str(value).strip())[:limit]


def is_allowed_enum(value: Any, allowed: set[str]) -> bool:
    """Hash-safe enum membership check for untrusted LLM/user payloads."""
    return isinstance(value, str) and value in allowed


def safe_url_ref(url: str) -> str:
    """Return a stable, copy-safe URL reference instead of the source URL itself."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    host = urlparse(url).netloc.lower() or "unknown-host"
    host_label = re.sub(r"[^a-z0-9.-]", "-", host)[:80]
    return f"source-url:{host_label}:{digest}"


def _join_path(parent: str, segment: str) -> str:
    return f"{parent}.{segment}" if parent else segment


def _safe_path_segment(segment: str) -> str:
    """Return a path segment that identifies fields without echoing copyable keys."""
    if copyability_flags(segment) or len(segment) > 120:
        digest = hashlib.sha256(segment.encode("utf-8")).hexdigest()[:12]
        return f"redacted-key:{digest}"
    return segment


def _normalize_field_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())
