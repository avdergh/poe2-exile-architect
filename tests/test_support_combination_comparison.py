from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from xml.etree import ElementTree as ET

import pytest

from server.compute import skillgroups, supportopt
from server.compute.state import build_state_hash


@pytest.fixture(autouse=True)
def oracle_subjects(monkeypatch):
    monkeypatch.setattr(
        supportopt,
        "_support_identity_subject",
        lambda name: {"gemIds": ["oracle:" + name], "effectIds": ["effect:" + name]},
    )


class CombinationOracle:
    """Deterministic tool-contract oracle; production still uses PoB for every measurement."""

    def __init__(self, values, current=("Pair A", "Pair B"), *, selected_index=1):
        self.values = values
        self.probes = []
        self.selected_index = selected_index
        self.drop_support = None
        self.change_effect = False
        self.illegal_support = None
        root = ET.Element("PathOfBuilding2")
        ET.SubElement(root, "Build", level="95", mainSocketGroup="1")
        skills = ET.SubElement(root, "Skills", activeSkillSet="1")
        group = ET.SubElement(
            ET.SubElement(skills, "SkillSet", id="1"),
            "Skill",
            mainActiveSkill=str(selected_index),
            mainActiveSkillCalcs=str(selected_index),
            includeInFullDPS="true",
        )
        ET.SubElement(
            group,
            "Gem",
            nameSpec="Spark",
            level="20",
            quality="20",
            enabled="true",
            count="3",
            skillPart="2",
            enableGlobal1="false",
        )
        if selected_index == 2:
            ET.SubElement(
                group,
                "Gem",
                nameSpec="Comet",
                level="20",
                quality="10",
                enabled="true",
                count="2",
                skillMinion="retained",
            )
        for name in current:
            ET.SubElement(group, "Gem", nameSpec=name, level="1", quality="13", enabled="true")
        self.xml = ET.tostring(root, encoding="unicode")

    def transaction_lock(self):
        return nullcontext()

    def get_xml(self):
        return self.xml

    def load_build_xml(self, xml, **_):
        self.xml = xml

    def _gems(self):
        return ET.fromstring(self.xml).findall("./Skills/SkillSet/Skill/Gem")

    def _supports(self):
        return tuple(sorted(gem.get("nameSpec") for gem in self._gems() if gem.get("level") == "1"))

    def get_build(self):
        result = {
            "class": "Sorceress",
            "level": 95,
            "mainSkillGroup": [{"name": "Spark", "level": 20, "quality": 20}],
        }
        if self.illegal_support in self._supports():
            result["attributes"] = {"str": 1, "dex": 1, "int": 1}
            result["attributeRequirements"] = {"str": 100}
        return result

    def get_stats(self, _keys=None):
        supports = self._supports()
        self.probes.append(supports)
        value = self.values.get(supports, 110)
        if isinstance(value, dict):
            return {"stats": {"Life": 100, "LifeReserved": 0, "LifeUnreserved": 100, **deepcopy(value)}}
        return {"stats": {"TotalDPS": value, "ManaCost": 10, "SpiritReserved": 10,
                          "Life": 100, "LifeReserved": 0, "LifeUnreserved": 100}}

    def probe_regular_skill_group(
        self,
        *,
        group_index,
        group_xml,
        active_skill_index,
        expected_skill_name,
        keys,
        objective_keys,
        expected_effect_id=None,
    ):
        root = ET.fromstring(self.xml)
        skill_set = root.find("./Skills/SkillSet")
        old = skill_set.findall("Skill")[group_index - 1]
        skill_set.remove(old)
        skill_set.insert(group_index - 1, ET.fromstring(group_xml))
        self.load_build_xml(ET.tostring(root, encoding="unicode"))
        self.call("set_skill_group_state", index=group_index, activeSkillIndex=active_skill_index)
        return {
            "ok": True,
            "state": self.call("list_skill_groups"),
            "capability": self.call("inspect_support_evaluation_capability"),
            **self.get_stats(keys),
        }

    def call(self, method, **kwargs):
        if method == "resolve_support_gem_identity":
            return {
                "ok": True,
                "status": "resolved",
                "name": kwargs["requestedName"],
                "gemId": "oracle:" + kwargs["requestedName"],
                "gameId": (kwargs.get("gemIds") or [None])[0],
                "effectId": "effect:" + kwargs["requestedName"],
                "naturalMaxLevel": 1,
            }
        if method == "set_skill_group_state":
            self.selected_index = kwargs.get("activeSkillIndex", self.selected_index)
            return {"ok": True}
        if method == "inspect_support_evaluation_capability":
            return {
                "ok": True,
                "applicationCheck": "verified",
                "numericRanking": "supported",
                "triggerRate": "not_applicable",
                "capabilitySource": "pob_runtime",
                "usageConditionContractVersion": 1,
                "usageConditionContracts": [],
            }
        assert method == "list_skill_groups"
        gems = [
            {
                "name": gem.get("nameSpec"),
                "level": int(gem.get("level")),
                "quality": int(gem.get("quality")),
                "isSupport": gem.get("level") == "1",
            }
            for gem in self._gems()
            if gem.get("nameSpec") != self.drop_support
        ]
        active = [
            {"index": index + 1, "name": gem["name"]}
            for index, gem in enumerate(gems)
            if not gem["isSupport"]
        ]
        selected_name = active[self.selected_index - 1]["name"]
        if self.change_effect and "Solo C" in self._supports():
            selected_name = "Other Effect"
        return {
            "mainGroupIndex": 1,
            "groups": [
                {
                    "index": 1,
                    "activeSkill": selected_name,
                    "mainActiveSkillCalcs": self.selected_index,
                    "mainActiveSkill": self.selected_index,
                    "activeSkills": active,
                    "gems": gems,
                }
            ],
        }


