"""Versioned availability corrections; physical identity and PoB model support stay separate."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import threading
from typing import Any, Literal
from urllib.parse import urlparse
from weakref import WeakKeyDictionary

from pydantic import BaseModel, ConfigDict, Field, model_validator

from server import paths

CATALOG_PATH = paths.BUNDLE_ROOT / "data/compatibility/gem-availability.json"
_REVIEW_LOCK = threading.RLock()
_SESSION_REVIEWS: WeakKeyDictionary[Any, dict[str, dict[str, Any]]] = WeakKeyDictionary()


def session_reviews(engine: Any) -> list[dict[str, Any]]:
    with _REVIEW_LOCK:
        return deepcopy(list((_SESSION_REVIEWS.get(engine) or {}).values()))


def register_session_reviews(engine: Any, reviewed: dict[str, dict[str, Any]]) -> None:
    """Internal sink for already identity-bound Agent reviews; no global/durable writes."""
    with _REVIEW_LOCK:
        _SESSION_REVIEWS.setdefault(engine, {}).update(deepcopy(reviewed))


def _patch(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[a-z]\d*)?", value)
    if not match:
        raise ValueError("invalid_availability_target_patch")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "gem-availability:" + hashlib.sha256(encoded.encode()).hexdigest()


@lru_cache(maxsize=8)
def _load(path: Path, mtime: int, size: int) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != 1:
        raise ValueError("unsupported_gem_availability_catalog")
    _patch(payload["targetPatch"])
    sources = {entry["ref"] for entry in payload["sources"]}
    used: set[str] = set()
    for entry in payload["entries"]:
        ids = set(entry["gemIds"])
        if (
            not ids
            or ids & used
            or entry["componentKey"] not in {"gem:" + key for key in ids}
            or entry["status"] != "removed"
            or entry["sourceRef"] not in sources
            or entry["identitySourceRef"] not in sources
        ):
            raise ValueError("invalid_gem_availability_identity_binding")
        used.update(ids)
        _patch(entry["sincePatch"])
    return {**payload, "catalogRef": fingerprint(payload)}


def catalog() -> dict[str, Any]:
    stat = (
        CATALOG_PATH.stat()
    )  # Missing correction data is a packaging failure, never an empty list.
    return _load(CATALOG_PATH, stat.st_mtime_ns, stat.st_size)


def inspect_ids(gem_ids: list[str], *, target_patch: str | None = None) -> dict[str, Any]:
    data = catalog()
    target = target_patch or data["targetPatch"]
    version = _patch(target)
    ids = {str(key).removeprefix("gem:") for key in gem_ids}
    for entry in data["entries"]:
        if ids.intersection(entry["gemIds"]) and version >= _patch(entry["sincePatch"]):
            return {
                "status": "unavailable",
                "reason": "removed_from_game",
                "componentKey": entry["componentKey"],
                "sincePatch": entry["sincePatch"],
                "targetPatch": target,
                "catalogRef": data["catalogRef"],
                "evidenceKind": "static_source",
                "sourceRefs": [entry["sourceRef"], entry["identitySourceRef"]],
            }
    return {
        "status": "not_flagged_unavailable",
        "targetPatch": target,
        "catalogRef": data["catalogRef"],
        "currentAvailabilityCertified": False,
    }


def unavailable_ids(*, target_patch: str | None = None) -> set[str]:
    data = catalog()
    target = _patch(target_patch or data["targetPatch"])
    return {
        key
        for row in data["entries"]
        if target >= _patch(row["sincePatch"])
        for key in row["gemIds"]
    }


def validate_corpus_bindings(connection: Any) -> dict[str, Any]:
    """Release check: exact identifiers cannot silently move to a different component."""
    checked = 0
    for entry in catalog()["entries"]:
        key = entry["componentKey"].removeprefix("gem:")
        row = connection.execute("SELECT name, grants FROM gems WHERE id = ?", (key,)).fetchone()
        if row is None:
            continue  # A later export may finally remove the obsolete physical row.
        if row[0] != entry["displayName"] or set(json.loads(row[1])) != set(entry["effectIds"]):
            raise ValueError("gem_availability_corpus_identity_mismatch:" + key)
        checked += 1
    return {
        "catalogRef": catalog()["catalogRef"],
        "checkedBindings": checked,
        "removedSubjects": len(catalog()["entries"]),
    }


class AvailabilitySourceReview(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)
    url: str
    assessment: Literal["supports_unavailable"]
    relevance_reason: str = Field(alias="relevanceReason", min_length=1, max_length=600)


class SupportAvailabilityReview(BaseModel):
    """Agent-read evidence excludes a candidate in this engine session; it never edits global data.

    Read the official page and independent corroboration before submission. URLs alone do not
    prove their contents. This is explicitly agent_reviewed evidence, not an internal research receipt.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    component_key: str = Field(alias="componentKey", pattern=r"^gem:Metadata/Items/Gems?/[^\s]+$")
    target_patch: str = Field(alias="targetPatch")
    reason: Literal["removed", "disabled"]
    evidence_kind: Literal["agent_reviewed"] = Field(default="agent_reviewed", alias="evidenceKind")
    source_reviews: list[AvailabilitySourceReview] = Field(alias="sourceReviews", min_length=2)

    @model_validator(mode="after")
    def reviewed_sources(self) -> "SupportAvailabilityReview":
        _patch(self.target_patch)
        hosts = set()
        official = False
        for evidence in self.source_reviews:
            parsed = urlparse(evidence.url)
            host = (parsed.hostname or "").removeprefix("www.")
            if parsed.scheme != "https" or parsed.username or not host or parsed.path in {"", "/"}:
                raise ValueError("availability_review_requires_specific_https_sources")
            hosts.add(host)
            official |= host in {"pathofexile.com", "pathofexile2.com"}
        if not official or len(hosts) < 2:
            raise ValueError("availability_review_requires_official_and_independent_reading")
        return self


def public_sources() -> list[dict[str, Any]]:
    return deepcopy(catalog()["sources"])
