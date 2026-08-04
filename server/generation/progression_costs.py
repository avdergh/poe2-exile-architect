"""Coarse cost-risk classification for progression stages.

Only named uniques use live prices. Rare items are classified from the existing craft-effort
signal, never assigned a fabricated market price. No total build cost is calculated.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, ValidationError, model_validator

from server import paths
from server.knowledge import copy_safety
from server.live import prices as live_prices

from . import models


COST_SCHEMA_VERSION = 1
PRICE_TTL = timedelta(hours=6)
DependencyRole = Literal["required", "recommended", "optional"]
UniqueBand = Literal["cheap", "moderate", "expensive", "chase", "unknown"]
RareBand = Literal["routine", "moderate", "expensive", "chase"]
CombinedBand = Literal["routine", "cheap", "moderate", "expensive", "chase", "unknown"]
CraftEffort = Literal["trivial", "low", "moderate", "high", "very high"]
_BAND_ORDER = {
    "routine": 0,
    "cheap": 1,
    "moderate": 2,
    "expensive": 3,
    "chase": 4,
    "unknown": -1,
}


class CostDependency(models.StrictModel):
    dependency_id: str = Field(pattern=r"^cost-item:[A-Za-z0-9\-]{3,100}$")
    kind: Literal["unique", "rare"]
    role: DependencyRole
    item_name: str | None = Field(default=None, min_length=1, max_length=160)
    craft_effort: CraftEffort | None = None
    fallback_available: bool = False
    responsibility: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def _typed(self) -> "CostDependency":
        if self.kind == "unique":
            if not self.item_name or self.craft_effort is not None:
                raise ValueError("unique cost dependency requires only item_name")
        elif self.craft_effort is None or self.item_name is not None:
            raise ValueError("rare cost dependency requires only craft_effort")
        safe_fragment = {
            "itemName": self.item_name,
            "responsibility": self.responsibility,
        }
        if copy_safety.copyability_flags(safe_fragment) or copy_safety.contains_raw_url(
            safe_fragment
        ):
            raise ValueError("unsafe cost dependency")
        return self


class CostRequest(models.StrictModel):
    stage_id: str = Field(pattern=r"^stage:[A-Za-z0-9\-]{3,100}$")
    league: str = Field(min_length=1, max_length=100)
    dependencies: list[CostDependency] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _unique(self) -> "CostRequest":
        ids = [item.dependency_id for item in self.dependencies]
        if len(ids) != len(set(ids)):
            raise ValueError("cost dependency ids must be unique")
        if sum(item.kind == "unique" for item in self.dependencies) > 8:
            raise ValueError("a stage may price at most eight named uniques")
        return self


def classify_build_progression_costs(payload: dict[str, Any]) -> dict[str, Any]:
    """Classify one stage and persist/reuse a six-hour safe snapshot."""

    try:
        request = CostRequest.model_validate(payload)
    except ValidationError as exc:
        first: Any = exc.errors()[0] if exc.errors() else {}
        return models.rejected(
            "invalid_progression_cost_request",
            caveats=[str(first.get("msg") or "invalid input")[:240]],
        )
    cache_key = _cache_key(request)
    cached = _read_cache(cache_key)
    if cached is not None and _parse_time(str(cached["expiresAt"])) > _now():
        response = dict(cached["response"])
        response["cacheStatus"] = "fresh_hit"
        return response

    unique_dependencies = [item for item in request.dependencies if item.kind == "unique"]
    divine_price: float | None = None
    live_lookup_available = True
    unique_prices: dict[str, float | None] = {}
    resolved_league = request.league
    base_currency = ""
    if unique_dependencies:
        try:
            divine_result = live_prices.get_prices(
                query="Divine Orb",
                kind="currency",
                league=request.league,
                limit=10,
            )
            resolved_league = str(divine_result.get("league") or request.league)
            base_currency = str(divine_result.get("base_currency") or "")
            if base_currency.casefold() == "divine orb":
                divine_price = 1.0
            else:
                divine_price = _exact_price(divine_result, "Divine Orb")
            for dependency in unique_dependencies:
                assert dependency.item_name is not None
                result = live_prices.get_prices(
                    query=dependency.item_name,
                    kind="unique",
                    league=request.league,
                    limit=20,
                )
                unique_prices[dependency.dependency_id] = _exact_price(result, dependency.item_name)
        except live_prices.PriceError:
            live_lookup_available = False
            unique_prices = {item.dependency_id: None for item in unique_dependencies}

    classified: list[dict[str, Any]] = []
    live_resolved = 0
    for dependency in request.dependencies:
        if dependency.kind == "unique":
            raw_price = unique_prices.get(dependency.dependency_id)
            divine_equivalent = (
                raw_price / divine_price
                if isinstance(raw_price, (int, float))
                and raw_price >= 0
                and isinstance(divine_price, (int, float))
                and divine_price > 0
                else None
            )
            band: CombinedBand = _unique_band(divine_equivalent)
            if divine_equivalent is not None:
                live_resolved += 1
            row = {
                "dependencyId": dependency.dependency_id,
                "kind": "unique",
                "role": dependency.role,
                "itemName": dependency.item_name,
                "divineEquivalent": (
                    round(divine_equivalent, 4) if divine_equivalent is not None else None
                ),
                "costBand": band,
                "fallbackAvailable": dependency.fallback_available,
                "responsibility": dependency.responsibility,
                "priceEvidence": "live" if divine_equivalent is not None else "unknown",
            }
        else:
            assert dependency.craft_effort is not None
            band = _rare_band(dependency.craft_effort)
            row = {
                "dependencyId": dependency.dependency_id,
                "kind": "rare",
                "role": dependency.role,
                "craftEffort": dependency.craft_effort,
                "costBand": band,
                "fallbackAvailable": dependency.fallback_available,
                "responsibility": dependency.responsibility,
                "priceEvidence": "craft_effort_only",
            }
        classified.append(row)

    required = [item for item in classified if item["role"] == "required"]
    unknown_required = sum(item["costBand"] == "unknown" for item in required)
    known_required = [item["costBand"] for item in required if item["costBand"] != "unknown"]
    highest_required: CombinedBand = (
        "unknown"
        if unknown_required
        else (
            max(known_required, key=lambda value: _BAND_ORDER[value])
            if known_required
            else "unknown"
        )
    )
    paid_dependencies = sum(
        item["role"] == "required"
        and (
            (item["kind"] == "unique" and item["costBand"] != "unknown")
            or (item["kind"] == "rare" and item["costBand"] in {"moderate", "expensive", "chase"})
        )
        for item in classified
    )
    fallback_count = sum(
        item["role"] == "required" and item["fallbackAvailable"] for item in classified
    )
    required_count = len(required)
    captured = _now()
    profile_ref = f"progression-cost:{hashlib.sha256(cache_key.encode()).hexdigest()[:16]}"
    response = {
        "status": "classified",
        "stageId": request.stage_id,
        "costProfileRef": profile_ref,
        "league": resolved_league,
        "baseCurrency": base_currency,
        "dependencies": classified,
        "highestRequiredBand": highest_required,
        "paidDependencyCount": paid_dependencies,
        "requiredDependencyCount": required_count,
        "unknownRequiredDependencyCount": unknown_required,
        "fallbackCoverage": (round(fallback_count / required_count, 3) if required_count else 1.0),
        "livePriceCoverage": (
            round(live_resolved / len(unique_dependencies), 3) if unique_dependencies else 1.0
        ),
        "costEvidenceStatus": (
            "supported"
            if not unique_dependencies or live_resolved == len(unique_dependencies)
            else ("limited" if live_lookup_available else "unavailable")
        ),
        "capturedAt": captured.isoformat(),
        "expiresAt": (captured + PRICE_TTL).isoformat(),
        "cacheStatus": "refreshed",
        "containsTotalPrice": False,
    }
    _write_cache(cache_key, response)
    return response


def read_trusted_cost_profile(
    cost_profile_ref: str,
    *,
    stage_id: str,
    allow_expired: bool = False,
) -> dict[str, Any] | None:
    """Resolve a classifier receipt; stage completion requires an unexpired one."""

    root = paths.build_progression_cost_cache_dir()
    if not root.is_dir():
        return None
    for path in root.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        response = payload.get("response") if isinstance(payload, dict) else None
        if (
            payload.get("schemaVersion") != COST_SCHEMA_VERSION
            or not isinstance(response, dict)
            or response.get("costProfileRef") != cost_profile_ref
            or response.get("stageId") != stage_id
        ):
            continue
        try:
            if not allow_expired and _parse_time(str(payload["expiresAt"])) <= _now():
                return None
        except (KeyError, TypeError, ValueError):
            return None
        return dict(response)
    return None


def _unique_band(value: float | None) -> UniqueBand:
    if value is None:
        return "unknown"
    if value <= 0.1:
        return "cheap"
    if value <= 0.5:
        return "moderate"
    if value <= 2.0:
        return "expensive"
    return "chase"


def _rare_band(value: CraftEffort) -> RareBand:
    bands: dict[CraftEffort, RareBand] = {
        "trivial": "routine",
        "low": "routine",
        "moderate": "moderate",
        "high": "expensive",
        "very high": "chase",
    }
    return bands[value]


def _exact_price(result: dict[str, Any], name: str) -> float | None:
    rows = result.get("results") if isinstance(result, dict) else None
    if not isinstance(rows, list):
        return None
    exact = [
        row
        for row in rows
        if isinstance(row, dict)
        and str(row.get("name") or "").casefold() == name.casefold()
        and isinstance(row.get("price"), int | float)
    ]
    return float(exact[0]["price"]) if exact else None


def _cache_key(request: CostRequest) -> str:
    canonical = json.dumps(
        request.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> Path:
    return paths.build_progression_cost_cache_dir() / f"{key}.json"


def _read_cache(key: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(_cache_path(key).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (
        payload.get("schemaVersion") != COST_SCHEMA_VERSION
        or payload.get("cacheKey") != key
        or not isinstance(payload.get("response"), dict)
    ):
        return None
    return payload


def _write_cache(key: str, response: dict[str, Any]) -> None:
    path = _cache_path(key)
    temp = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(
            json.dumps(
                {
                    "schemaVersion": COST_SCHEMA_VERSION,
                    "cacheKey": key,
                    "expiresAt": response["expiresAt"],
                    "response": response,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temp.replace(path)
    except OSError:
        temp.unlink(missing_ok=True)
        # Price classification remains usable when only the cache write fails.


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)
