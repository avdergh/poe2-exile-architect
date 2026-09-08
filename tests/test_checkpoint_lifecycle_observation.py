from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from server.compute.state import build_state_hash
from server.generation import lifecycle_observation, validation_checkpoint
from server.knowledge import lifecycle_verification


TARGET = {"groupIndex": 1, "activeIndex": 1, "skillName": "Whirling Assault"}
DECLARATION = {
    "buildDefiningComponentKind": "skill",
    "buildDefiningComponentName": "Whirling Assault",
    "buildDefiningComponentKey": "skill:WhirlingAssaultPlayer",
    "buildDefiningEvidenceRefs": ["skill:WhirlingAssaultPlayer", "dq-0123456789abcdef"],
}


class ObservationEngine:
    def __init__(self, level=90):
        self.level = level
        self.selected = 1
        self.xml = f'''<PathOfBuilding>
          <Build className="Monk" ascendClassName="Martial Artist" level="{level}"
            mainSocketGroup="1"/>
          <Skills activeSkillSet="1"><SkillSet id="1">
            <Skill enabled="true"><Gem nameSpec="Whirling Assault"
              skillId="WhirlingAssaultPlayer"/></Skill>
            <Skill enabled="true"><Gem nameSpec="Tempest Bell"
              skillId="TempestBellPlayer"/></Skill>
          </SkillSet></Skills></PathOfBuilding>'''
        self.numeric_reads = 0

    def transaction_lock(self):
        return nullcontext()

    def get_xml(self):
        return self.xml

    def get_build(self):
        return {"level": self.level, "mainSkill": "Whirling Assault", "gear": {}}

    def get_stats(self, _keys):
        self.numeric_reads += 1
        return {"stats": {
            "Life": 5000,
            "Mana": 600,
            "ManaUnreserved": 600,
            "ManaCost": 20,
            "Speed": 2,
            "NetManaRegen": 60,
            "TotalDPS": 10000,
        }}

    def get_defenses(self):
        return {
            "resistances": {"fire": 75, "cold": 75, "lightning": 75},
            "totalEHP": 25000 if self.selected == 1 else 500,
        }

    def call(self, method, **params):
        assert method == "set_skill_group_state"
        self.selected = params["index"]
        self.xml = self.xml.replace('mainSocketGroup="1"', f'mainSocketGroup="{self.selected}"')
        return {"ok": True}

    def load_build_xml(self, xml, name=""):
        self.xml = xml
        self.selected = 1
        return {"ok": True}


@pytest.fixture(autouse=True)
def isolated_checkpoints(monkeypatch):
    validation_checkpoint.clear_validation_checkpoint_cache()
    monkeypatch.setattr(
        validation_checkpoint.completeness,
        "inspect_build_completeness",
        lambda *_args, **_kwargs: {"hardFailures": []},
    )
    monkeypatch.setattr(
        validation_checkpoint.preflight,
        "inspect_generation_snapshot",
        lambda *_args, **_kwargs: {
            "readyForJudge": True,
            "hardLegalityReady": True,
            "mechanismReady": True,
            "skillGroups": [
                {"groupIndex": 1, "role": "pob_main_group", "activeSkills": ["Whirling Assault"]},
                {"groupIndex": 2, "role": "additional_skill_group", "activeSkills": ["Tempest Bell"]},
            ],
        },
    )
    monkeypatch.setattr(
        validation_checkpoint,
        "_create_quality_checklist",
        lambda **_kwargs: {"skillSupportAudit": {"status": "passed", "reasons": []}},
    )
    yield
    validation_checkpoint.clear_validation_checkpoint_cache()


def _remember(engine, declaration=None, target=None):
    return lifecycle_observation.remember_state(
        engine,
        state_hash=build_state_hash(engine.get_xml()),
        observation_target=target or TARGET,
        state=DECLARATION if declaration is None else declaration,
    )


