from __future__ import annotations

from typing import Any

from server.generation import leveled_build
from server.knowledge import db


class _FakeEngine:
    """Minimal engine stand-in: gem_level_requirements backed by a dict of curves."""

    def __init__(self, curves: dict[str, dict[str, Any]]) -> None:
        self.curves = curves

    def gem_level_requirements(self, gem_name: str) -> dict[str, Any]:
        return self.curves.get(gem_name, {"found": False, "gemName": gem_name})


def _curve(
    found: bool = True,
    *,
    requirements: list[int],
    natural_max: int = 20,
    name: str = "Ice Shot",
) -> dict[str, Any]:
    return {
        "found": found,
        "gemName": name,
        "isSupport": False,
        "naturalMaxLevel": natural_max,
        "levels": [{"level": i + 1, "levelRequirement": req} for i, req in enumerate(requirements)],
    }


def test_gem_level_availability_ok_partial_unavailable():
    engine = _FakeEngine(
        {
            "Ice Shot": _curve(requirements=[1, 10, 20, 30, 40], natural_max=20),
        }
    )
    # At 18: levels 1 (req 1) and 2 (req 10) usable; level 3 needs 20 → partial (below max).
    partial = leveled_build.gem_level_availability(engine, "Ice Shot", 18)
    assert partial["status"] == "partial"
    assert partial["maxLegalLevel"] == 2

    full = leveled_build.gem_level_availability(engine, "Ice Shot", 40)
    assert full["status"] == "partial"  # 5 usable levels but natural cap is 20
    assert full["maxLegalLevel"] == 5

    capped_engine = _FakeEngine(
        {"Capped": _curve(requirements=[1, 10, 20, 30, 40], natural_max=5, name="Capped")}
    )
    capped_full = leveled_build.gem_level_availability(capped_engine, "Capped", 40)
    assert capped_full["status"] == "ok"  # maxLegalLevel == naturalMax
    assert capped_full["maxLegalLevel"] == 5

    low = leveled_build.gem_level_availability(engine, "Ice Shot", 1)
    assert low["status"] == "partial"  # level 1 usable, but below the 20-level cap
    assert low["maxLegalLevel"] == 1
    # naturalMax == 1 means the curve caps at level 1 → usable = ok, not partial.
    engine_capped = _FakeEngine({"Capped": _curve(requirements=[1], natural_max=1, name="Capped")})
    capped = leveled_build.gem_level_availability(engine_capped, "Capped", 18)
    assert capped["status"] == "ok"
    assert capped["maxLegalLevel"] == 1


def test_gem_level_availability_level_requirement_exceeds():
    engine = _FakeEngine({"Ice Shot": _curve(requirements=[20, 40, 60])})
    result = leveled_build.gem_level_availability(engine, "Ice Shot", 18)
    assert result["status"] == "unavailable"
    assert result["reason"] == "level_requirement_exceeds_target"


def test_gem_level_availability_engine_miss():
    engine = _FakeEngine({})
    result = leveled_build.gem_level_availability(engine, "Ice Shot", 18)
    assert result["status"] == "unavailable"
    assert result["reason"] == "gem_not_found_in_engine"


def test_validate_level_availability_resolves_name_gem_key_and_skill_key():
    engine = _FakeEngine({"Ice Shot": _curve(requirements=[1, 10], natural_max=20)})
    result = leveled_build.validate_level_availability(
        engine,
        skill_keys=[
            "Ice Shot",
            "gem:Metadata/Items/Gem/SkillGemIceShot",
            "skill:IceShotPlayer",
            "No Such Gem",
        ],
        level=18,
        class_key="Ranger",
    )
    by_skill = {item["skill"]: item for item in result["results"]}
    # Usable at 18 but below the 20-level cap → partial, attribute-compatible for Ranger.
    assert by_skill["Ice Shot"]["status"] == "partial"
    assert by_skill["Ice Shot"]["attributeCompatible"] is True
    assert by_skill["gem:Metadata/Items/Gem/SkillGemIceShot"]["status"] == "partial"
    assert by_skill["skill:IceShotPlayer"]["status"] == "unavailable"
    assert by_skill["skill:IceShotPlayer"]["reason"] == "unresolvable_skill_identity"
    assert by_skill["No Such Gem"]["status"] == "unavailable"
    assert by_skill["No Such Gem"]["reason"] == "gem_not_found_in_corpus"