def run_oracle(monkeypatch, values=None, *, current=("Pair A", "Pair B"), **kwargs):
    engine = CombinationOracle(
        values
        or {
            (): 100,
            ("Pair A",): 90,
            ("Pair B",): 100,
            ("Solo C",): 110,
            ("Pair A", "Pair B"): 300,
        },
        current,
    )
    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: ["Pair A", "Pair B", "Solo C"])
    before = engine.get_xml()
    result = supportopt.optimize_supports(engine, **kwargs)
    assert engine.get_xml() == before
    return engine, result


def test_life_exhausting_candidate_does_not_hide_a_legal_alternative(monkeypatch):
    _, result = run_oracle(monkeypatch, {
        (): 100, ("Pair A",): 125, ("Pair B",): 105,
        ("Solo C",): {"TotalDPS": 1000, "ManaCost": 10, "SpiritReserved": 0,
                      "Life": 100, "LifeReserved": 100, "LifeUnreserved": 0},
    }, current=())
    assert result['supports'] == ['Pair A']
    assert result['measurement']['candidateRejectionCodes']['life_reservation_exhausts_life'] == 1
    assert result['measurement']['combinationComparison']['candidateConstraintsSatisfied'] is True
    assert result['supportAudit']['positiveGainCombinationAvailable'] is True


def test_agent_availability_correction_replaces_invalid_demand_with_complete_recomparison(monkeypatch):
    from test_gem_availability import valid_review
    key = "Metadata/Items/Gems/SupportGemSyntheticC"
    engine, first = run_oracle(monkeypatch, {():100, ("Pair A",):200, ("Pair B",):150,
                                           ("Solo C",):1000}, current=("Pair A",))
    assert first["supportAudit"]["positiveGainCombinationAvailable"]
    original_subject = supportopt._support_identity_subject
    monkeypatch.setattr(supportopt, "_support_identity_subject", lambda name:
                        {"gemIds":[key],"effectIds":["effect:Solo C"]} if name == "Solo C" else original_subject(name))
    monkeypatch.setattr(supportopt.db, "get_gem", lambda _: {"id":key,"name":"Solo C","gem_type":"support"})
    review = valid_review()
    review["componentKey"] = "gem:"+key
    # Synthetic contract fixture only: no assertion about an actual game's new component.
    before = engine.get_xml()
    engine.probes.clear()
    result = supportopt.optimize_supports(engine, availability_reviews=[review])
    assert result["supportAudit"]["status"] == "passed"
    assert result["supports"] == ["Pair A"]
    assert all("Solo C" not in probe for probe in engine.probes)
    assert result["measurement"]["unavailableInGameCandidates"][0]["evidenceKind"] == "agent_reviewed"
    assert supportopt.support_audit_for_state(engine, result["stateHash"], 1)["auditRef"] == result["supportAudit"]["auditRef"]
    assert engine.get_xml() == before
    # The correction persists only in this engine session; omitting the argument cannot resurrect it.
    repeated = supportopt.optimize_supports(engine)
    assert repeated["supportAudit"]["status"] == "passed"


def test_availability_reviews_are_atomic_and_wrong_patch_does_not_change_state(monkeypatch):
    from test_gem_availability import valid_review
    engine, _ = run_oracle(monkeypatch)
    review = valid_review()
    review["targetPatch"] = "0.2.0"
    before = engine.get_xml()
    result = supportopt.optimize_supports(engine, availability_reviews=[review])
    assert result["errorCode"] == "invalid_support_availability_review"
    assert engine.get_xml() == before
    assert not supportopt.gem_availability.session_reviews(engine)