@pytest.mark.parametrize("level", [80, 90, 91, 92])
def test_checkpoint_and_formal_lifecycle_share_declared_snapshot_mechanism(level):
    engine = ObservationEngine(level)
    first = validation_checkpoint.inspect_generation_checkpoint(engine)
    if level < 92:
        assert first["deliveryStatus"] == "candidate"
        assert first["lifecycleVerification"]["unknownChecks"] == ["build_defining_component_online"]
    _remember(engine)
    second = validation_checkpoint.inspect_generation_checkpoint(engine)
    assert second["cacheHit"] is True
    assert engine.numeric_reads == 1
    effective = lifecycle_observation.observe_state(
        engine.get_xml(), build=engine.get_build(), observation_target=TARGET, state=DECLARATION
    )
    formal = lifecycle_verification.verify_stage_metrics(
        second["lifecycleVerification"]["stage"],
        stats=second["stats"],
        defenses=second["defenses"],
        state=effective,
    )
    assert second["lifecycleVerification"]["requiredChecks"] == formal["requiredChecks"]
    assert formal["pass"] is True
    assert second["deliveryStatus"] == "recommended"
    assert second["lifecycleVerification"]["stateHash"] == build_state_hash(engine.get_xml())
    assert second["lifecycleVerification"]["observationTarget"] == TARGET


@pytest.mark.parametrize("changed_target", [
    {"groupIndex": 2, "activeIndex": 1, "skillName": "Whirling Assault"},
    {"groupIndex": 1, "activeIndex": 2, "skillName": "Whirling Assault"},
    {"groupIndex": 1, "activeIndex": 1, "skillName": "Tempest Bell"},
])
def test_declaration_isolation_includes_exact_output_target(changed_target):
    engine = ObservationEngine()
    _remember(engine)
    assert lifecycle_observation.state_for_target(
        engine, state_hash=build_state_hash(engine.get_xml()), observation_target=changed_target
    ) is None


def test_declarations_do_not_cross_engine_or_semantic_state():
    engine = ObservationEngine()
    _remember(engine)
    other = ObservationEngine()
    validation_checkpoint.inspect_generation_checkpoint(engine)
    assert validation_checkpoint.inspect_generation_checkpoint(other)["deliveryStatus"] == "candidate"
    changed_hash = build_state_hash(engine.get_xml().replace('level="90"', 'level="91"'))
    assert lifecycle_observation.state_for_target(
        engine, state_hash=changed_hash, observation_target=TARGET
    ) is None


@pytest.mark.parametrize("replacement, expected_status", [
    ({}, "unknown"),
    ({**DECLARATION, "buildDefiningComponentName": "Absent Skill"}, "failed"),
])
def test_reobservation_replaces_old_declarations_instead_of_preserving_pass(replacement, expected_status):
    engine = ObservationEngine()
    _remember(engine)
    assert validation_checkpoint.inspect_generation_checkpoint(engine)["deliveryStatus"] == "recommended"
    _remember(engine, replacement)
    refreshed = validation_checkpoint.inspect_generation_checkpoint(engine)
    assert refreshed["cacheHit"] is True
    assert refreshed["deliveryStatus"] == "candidate"
    assert refreshed["lifecycleVerification"]["status"] == expected_status


def test_lifecycle_success_does_not_upgrade_an_independent_quality_gap(monkeypatch):
    engine = ObservationEngine()
    _remember(engine)
    monkeypatch.setattr(
        validation_checkpoint, "_create_quality_checklist",
        lambda **_kwargs: {"skillSupportAudit": {"status": "unknown", "reasons": ["capability_gap"]}},
    )
    checkpoint = validation_checkpoint.inspect_generation_checkpoint(engine)
    assert checkpoint["lifecycleVerification"]["pass"] is True
    assert checkpoint["deliveryStatus"] == "candidate"


def test_selected_output_defenses_are_read_before_selector_restore():
    engine = ObservationEngine(92)
    checkpoint = validation_checkpoint.inspect_generation_checkpoint(
        engine, offense_skill_group_index=2, expected_skill_name="Tempest Bell"
    )
    assert checkpoint["defenses"]["totalEHP"] == 500
    assert checkpoint["calculationContext"]["groupIndex"] == 2
    assert checkpoint["lifecycleVerification"]["observationTarget"]["groupIndex"] == 2
    assert engine.selected == 1


def test_actual_snapshot_level_and_flask_presence_override_caller_hints():
    engine = ObservationEngine(80)
    state = lifecycle_observation.observe_state(
        engine.get_xml(), build={"level": 92}, observation_target=TARGET,
        state={**DECLARATION, "level": 99, "manaFlaskEquipped": True},
    )
    assert state["level"] == 80
    assert state["manaFlaskEquipped"] is False
    assert state["buildDefiningComponent"]["verified"] is True


