"""Live PoE2 market prices via the public poe2scout.com API.

Currency prices are quoted in the league's base currency (Exalted Orbs for the current
challenge league). Data is read-only and refreshes upstream roughly hourly.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from .league_tokens import normalize_league_token

API = "https://poe2scout.com/api"
REALM = "poe2"
UA = {"User-Agent": "poe2-build-mcp/0.1"}

_league_info: dict[str, str] | None = None
_unique_cats: dict[str, list[str]] = {}


class PriceError(RuntimeError):
    """Raised when the price API can't be reached or returns an error."""


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{API}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
            return json.loads(r.read())
    except Exception as e:  # noqa: BLE001 - normalize to one error type
        raise PriceError(f"poe2scout request failed ({url}): {e}") from e


def list_leagues() -> list[dict[str, Any]]:
    return [
        {
            "name": leag["Value"],
            "current": bool(leag.get("IsCurrent")),
            "base_currency": leag.get("BaseCurrencyText"),
        }
        for leag in _get(f"{REALM}/Leagues")
    ]


def resolve_league(override: str | None = None) -> dict[str, str]:
    """Return {name, base} for the chosen league, defaulting to the current league."""
    global _league_info
    if override:
        token = normalize_league_token(override)
        for leag in _get(f"{REALM}/Leagues"):
            if normalize_league_token(leag["Value"]) == token:
                return {"name": leag["Value"], "base": leag.get("BaseCurrencyText", "")}
        return {"name": override, "base": ""}
    if _league_info is None:
        leagues = _get(f"{REALM}/Leagues")
        current = [leag for leag in leagues if leag.get("IsCurrent")] or leagues
        _league_info = {
            "name": current[0]["Value"],
            "base": current[0].get("BaseCurrencyText", ""),
        }
    return _league_info


def _unique_categories(enc_league: str) -> list[str]:
    if enc_league not in _unique_cats:
        cats = _get(f"{REALM}/Leagues/{enc_league}/Items/Categories")
        _unique_cats[enc_league] = [c["ApiId"] for c in cats.get("UniqueCategories", [])]
    return _unique_cats[enc_league]


def get_prices(
    query: str = "",
    kind: str = "currency",
    category: str | None = None,
    league: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Look up live prices. `kind` is "currency" or "unique"; results are sorted high→low."""
    info = resolve_league(league)
    enc = urllib.parse.quote(info["name"])
    q = (query or "").lower()
    results: list[dict[str, Any]] = []

    if kind == "currency":
        data = _get(
            f"{REALM}/Leagues/{enc}/Currencies/ByCategory",
            {"Category": "currency", "PerPage": 200},
        )
        for it in data.get("Items", []):
            name = it.get("Text") or it.get("ApiId") or ""
            if not q or q in name.lower():
                results.append(
                    {"name": name, "api_id": it.get("ApiId"), "price": it.get("CurrentPrice")}
                )
    elif kind == "unique":
        cats = [category] if category else _unique_categories(enc)
        for cat in cats:
            try:
                data = _get(
                    f"{REALM}/Leagues/{enc}/Uniques/ByCategory",
                    {"Category": cat, "Search": query or "", "PerPage": max(limit, 25)},
                )
            except PriceError:
                continue
            for it in data.get("Items", []):
                name = it.get("Text") or it.get("Name") or ""
                if not q or q in name.lower():
                    results.append({"name": name, "category": cat, "price": it.get("CurrentPrice")})
    else:
        raise PriceError(f"unknown kind {kind!r} (use 'currency' or 'unique')")

    results.sort(key=lambda r: (r.get("price") is None, -(r.get("price") or 0)))
    out: dict[str, Any] = {
        "league": info["name"],
        "base_currency": info["base"],
        "kind": kind,
        "results": results[:limit],
    }
    if kind == "unique" and query and not results:
        out["note"] = (
            "No matches — unique pricing matches by item NAME (e.g. 'Matsya'), not a base type "
            "or category. Try the unique's name."
        )
    return out