def test_same_display_name_cannot_authorize_excluding_a_different_runtime_gem(monkeypatch):
    from test_gem_availability import valid_review
    engine, _ = run_oracle(monkeypatch)
    original_call = engine.call
    def wrong_identity(method, **params):
        result = original_call(method, **params)
        if method == "resolve_support_gem_identity":
            result.update(gemId="unrelated-runtime-gem", gameId="unrelated-game-gem")
        return result
    engine.call = wrong_identity
    result = supportopt.optimize_supports(engine, availability_reviews=[valid_review()])
    assert result["errorCode"] == "invalid_support_availability_review"
    assert result["reason"] == "availability_review_runtime_identity_mismatch"
    assert not supportopt.gem_availability.session_reviews(engine)


def test_current_removed_support_gets_a_legal_replacement_even_when_panel_is_lower(monkeypatch):
    key = "Metadata/Items/Gems/SupportGemWindWave"
    original_subject = supportopt._support_identity_subject
    monkeypatch.setattr(supportopt, "_support_identity_subject", lambda name:
                        {"gemIds":[key],"effectIds":["effect:Solo C"]} if name == "Solo C" else original_subject(name))
    _, result = run_oracle(monkeypatch, {():100, ("Pair A",):200, ("Pair B",):150,
                                        ("Solo C",):1000}, current=("Solo C",))
    assert result["supports"] == ["Pair A"]
    assert result["supportAudit"]["currentUnavailableSupports"] == ["Solo C"]
    assert result["supportAudit"]["supportsToRemove"] == ["Solo C"]
    assert result["supportAudit"]["recoveryAction"] == "apply_valid_replacement_and_reaudit"
    assert not result["supportAudit"]["positiveGainCombinationAvailable"]


def test_installed_synergy_is_measured_and_never_replaced_by_inferior_solo(monkeypatch):
    engine, result = run_oracle(monkeypatch)
    assert ("Pair A", "Pair B") in engine.probes
    assert result["supports"] == ["Pair A", "Pair B"]
    assert result["currentValue"] == result["finalValue"] == 300
    assert result["supportAudit"]["status"] == "passed"
    assert result["supportAudit"]["positiveGainSupportsMissing"] == []
    assert result["measurement"]["globalOptimalityProven"] is False


@pytest.mark.parametrize("condition_effect", ["effect:Spark", "effect:Comet"])
def test_usage_condition_added_to_any_group_role_is_not_an_automatic_upgrade(
    monkeypatch, condition_effect
):
    engine = CombinationOracle({(): 100, ("Pair A", "Pair B"): 300, ("Solo C",): 1000})
    original_call = engine.call

    def call(method, **params):
        result = original_call(method, **params)
        if method == "inspect_support_evaluation_capability" and "Solo C" in engine._supports():
            result["usageConditionContracts"] = [
                {"effectId": condition_effect, "supportEffectId": "effect:Solo C"}
            ]
        return result

    engine.call = call
    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: ["Pair A", "Pair B", "Solo C"])
    before = engine.get_xml()
    result = supportopt.optimize_supports(engine)
    assert result["supports"] == ["Pair A", "Pair B"]
    assert result["measurement"]["candidateRejectionCodes"]["support_usage_condition_changed"] == 1
    assert result["supportAudit"]["status"] == "passed"
    assert engine.get_xml() == before


def test_existing_usage_condition_is_preserved_in_minimal_seed_and_full_comparison(monkeypatch):
    engine = CombinationOracle(
        {(): 100, ("Pair A",): 150, ("Pair A", "Pair B"): 300, ("Pair A", "Solo C"): 500,
         ("Solo C",): 1000}
    )
    original_call = engine.call

    def call(method, **params):
        result = original_call(method, **params)
        if method == "inspect_support_evaluation_capability" and "Pair A" in engine._supports():
            result["usageConditionContracts"] = [
                {"effectId": "effect:Spark", "supportEffectId": "effect:Pair A"}
            ]
        return result

    engine.call = call
    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: ["Pair A", "Pair B", "Solo C"])
    before = engine.get_xml()
    result = supportopt.optimize_supports(engine)
    assert set(result["supports"]) == {"Pair A", "Solo C"}
    assert result["measurement"]["preservedUsageConditionSupports"] == ["Pair A"]
    assert result["supportAudit"]["positiveGainCombinationAvailable"] is True
    assert engine.get_xml() == before


def test_missing_usage_contract_cannot_issue_a_numeric_support_pass(monkeypatch):
    engine = CombinationOracle({(): 100, ("Pair A", "Pair B"): 300})
    original_call = engine.call

    def call(method, **params):
        result = original_call(method, **params)
        if method == "inspect_support_evaluation_capability":
            result.pop("usageConditionContractVersion")
        return result

    engine.call = call
    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: ["Pair A", "Pair B"])
    result = supportopt.optimize_supports(engine)
    assert result["supportAudit"]["status"] == "inconclusive"
    assert result["supportAudit"]["positiveGainCombinationAvailable"] is False
    assert "support_usage_condition_evidence_missing" in result["supportAudit"]["reasonCodes"]


