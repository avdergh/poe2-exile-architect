from __future__ import annotations

from datetime import datetime, timedelta, timezone

from server import paths
from server.generation import progression_costs


def _request() -> dict[str, object]:
    return {
        "stageId": "stage:target-80",
        "league": "Test League",
        "dependencies": [
            {
                "dependencyId": "cost-item:cheap-unique",
                "kind": "unique",
                "role": "required",
                "itemName": "Cheap Relic",
                "fallbackAvailable": False,
                "responsibility": "Closes the target damage loop.",
            },
            {
                "dependencyId": "cost-item:rare-weapon",
                "kind": "rare",
                "role": "required",
                "craftEffort": "high",
                "fallbackAvailable": True,
                "responsibility": "Provides stage weapon damage.",
            },
        ],
    }


def test_progression_costs_use_divine_bands_and_never_sum_a_build(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    calls = []

    def get_prices(*, query, kind, league, limit):
        calls.append((query, kind))
        if kind == "currency":
            return {
                "league": league,
                "base_currency": "Exalted Orb",
                "results": [{"name": "Divine Orb", "price": 100}],
            }
        return {
            "league": league,
            "base_currency": "Exalted Orb",
            "results": [{"name": query, "price": 10}],
        }

    monkeypatch.setattr(progression_costs.live_prices, "get_prices", get_prices)
    result = progression_costs.classify_build_progression_costs(_request())

    assert result["status"] == "classified"
    unique = result["dependencies"][0]
    assert unique["divineEquivalent"] == 0.1
    assert unique["costBand"] == "cheap"
    assert result["dependencies"][1]["costBand"] == "expensive"
    assert result["highestRequiredBand"] == "expensive"
    assert result["paidDependencyCount"] == 2
    assert result["containsTotalPrice"] is False
    assert not any("total" in key.casefold() and key != "containsTotalPrice" for key in result)
    assert (
        progression_costs.read_trusted_cost_profile(
            result["costProfileRef"],
            stage_id="stage:target-80",
        )
        is not None
    )
    monkeypatch.setattr(
        progression_costs,
        "_now",
        lambda: datetime.now(timezone.utc) + timedelta(hours=7),
    )
    assert (
        progression_costs.read_trusted_cost_profile(
            result["costProfileRef"],
            stage_id="stage:target-80",
        )
        is None
    )
    assert (
        progression_costs.read_trusted_cost_profile(
            result["costProfileRef"],
            stage_id="stage:target-80",
            allow_expired=True,
        )
        is not None
    )

    monkeypatch.setattr(
        progression_costs,
        "_now",
        lambda: datetime.now(timezone.utc),
    )
    cached = progression_costs.classify_build_progression_costs(_request())
    assert cached["cacheStatus"] == "fresh_hit"
    assert len(calls) == 2


def test_progression_cost_boundaries_and_price_failure_are_advisory(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    assert progression_costs._unique_band(0.1) == "cheap"
    assert progression_costs._unique_band(0.5) == "moderate"
    assert progression_costs._unique_band(2.0) == "expensive"
    assert progression_costs._unique_band(2.01) == "chase"

    monkeypatch.setattr(
        progression_costs.live_prices,
        "get_prices",
        lambda **_kwargs: (_ for _ in ()).throw(
            progression_costs.live_prices.PriceError("offline")
        ),
    )
    result = progression_costs.classify_build_progression_costs(_request())
    assert result["status"] == "classified"
    assert result["costEvidenceStatus"] == "unavailable"
    assert result["dependencies"][0]["costBand"] == "unknown"
    assert result["highestRequiredBand"] == "unknown"
    assert result["unknownRequiredDependencyCount"] == 1
    assert result["dependencies"][1]["costBand"] == "expensive"


def test_rare_only_cost_profile_does_not_require_network(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        progression_costs.live_prices,
        "get_prices",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("network not expected")),
    )
    request = _request()
    request["dependencies"] = [request["dependencies"][1]]
    result = progression_costs.classify_build_progression_costs(request)
    assert result["status"] == "classified"
    assert result["costEvidenceStatus"] == "supported"
    assert result["livePriceCoverage"] == 1.0