def test_validate_level_availability_attribute_compatibility():
    engine = _FakeEngine(
        {
            # Fireball at full usable level (naturalMax == 2, both reqs ≤ 18) → ok before the
            # attribute downgrade.
            "Fireball": _curve(requirements=[1, 10], natural_max=2, name="Fireball"),
            "Ice Shot": _curve(requirements=[1, 10], natural_max=20),
        }
    )
    warrior = leveled_build.validate_level_availability(
        engine, skill_keys=["Fireball", "Ice Shot"], level=18, class_key="Warrior"
    )
    by_skill = {item["skill"]: item for item in warrior["results"]}
    # Fireball is int-only → attribute-incompatible for Warrior → ok downgraded to partial.
    assert by_skill["Fireball"]["status"] == "partial"
    assert by_skill["Fireball"]["attributeCompatible"] is False
    # Ice Shot is dex-only → also incompatible for Warrior (already partial from the level cap).
    assert by_skill["Ice Shot"]["attributeCompatible"] is False

    ranger = leveled_build.validate_level_availability(
        engine, skill_keys=["Fireball", "Ice Shot"], level=18, class_key="Ranger"
    )
    by_skill_r = {item["skill"]: item for item in ranger["results"]}
    assert by_skill_r["Ice Shot"]["attributeCompatible"] is True
    assert by_skill_r["Fireball"]["attributeCompatible"] is False  # int-only vs Ranger dex


def test_leveled_skill_pool_filters_by_engine_curve():
    engine = _FakeEngine({})
    empty = leveled_build.leveled_skill_pool(engine, level=18, class_key="Ranger", limit=10)
    assert empty["candidates"] == []

    # Drive the pool with real corpus gems: take the Ranger-compatible pool names and give every
    # one a usable engine curve, so the pool must return them all as ok.
    real_pool = db.list_gems_for_level(level=18, gem_type="active", class_key="Ranger", limit=10)
    assert real_pool, "corpus should return Ranger-active gems at level 18"
    curves = {
        str(gem["name"]): _curve(requirements=[1], natural_max=1, name=str(gem["name"]))
        for gem in real_pool
    }
    engine2 = _FakeEngine(curves)
    pool = leveled_build.leveled_skill_pool(engine2, level=18, class_key="Ranger", limit=10)
    assert pool["candidates"], "engine-verified pool must not be empty"
    assert all(item["status"] == "ok" for item in pool["candidates"])
    assert all(item["attributeCompatible"] is True for item in pool["candidates"])
    assert all(item["maxLegalLevel"] == 1 for item in pool["candidates"])


def test_level_gear_scope_drop_level_filter():
    scope = leveled_build.level_gear_scope(18)
    assert scope["level"] == 18
    assert "slots" in scope and "Body Armour" in scope["slots"]
    for slot, info in scope["slots"].items():
        for base in info["eligibleBases"]:
            assert base["dropLevel"] <= 18
    assert "affixNote" in scope


def test_class_attribute_mapping_shapes():
    mapping = db.class_attribute_mapping()
    assert mapping["Warrior"] == {"attribute": "strength", "short": "str"}
    assert mapping["Ranger"] == {"attribute": "dexterity", "short": "dex"}
    assert mapping["Witch"] == {"attribute": "intelligence", "short": "int"}
    assert mapping["Huntress"] == {"attribute": "dexterity", "short": "dex"}
    assert mapping["Druid"] == {"attribute": "strength", "short": "str"}
    assert len(mapping) == 8