def test_positive_solo_is_actionable_only_when_whole_set_beats_current(monkeypatch):
    _, result = run_oracle(monkeypatch, {(): 100, ("Pair A", "Pair B"): 300, ("Solo C",): 400})
    comparison = result["measurement"]["combinationComparison"]
    assert result["supports"] == ["Solo C"]
    assert comparison["netGain"] == 100
    assert comparison["positiveGainProven"] is True
    assert result["supportAudit"]["status"] == "failed"
    assert result["supportAudit"]["positiveGainSupportsMissing"] == ["Solo C"]


def test_solo_neutral_support_can_extend_current_synergy(monkeypatch):
    _, result = run_oracle(
        monkeypatch,
        {(): 100, ("Pair A", "Pair B"): 300, ("Solo C",): 100, ("Pair A", "Pair B", "Solo C"): 450},
    )
    assert result["supports"] == ["Pair A", "Pair B", "Solo C"]
    assert result["supportAudit"]["positiveGainCombinationAvailable"] is True


@pytest.mark.parametrize("alternative", [300, 299, 0])
def test_equal_or_worse_complete_set_has_no_required_upgrade(monkeypatch, alternative):
    _, result = run_oracle(
        monkeypatch, {(): 100, ("Pair A", "Pair B"): 300, ("Solo C",): alternative}
    )
    assert result["supports"] == ["Pair A", "Pair B"]
    assert result["supportAudit"]["status"] == "passed"
    assert result["supportAudit"]["positiveGainSupportsMissing"] == []


@pytest.mark.parametrize("current", [{}, {"TotalDPS": float("nan")}, {"TotalDPS": float("inf")}])
def test_missing_current_measurement_cannot_authorize_positive_gain(monkeypatch, current):
    _, result = run_oracle(monkeypatch, {(): 100, ("Pair A", "Pair B"): current, ("Solo C",): 400})
    assert result["supportAudit"]["status"] == "inconclusive"
    assert result["supportAudit"]["positiveGainSupportsMissing"] == []
    assert result["measurement"]["combinationComparison"]["baselineMeasurable"] is False


@pytest.mark.parametrize(
    "key,limit", [("ManaCost", "max_mana_cost"), ("SpiritReserved", "spirit_limit")]
)
def test_better_damage_with_resource_regression_is_not_an_upgrade(monkeypatch, key, limit):
    _, result = run_oracle(
        monkeypatch,
        {
            (): 100,
            ("Pair A", "Pair B"): 300,
            ("Solo C",): {"TotalDPS": 500, "ManaCost": 10, "SpiritReserved": 10, key: 30},
        },
        **{limit: 20},
    )
    assert result["supports"] == ["Pair A", "Pair B"]
    assert result["supportAudit"]["positiveGainSupportsMissing"] == []


def test_unknown_objective_is_not_checkpoint_authority(monkeypatch):
    _, result = run_oracle(
        monkeypatch,
        {
            (): {"CustomMetric": 100},
            ("Pair A", "Pair B"): {"CustomMetric": 300},
            ("Solo C",): {"CustomMetric": 500},
        },
        metric="CustomMetric",
    )
    assert result["supportAudit"]["status"] == "inconclusive"
    assert not result["supportAudit"]["positiveGainSupportsMissing"]


def test_rejected_whole_character_legality_regression_restores_current_choice(monkeypatch):
    engine = CombinationOracle({(): 100, ("Pair A", "Pair B"): 300, ("Solo C",): 500})
    engine.illegal_support = "Solo C"
    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: ["Solo C"])
    result = supportopt.optimize_supports(engine)
    assert result["supports"] == ["Pair A", "Pair B"]
    assert result["supportAudit"]["status"] == "passed"
    assert result["supportAudit"]["positiveGainSupportsMissing"] == []
    rejected = result["measurement"]["rejectedRecommendation"]
    assert rejected["legalityComparison"]["reasons"][0]["code"] == "attribute_requirement_unmet"


def test_narrow_search_keeps_unscreened_current_combination(monkeypatch):
    _, result = run_oracle(monkeypatch, candidates=1, screen=1, max_supports=1)
    assert result["supports"] == ["Pair A", "Pair B"]
    assert result["currentValue"] == result["finalValue"] == 300
    assert result["supportAudit"]["status"] == "inconclusive"
    assert result["supportAudit"]["positiveGainSupportsMissing"] == []


def test_only_partially_measured_weighted_goal_cannot_prove_gain(monkeypatch):
    _, result = run_oracle(
        monkeypatch,
        {
            (): {"TotalDPS": 100, "TotalEHP": 10},
            ("Pair A", "Pair B"): {"TotalDPS": 300, "TotalEHP": 10},
            ("Solo C",): {"TotalDPS": 500},
        },
        goals={"TotalDPS": 1, "TotalEHP": 1},
    )
    assert result["supportAudit"]["status"] == "inconclusive"
    assert result["supportAudit"]["positiveGainSupportsMissing"] == []


