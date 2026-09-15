"""Isolated PoB contract: preserve unknowns and reject invalid numerical comparisons."""

from __future__ import annotations

import pytest

from server.study import measurements, storage


class FakeEngine:
    instances = []
    capability = "supported"
    invalid_after = False
    missing_after = False

    def __init__(self, **kwargs):
        self.changed = False
        self.closed = False
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def load_build_xml(self, xml, **kwargs):
        self.xml = xml

    def select_judge_skill(self, **kwargs):
        if self.changed and self.missing_after:
            return {"status": "error"}
        selected = {"groupIndex": 1, "activeIndex": 1, "skillName": "Fixture", "skillId": "fixture"}
        return {"status": "selected", "selectedSkill": selected, "calculationContext": selected}

    def call(self, *args, **kwargs):
        return {
            "ok": True,
            "numericRanking": self.capability,
            "capabilitySource": "pob_runtime",
            "selectedEffectId": "fixture",
        }

    def get_build(self):
        return {"activeWeaponSet": 1}

    def get_stats(self, keys):
        return {"stats": {"TotalDPS": 5 if self.changed else 10, "Life": 100, "Mana": float("nan")}}

    def get_xml(self):
        return self.xml.replace('level="80"', 'level="79"') if self.changed else self.xml

    def ping(self):
        return {"version": "fixture"}

    def unequip_item(self, slot):
        self.changed = True
        return {"ok": True}


@pytest.fixture
def engine(monkeypatch):
    FakeEngine.instances = []
    FakeEngine.capability = "supported"
    FakeEngine.invalid_after = False
    FakeEngine.missing_after = False
    monkeypatch.setattr(measurements, "PobEngine", FakeEngine)
    monkeypatch.setattr(
        measurements.hard_legality,
        "audit_active_build",
        lambda engine, **kwargs: {
            "hardFailures": ["attribute_requirement_unmet"]
            if engine.changed and engine.invalid_after
            else [],
            "checks": {},
        },
    )
    return FakeEngine


def test_independent_processes_and_no_judge_attempt(engine):
    from tests.test_study_workflow import SYNTHETIC_XML

    for _ in range(2):
        result = measurements.measure(
            SYNTHETIC_XML,
            group_index=1,
            skill_name="Fixture",
            locator={"kind": "item", "slot": "Weapon 1"},
        )
        assert result["status"] == "comparable"
        assert result["delta"]["TotalDPS"] == -5
        assert "Mana" not in result["before"]["stats"]
        assert result["attemptConsumed"] is False
    assert len(engine.instances) == 2
    assert all(item.closed for item in engine.instances)


@pytest.mark.parametrize("reason", ["gap", "illegal", "missing"])
def test_unknown_or_invalid_comparison_has_no_delta(engine, reason):
    from tests.test_study_workflow import SYNTHETIC_XML

    engine.capability = "unsupported" if reason == "gap" else "supported"
    engine.invalid_after = reason == "illegal"
    engine.missing_after = reason == "missing"
    result = measurements.measure(
        SYNTHETIC_XML,
        group_index=1,
        skill_name="Fixture",
        locator={"kind": "item", "slot": "Weapon 1"},
    )
    assert result["status"] in {"inconclusive", "output_unavailable"}
    assert "delta" not in result
    assert engine.instances[0].closed


def test_unsupported_mutation_closes_engine(engine):
    from tests.test_study_workflow import SYNTHETIC_XML

    with pytest.raises(storage.StudyError, match="requires_item_or_passive"):
        measurements.measure(
            SYNTHETIC_XML, group_index=1, skill_name="Fixture", locator={"kind": "gem"}
        )
    assert engine.instances[0].closed


def test_import_group_renumbering_requires_explicit_reselection(engine, monkeypatch):
    from tests.test_study_workflow import SYNTHETIC_XML

    monkeypatch.setattr(engine, "select_judge_skill", lambda *a, **k: {"status": "not_found"})
    candidate = {"groupIndex": 2, "activeIndex": 1, "skillName": "Fixture"}
    monkeypatch.setattr(engine, "call", lambda *a, **k: {"candidates": [candidate]})
    result = measurements.measure(SYNTHETIC_XML, group_index=1, skill_name="Fixture")
    assert result["status"] == "selection_required"
    assert result["availableOutputs"][0]["groupIndex"] == 2
    assert "before" not in result and "delta" not in result
    assert result["attemptConsumed"] is False
    assert engine.instances[0].closed
