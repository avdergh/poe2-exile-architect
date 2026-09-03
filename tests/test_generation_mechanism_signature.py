from __future__ import annotations

from contextlib import nullcontext

from server.generation import mechanism_signature


class _Engine:
    def __init__(self, stats: dict[str, float]) -> None:
        self.xml = '<PathOfBuilding><Build level="95"/></PathOfBuilding>'
        self.stats = stats

    def get_xml(self) -> str:
        return self.xml

    def transaction_lock(self):
        return nullcontext()

    def load_build_xml(self, xml: str, name: str = "") -> dict[str, object]:
        self.xml = xml
        return {"ok": True, "name": name}

    def select_judge_skill(
        self,
        *,
        offense_skill_group_index: int,
        expected_skill_name: str,
    ) -> dict[str, object]:
        return {
            "status": "selected",
            "calculationContext": {
                "groupIndex": offense_skill_group_index,
                "activeIndex": 1,
                "skillName": expected_skill_name,
            },
        }

    def get_stats(self, _keys: list[str]) -> dict[str, object]:
        return {"stats": dict(self.stats)}


def _listed(*supports: str) -> dict[str, object]:
    return {
        "groups": [
            {
                "index": 2,
                "isMain": True,
                "activeSkills": [{"index": 1, "name": "Whirling Assault"}],
                "gems": [
                    {"name": "Whirling Assault", "isSupport": False},
                    *({"name": name, "isSupport": True} for name in supports),
                ],
            }
        ]
    }


def test_observed_signature_binds_supports_resource_domain_and_damage_types(monkeypatch):
    engine = _Engine(
        {
            "LifeCost": 80,
            "ManaCost": 0,
            "PhysicalHitAverage": 120,
            "FireHitAverage": 0,
        }
    )
    monkeypatch.setattr(
        mechanism_signature.skillgroups,
        "list_skill_groups",
        lambda _engine: _listed("Lifetap", "Brutality I"),
    )
    declared = {
        "offenseSkillGroupIndex": 2,
        "activeSkillName": "Whirling Assault",
    }

    result = mechanism_signature.observe(engine, declared)

    assert result["ok"] is True
    assert result["signature"]["supportNames"] == ["Brutality I", "Lifetap"]
    assert result["signature"]["resourceCostDomains"] == ["life"]
    assert result["signature"]["hitDamageTypes"] == ["physical"]
    assert result["signature"]["hitDamageTypesModelled"] is True


def test_signature_detects_lifetap_or_damage_axis_drift(monkeypatch):
    engine = _Engine({"ManaCost": 20, "LightningHitAverage": 100})
    monkeypatch.setattr(
        mechanism_signature.skillgroups,
        "list_skill_groups",
        lambda _engine: _listed("Elemental Armament I"),
    )
    declared = {
        "offenseSkillGroupIndex": 2,
        "activeSkillName": "Whirling Assault",
        "supportNames": ["Brutality I"],
        "resourceCostDomains": ["mana"],
        "hitDamageTypes": ["physical"],
        "hitDamageTypesModelled": True,
    }

    observed = mechanism_signature.observe(engine, declared)

    assert observed["ok"] is True
    assert mechanism_signature.matches(declared, observed["signature"]) is False