def test_removal_only_improvement_has_explicit_complete_set_decision(monkeypatch):
    _, result = run_oracle(
        monkeypatch,
        {
            (): {"ManaCost": 10},
            ("Pair A", "Pair B"): {"ManaCost": 30},
            ("Solo C",): {"ManaCost": 20},
            ("Pair A", "Pair B", "Solo C"): {"ManaCost": 40},
        },
        metric="ManaCost",
    )
    assert result["supports"] == []
    assert result["supportAudit"]["status"] == "failed"
    assert result["supportAudit"]["positiveGainSupportsMissing"] == []
    assert result["supportAudit"]["positiveGainCombinationAvailable"] is True
    assert result["supportAudit"]["supportsToRemove"] == ["Pair A", "Pair B"]


def test_stats_error_with_numeric_payload_is_not_a_successful_measurement(monkeypatch):
    engine = CombinationOracle({(): 100, ("Pair A", "Pair B"): 300, ("Solo C",): 500})
    original_stats = engine.get_stats

    def failing_stats(keys):
        if "Solo C" in engine._supports():
            return {"ok": False, "stats": {"TotalDPS": 500}}
        return original_stats(keys)

    monkeypatch.setattr(engine, "get_stats", failing_stats)
    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: ["Solo C"])
    result = supportopt.optimize_supports(engine)
    assert result["supportAudit"]["status"] == "inconclusive"
    assert result["supportAudit"]["positiveGainSupportsMissing"] == []
    assert result["measurement"]["failedCandidates"] == 1


def test_carry_rejects_same_names_with_changed_quality(monkeypatch):
    engine, result = run_oracle(monkeypatch, {(): 100, ("Pair A", "Pair B"): 300, ("Solo C",): 400})
    before_hash = result["stateHash"]
    group = engine.call("list_skill_groups")["groups"][0]
    configured = ET.fromstring(
        supportopt._regular_probe_xml(engine.get_xml(), 1, group, result["supports"])
    )
    configured.findall("./Skills/SkillSet/Skill/Gem")[-1].set("quality", "0")
    engine.load_build_xml(ET.tostring(configured, encoding="unicode"))
    assert (
        supportopt.carry_support_audit_to_configured_state(
            engine=engine,
            before_state_hash=before_hash,
            after_state_hash=build_state_hash(engine.get_xml()),
            group_index=1,
            applied_supports=result["supports"],
        )
        is None
    )


def test_selected_effect_and_all_active_gem_settings_survive_each_probe(monkeypatch):
    engine = CombinationOracle({(): 100, ("Pair A", "Pair B"): 300}, selected_index=2)
    original = engine.get_xml()
    originals = [deepcopy(gem.attrib) for gem in engine._gems() if gem.get("level") != "1"]
    original_load = engine.load_build_xml

    def checked_load(xml, **kwargs):
        actual = ET.fromstring(xml).findall("./Skills/SkillSet/Skill/Gem")
        assert [gem.attrib for gem in actual if gem.get("level") != "1"] == originals
        original_load(xml, **kwargs)

    monkeypatch.setattr(engine, "load_build_xml", checked_load)
    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: ["Pair A", "Pair B", "Solo C"])
    result = supportopt.optimize_supports(engine)
    assert result["supportAudit"]["skill"] == "Comet"
    assert result["supportAudit"]["activeSkillIndex"] == 2
    assert result["measurement"]["combinationComparison"]["sameContext"] is True
    assert engine.get_xml() == original


def test_shifted_effect_cannot_supply_comparison_evidence(monkeypatch):
    engine = CombinationOracle({(): 100, ("Pair A", "Pair B"): 300, ("Solo C",): 500})
    engine.change_effect = True
    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: ["Solo C"])
    result = supportopt.optimize_supports(engine)
    assert result["supportAudit"]["status"] == "inconclusive"
    assert not result["supportAudit"]["positiveGainSupportsMissing"]
    assert result["measurement"]["candidateFailureCodes"] == {"support_selected_effect_changed": 1}