def test_unknown_fields_and_incomplete_declarations_remain_strictly_typed():
    engine = ObservationEngine()
    for payload in (
        {"unrecognizedEvidence": True},
        {"buildDefiningComponentKind": "skill"},
        {"manaFlaskEquipped": "true"},
    ):
        with pytest.raises(ValidationError):
            _remember(engine, payload)
    assert lifecycle_observation.state_for_target(
        engine, state_hash=build_state_hash(engine.get_xml()), observation_target=TARGET
    ) is None


@pytest.mark.parametrize("socketed", [False, True])
@pytest.mark.parametrize("caller_claim", [False, True])
def test_legacy_observation_booleans_are_reobserved_and_never_cached(socketed, caller_claim):
    engine = ObservationEngine()
    if not socketed:
        engine.xml = engine.xml.replace('enabled="true"', 'enabled="false"')
    payload = {
        **DECLARATION,
        "mainSkillSocketed": caller_claim,
        "main_skill_socketed": caller_claim,
        "mainSkillSocketEvidence": {"socketed": caller_claim, "activeSkills": ["Fake Skill"]},
        "main_skill_socket_evidence": {"socketed": caller_claim},
        "ascendancyOrKeySupport": {"verified": caller_claim},
        "ascendancy_or_key_support": {"verified": caller_claim},
        "singleTargetDuty": {"verified": caller_claim},
        "single_target_duty": {"verified": caller_claim},
        "buildDefiningComponent": {"verified": caller_claim},
        "build_defining_component": {"verified": caller_claim},
        "mechanismObservation": {"stateHash": "fake:state"},
        "mechanism_observation": {"stateHash": "fake:state"},
        "manaFlaskEquipped": caller_claim,
    }
    observed = lifecycle_observation.observe_state(
        engine.get_xml(), build=engine.get_build(), observation_target=TARGET, state=payload
    )
    assert observed["mainSkillSocketed"] is socketed
    assert observed["mainSkillSocketEvidence"]["socketed"] is socketed
    assert "Fake Skill" not in observed["mainSkillSocketEvidence"].get("activeSkills", [])
    assert observed["buildDefiningComponent"]["verified"] is socketed
    assert observed["manaFlaskEquipped"] is False
    assert observed["mechanismObservation"]["stateHash"] == build_state_hash(engine.get_xml())
    _remember(engine, payload)
    cached = lifecycle_observation.state_for_target(
        engine, state_hash=build_state_hash(engine.get_xml()), observation_target=TARGET
    )
    assert cached == lifecycle_observation.declaration_payload(DECLARATION)
    assert not (lifecycle_observation._DERIVED_STATE_FIELDS & cached.keys())
    assert "manaFlaskEquipped" not in cached
    assert "verified" not in json.dumps(cached)


def test_legacy_component_boolean_does_not_substitute_for_a_declaration():
    engine = ObservationEngine()
    observed = lifecycle_observation.observe_state(
        engine.get_xml(), build=engine.get_build(), observation_target=TARGET,
        state={"buildDefiningComponent": {"verified": True}},
    )
    assert observed["buildDefiningComponent"]["verified"] is None
    assert observed["buildDefiningComponent"]["componentKey"] is None


def test_session_declarations_are_bounded_copied_and_raw_free():
    engine = ObservationEngine()
    declaration = deepcopy(DECLARATION)
    _remember(engine, declaration)
    declaration["buildDefiningEvidenceRefs"].append("fake:later")
    copied = lifecycle_observation.state_for_target(
        engine, state_hash=build_state_hash(engine.get_xml()), observation_target=TARGET
    )
    assert copied == lifecycle_observation.declaration_payload(DECLARATION)
    assert "PathOfBuilding" not in json.dumps(copied)
    assert "verified" not in json.dumps(copied)
    for index in range(60):
        lifecycle_observation.remember_state(
            engine, state_hash=f"test-state:{index}", observation_target=TARGET, state=DECLARATION
        )
    assert lifecycle_observation.state_for_target(
        engine, state_hash=build_state_hash(engine.get_xml()), observation_target=TARGET
    ) is None
    assert len(getattr(engine, lifecycle_observation._SESSION_ATTRIBUTE)) == 48