def test_carry_rebases_complete_candidate_and_rejects_multiset_drift(monkeypatch):
    engine, result = run_oracle(monkeypatch, {(): 100, ("Pair A", "Pair B"): 300, ("Solo C",): 400})
    original_hash = build_state_hash(engine.get_xml())
    selected_group = engine.call("list_skill_groups")["groups"][0]
    configured_xml = supportopt._regular_probe_xml(
        engine.get_xml(), 1, selected_group, result["supports"]
    )
    engine.load_build_xml(configured_xml)
    configured_hash = build_state_hash(configured_xml)
    assert (
        supportopt.carry_support_audit_to_configured_state(
            engine=engine,
            before_state_hash=original_hash,
            after_state_hash=configured_hash,
            group_index=1,
            applied_supports=["Solo C", "Solo C"],
        )
        is None
    )
    carried = supportopt.carry_support_audit_to_configured_state(
        engine=engine,
        before_state_hash=original_hash,
        after_state_hash=configured_hash,
        group_index=1,
        applied_supports=result["supports"],
    )
    assert carried["status"] == "passed"
    assert carried["measurement"]["combinationComparison"]["netGain"] == 0
    assert (
        carried["measurement"]["combinationComparison"]["baselineMetrics"]
        == carried["measurement"]["combinationComparison"]["candidateMetrics"]
    )


def test_old_audit_is_stale_and_cannot_authorize_checkpoint(monkeypatch):
    engine, result = run_oracle(monkeypatch)
    state_hash = result["stateHash"]
    supportopt._SUPPORT_AUDITS[engine][(state_hash, 1)]["auditVersion"] = "support_audit_v2"
    assert supportopt.support_audit_for_state(engine, state_hash, 1) is None
    assert supportopt.support_audit_freshness(engine, state_hash, 1) == "stale"
    assert not supportopt.support_audit_is_complete(
        supportopt._SUPPORT_AUDITS[engine][(state_hash, 1)]
    )


def test_model_unavailable_candidate_is_excluded_without_claiming_no_gain(monkeypatch):
    engine = CombinationOracle({(): 100, ("Pair A", "Pair B"): 300, ("Solo C",): 400})
    original_call = engine.call

    def directory(method, **params):
        if method == "resolve_support_gem_identity" and params["requestedName"] == "Unavailable":
            assert params["effectIds"] == ["effect:Unavailable"]
            return {"ok": True, "status": "model_unavailable"}
        return original_call(method, **params)

    monkeypatch.setattr(engine, "call", directory)
    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: ["Solo C", "Unavailable"])
    result = supportopt.optimize_supports(engine)
    assert result["supportAudit"]["status"] == "failed"
    assert result["supportAudit"]["positiveGainSupportsMissing"] == ["Solo C"]
    assert result["measurement"]["modelCoverageComplete"] is False
    assert result["measurement"]["searchCoverageScope"] == "runtime_resolvable_support_identities"
    assert result["measurement"]["uncoveredCandidates"][0]["status"] == "model_unavailable"
    assert all("Unavailable" not in supports for supports in engine.probes)


@pytest.mark.parametrize(
    "response",
    [
        {"ok": False},
        {"ok": True, "status": "ambiguous"},
        {"ok": True, "status": "resolved", "name": "Unknown"},
    ],
)
def test_unknown_or_incomplete_directory_response_does_not_authorize_audit(monkeypatch, response):
    engine = CombinationOracle({(): 100, ("Pair A", "Pair B"): 300, ("Solo C",): 400})
    original_call = engine.call

    def directory(method, **params):
        if method == "resolve_support_gem_identity" and params["requestedName"] == "Unknown":
            return response
        return original_call(method, **params)

    monkeypatch.setattr(engine, "call", directory)
    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: ["Solo C", "Unknown"])
    result = supportopt.optimize_supports(engine)
    assert result["supportAudit"]["status"] == "inconclusive"
    assert result["supportAudit"]["positiveGainSupportsMissing"] == []
    assert result["measurement"]["failedCandidates"] == 1


def test_canonical_runtime_name_requires_resolver_stable_identity(monkeypatch):
    engine = CombinationOracle({(): 100, ("Pair A", "Pair B"): 300, ("Canonical",): 400})
    original_call = engine.call

    def directory(method, **params):
        if method == "resolve_support_gem_identity":
            assert params["gemIds"] == ["oracle:Different Display"]
            return {
                "ok": True,
                "status": "resolved",
                "name": "Canonical",
                "gemId": "stable-gem",
                "effectId": "stable-support",
                "naturalMaxLevel": 1,
            }
        return original_call(method, **params)

    monkeypatch.setattr(engine, "call", directory)
    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: ["Different Display"])
    result = supportopt.optimize_supports(engine)
    assert result["supports"] == ["Canonical"]
    assert result["supportGemSettings"][0]["name"] == "Canonical"
    assert result["supportAudit"]["positiveGainSupportsMissing"] == ["Canonical"]


def test_missing_static_identity_is_not_runtime_unavailable(monkeypatch):
    monkeypatch.setattr(
        supportopt, "_support_identity_subject", lambda _: {"gemIds": [], "effectIds": []}
    )
    engine, result = run_oracle(monkeypatch)
    assert result["supportAudit"]["status"] == "inconclusive"
    assert result["measurement"]["modelUnavailableCandidates"] == 0
    assert result["measurement"]["failedCandidates"] == 3


def test_complete_comparison_does_not_require_bare_skill_to_be_modelable(monkeypatch):
    _, result = run_oracle(monkeypatch, {(): {}, ("Pair A", "Pair B"): 300, ("Solo C",): 400})
    assert result["measurement"]["baseMeasurable"] is False
    assert result["measurement"]["currentCombinationMeasurable"] is True
    assert result["supportAudit"]["status"] == "failed"
    assert result["supportAudit"]["positiveGainSupportsMissing"] == ["Solo C"]


def test_explicit_empty_seed_probe_failure_cannot_be_hidden_by_complete_comparisons(monkeypatch):
    engine = CombinationOracle({(): 100, ("Pair A", "Pair B"): 300, ("Solo C",): 400})
    original_probe = engine.probe_regular_skill_group

    def failing_empty_probe(**params):
        gems = ET.fromstring(params["group_xml"]).findall("Gem")
        if not any(gem.get("level") == "1" for gem in gems):
            return {"ok": False, "errorCode": "support_empty_probe_failed"}
        return original_probe(**params)

    monkeypatch.setattr(engine, "probe_regular_skill_group", failing_empty_probe)
    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: ["Pair A", "Pair B", "Solo C"])
    result = supportopt.optimize_supports(engine)
    assert result["measurement"]["combinationComparison"]["status"] == "complete"
    assert result["measurement"]["failedCombinations"] == 1
    assert result["measurement"]["combinationFailureCodes"] == {"support_empty_probe_failed": 1}
    assert result["supportAudit"]["status"] == "inconclusive"
    assert result["supportAudit"]["reasonClass"] == "measurement_error"
    assert result["supportAudit"]["positiveGainSupportsMissing"] == []


def test_multi_active_group_discovers_host_and_selected_payload_supports(monkeypatch):
    engine = CombinationOracle(
        {(): 100, ("Host A",): 120, ("Payload B",): 200, ("Host A", "Payload B"): 300},
        current=(),
        selected_index=2,
    )
    discovered = []

    def screen(skill, _limit):
        discovered.append(skill)
        return {"Spark": ["Host A"], "Comet": ["Payload B"]}[skill]

    monkeypatch.setattr(supportopt, "_screen_set", screen)
    result = supportopt.optimize_supports(engine)
    assert discovered == ["Spark", "Comet"]
    assert set(result["supports"]) == {"Host A", "Payload B"}
    assert result["supportAudit"]["skill"] == "Comet"
    assert result["measurement"]["discoverySkills"] == ["Spark", "Comet"]
    assert [gem["name"] for gem in result["activeGemSettings"]] == ["Spark", "Comet"]
    assert result["measurement"]["totalRelevantCandidates"] == 2


class RetentionSourceOracle(CombinationOracle):
    def __init__(self):
        super().__init__({(): 100, ("Pair A", "Pair B"): 300, ("Solo C",): 400})
        self.later = None

    def call(self, method, **params):
        if (
            method == "inspect_support_evaluation_capability"
            and self.later == "current_capability_error"
        ):
            return {
                "ok": True,
                "numericRanking": "unknown",
                "applicationCheck": "unknown",
                "triggerRate": "unknown",
                "capabilitySource": "pob_runtime",
                "reasonCodes": ["probe_failed"],
            }
        if method == "resolve_support_gem_identity":
            name = params.get("requestedName") or params.get("runtimeName")
            if not name:
                name = params["gemIds"][0].removeprefix("oracle:")
            return {
                "ok": True,
                "status": "resolved",
                "name": name,
                "gemId": "oracle:" + name,
                "effectId": "effect:" + name,
                "naturalMaxLevel": 1,
            }
        if method == "configure_source_skill_supports":
            names = [value.removeprefix("oracle:") for value in params["supportGemIds"]]
            group = self.call("list_skill_groups")["groups"][0]
            self.load_build_xml(supportopt._regular_probe_xml(self.get_xml(), 1, group, names))
            return {"ok": True}
        result = super().call(method, **params)
        if method == "list_skill_groups":
            result["groups"][0].update(source="Tree:1", sourceKind="tree", noSupports=False)
        return result

    def get_stats(self, keys=None):
        if self._supports() == ("Solo C",):
            if self.later == "measurement_error":
                return {"ok": False, "stats": {"TotalDPS": 400}}
            if self.later == "contradiction":
                return {"stats": {"TotalDPS": 100, "ManaCost": 10, "SpiritReserved": 10,
                                  "Life": 100, "LifeReserved": 0, "LifeUnreserved": 100}}
        return super().get_stats(keys)


def retention_source(monkeypatch):
    class Identities:
        @staticmethod
        def gem_ids(name):
            return ["oracle:" + name]

    def gem(name):
        name = name.removeprefix("oracle:")
        return {
            "id": "oracle:" + name,
            "name": name,
            "gem_type": "support",
            "tags": [],
            "grants": [],
        }

    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: ["Pair A", "Pair B", "Solo C"])
    monkeypatch.setattr(supportopt.db, "get_gem", gem)
    monkeypatch.setattr(skillgroups.SkillEquivalenceIndex, "shared", lambda: Identities())
    return RetentionSourceOracle()


def apply_source_recommendation(engine, supports):
    listed = skillgroups.list_skill_groups(engine)
    return skillgroups.configure_source_skill_supports(
        engine,
        source_group_index=1,
        supports=supports,
        expected_fingerprint=listed["groups"][0]["fingerprint"],
        expected_state_hash=listed["stateHash"],
    )


@pytest.mark.parametrize(
    "later,expected_status",
    [
        ("measurement_error", "inconclusive"),
        ("contradiction", "passed"),
        ("current_capability_error", "inconclusive"),
    ],
)
@pytest.mark.parametrize("previously_carried", [False, True])
def test_latest_same_context_evidence_revokes_old_public_carry(
    monkeypatch, later, expected_status, previously_carried
):
    from test_support_checkpoint_contract import _support_check

    engine = retention_source(monkeypatch)
    original_xml = engine.get_xml()
    first = supportopt.optimize_supports(engine)
    assert first["supportAudit"]["status"] == "failed"
    if previously_carried:
        prior = apply_source_recommendation(engine, first["supports"])
        assert prior["supportAudit"]["status"] == "passed"
        engine.load_build_xml(original_xml)
    engine.later = later
    latest = supportopt.optimize_supports(engine)
    retained = supportopt.support_audit_for_state(engine, first["stateHash"], 1)
    assert retained["auditRef"] == latest["supportAudit"]["auditRef"]
    assert retained["status"] == expected_status
    assert retained["supersededAuditDiagnostics"][0]["candidateScore"] == 400
    applied = apply_source_recommendation(engine, first["supports"])
    assert applied["ok"] is True
    assert applied["supportAudit"] is None
    assert _support_check(engine)["status"] == "failed"
    if previously_carried:
        old_carried = supportopt.support_audit_for_state(
            engine, build_state_hash(engine.get_xml()), 1
        )
        assert old_carried["authorizationRevoked"] is True
        assert not supportopt.support_audit_is_complete(old_carried)


@pytest.mark.parametrize(
    "later_query",
    [
        {"screen": 1, "candidates": 1, "max_supports": 1},
        {"metric": "ManaCost"},
        {"goals": {"TotalDPS": 1}},
        {"max_mana_cost": 20},
    ],
)
def test_narrow_or_different_objective_does_not_erase_proved_improvement(monkeypatch, later_query):
    engine = retention_source(monkeypatch)
    first = supportopt.optimize_supports(engine)
    later = supportopt.optimize_supports(engine, **later_query)
    assert later["supportAudit"]["auditRef"] != first["supportAudit"]["auditRef"]
    retained = supportopt.support_audit_for_state(engine, first["stateHash"], 1)
    assert retained["auditRef"] == first["supportAudit"]["auditRef"]
    assert retained["status"] == "failed"
    applied = apply_source_recommendation(engine, first["supports"])
    assert applied["supportAudit"]["status"] == "passed"
    assert applied["supportAudit"]["measurement"]["combinationComparison"]["baselineScore"] == 400


def test_invalidated_origin_can_gain_fresh_authority_after_successful_recheck(monkeypatch):
    engine = retention_source(monkeypatch)
    first = supportopt.optimize_supports(engine)
    engine.later = "measurement_error"
    supportopt.optimize_supports(engine)
    engine.later = None
    refreshed = supportopt.optimize_supports(engine)
    assert refreshed["supportAudit"]["status"] == "failed"
    assert len(refreshed["supportAudit"]["supersededAuditDiagnostics"]) == 2
    applied = apply_source_recommendation(engine, first["supports"])
    assert applied["supportAudit"]["status"] == "passed"


def test_different_full_discovery_scope_does_not_disprove_an_unvisited_recommendation(monkeypatch):
    engine = retention_source(monkeypatch)
    first = supportopt.optimize_supports(engine)
    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: ["Pair A", "Pair B", "Unrelated"])
    later = supportopt.optimize_supports(engine)
    assert later["measurement"]["coverageComplete"] is True
    assert later["measurement"]["searchScopeHash"] != first["measurement"]["searchScopeHash"]
    assert (
        supportopt.support_audit_for_state(engine, first["stateHash"], 1)["auditRef"]
        == first["supportAudit"]["auditRef"]
    )
    assert (
        apply_source_recommendation(engine, first["supports"])["supportAudit"]["status"] == "passed"
    )
