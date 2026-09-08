"""Real PoB handoffs for stale socket obligations and saved lifecycle declarations."""

from collections import OrderedDict
from copy import deepcopy

import pytest

from server import main
from server.compute import craftopt
from server.compute.pob_xml_input import parse_pob_xml
from server.compute.state import build_state_hash
from server.generation import lifecycle_observation, validation_checkpoint
from server.judge.evaluator import compute_source_hash
from tests.test_server import _artifact_manifest


def setup_engine(engine, monkeypatch, level):
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(level)
    engine.paste_skill("Fireball 1/0 1")
    modifiers = "\n".join(
        [
            "+5000 to maximum Life",
            "+500 to Strength",
            "+500 to Dexterity",
            "+500 to Intelligence",
            "+200% to all Elemental Resistances",
            "Regenerate 1000 Mana per second",
        ]
    )
    engine.set_config(custom_mods=modifiers)
    engine.call("set_skill_group_state", index=1, makeMain=True, activeSkillIndex=1)
    monkeypatch.setattr(main, "get_engine", lambda: engine)
    monkeypatch.setattr(
        engine, lifecycle_observation._SESSION_ATTRIBUTE, OrderedDict(), raising=False
    )
    craftopt._clear_socket_decisions(engine)
    validation_checkpoint.clear_validation_checkpoint_cache()
    return modifiers


def checkpoint():
    result = main.inspect_generation_checkpoint(
        offense_skill_group_index=1, expected_skill_name="Fireball"
    )
    assert result.get("status") != "error", result
    return result


@pytest.mark.parametrize("failed_probe", [False, True])
def test_full_socket_history_requires_current_review_after_config_change(
    engine, monkeypatch, failed_probe
):
    modifiers = setup_engine(engine, monkeypatch, 92)
    assert engine.add_item(
        "Rarity: Rare\nReview Fixture\nSacramental Robe\nItem Level: 82\n--------\n+50 to maximum Life",
        slot="Body Armour",
    )["ok"]
    crafting_options = engine.crafting_options
    choices = crafting_options("Body Armour")["runes"]
    selected = next(row for row in choices if row["name"] == "Iron Rune")
    monkeypatch.setattr(
        engine, "crafting_options", lambda slot: {**crafting_options(slot), "runes": [selected]}
    )
    baseline = craftopt.optimize_item_sockets(
        engine, slot="Body Armour", goals={"EnergyShield": 1}, socket_count=1
    )
    assert baseline["ok"] and baseline["changed"], baseline
    assert main.equip_item(
        raw=baseline["item"],
        slot="Body Armour",
        craft_receipt_ref=baseline["craftReceiptRef"],
    )["ok"]
    selected = next(row for row in choices if row["name"] == "Perfect Iron Rune")
    if failed_probe:
        original_stats = engine.get_stats
        with monkeypatch.context() as failure:
            failure.setattr(engine, "get_stats", lambda keys: {"stats": {}})
            outcome = craftopt.optimize_item_sockets(
                engine, slot="Body Armour", goals={"EnergyShield": 1}, socket_count=1
            )
        assert engine.get_stats == original_stats
        assert not outcome["ok"], outcome
    else:
        outcome = craftopt.optimize_item_sockets(
            engine, slot="Body Armour", goals={"EnergyShield": 1}, socket_count=1
        )
        assert outcome["ok"] and outcome["changed"], outcome
    before = checkpoint()["createQualityChecklist"]["itemSockets"]
    assert before["status"] == "failed" and before["currentAdverseEvidence"] is True
    engine.set_config(custom_mods=modifiers + "\n+1 to Intelligence")
    after = checkpoint()["createQualityChecklist"]["itemSockets"]
    assert after["status"] == "failed", after
    assert after["evidenceFreshness"]["Body Armour"] == "stale"
    assert after["currentAdverseEvidence"] is False
    renewed = craftopt.optimize_item_sockets(
        engine, slot="Body Armour", goals={"EnergyShield": 1}, socket_count=1
    )
    assert renewed["ok"] and renewed["changed"], renewed
    assert main.equip_item(
        raw=renewed["item"],
        slot="Body Armour",
        craft_receipt_ref=renewed["craftReceiptRef"],
    )["ok"]
    complete = checkpoint()["createQualityChecklist"]["itemSockets"]
    assert complete["status"] == "passed" and complete["currentAdverseEvidence"] is False, complete
    engine.unequip_item("Body Armour")
    removed = checkpoint()["createQualityChecklist"]["itemSockets"]
    assert "Body Armour" not in removed["evidenceFreshness"]


@pytest.mark.parametrize("level", [80, 90, 91, 92])
def test_artifact_lifecycle_omitted_state_inherits_inputs_and_empty_revokes(
    engine, monkeypatch, level
):
    setup_engine(engine, monkeypatch, level)
    xml = engine.get_xml()
    expected_hash = build_state_hash(xml)
    gem = next(
        row
        for row in parse_pob_xml(xml).findall("./Skills/SkillSet/Skill/Gem")
        if row.get("nameSpec") == "Fireball"
    )
    key = "skill:" + gem.get("skillId")
    declaration = {
        "buildDefiningComponentKind": "skill",
        "buildDefiningComponentName": "Fireball",
        "buildDefiningComponentKey": key,
        "buildDefiningEvidenceRefs": [key],
    }
    target = {"groupIndex": 1, "activeIndex": 1, "skillName": "Fireball"}
    artifact_id = f"final-build:lifecycle-{level}"
    manifest = _artifact_manifest(artifact_id, compute_source_hash(xml), "Fireball")
    manifest.lifecycle_declaration_binding = {
        "observationVersion": lifecycle_observation.OBSERVATION_VERSION,
        "stateHash": expected_hash,
        "observationTarget": target,
        "declarations": lifecycle_observation.declaration_payload(declaration),
    }
    # Artifact storage/binding has separate public-save tests. Here only the trusted artifact
    # lookup is controlled; PoB, the binding reader, public verifier, receipt writer and gates run.
    monkeypatch.setattr(
        main.generation_artifacts,
        "read_final_build_artifact_for_export",
        lambda value: (manifest, xml) if value == artifact_id else None,
    )
    stage = "endgame_final" if level == 92 else "endgame_budget"
    result = main.verify_lifecycle_stage(stage, artifact_id=artifact_id)
    assert result["pass"] and result["artifactBound"], result
    assert build_state_hash(engine.get_xml()) == expected_hash
    assert checkpoint()["lifecycleVerification"]["pass"]
    saved_binding = deepcopy(manifest.lifecycle_declaration_binding)
    revoked = main.verify_lifecycle_stage(stage, artifact_id=artifact_id, state={})
    repeated = main.verify_lifecycle_stage(stage, artifact_id=artifact_id)
    assert revoked["pass"] is (level == 92), revoked
    assert repeated["pass"] is (level == 92), repeated
    assert manifest.lifecycle_declaration_binding == saved_binding
    assert build_state_hash(engine.get_xml()) == expected_hash
    # The old saved declaration may not cover a different artifact/Judge target.
    manifest.lifecycle_declaration_binding["observationTarget"]["activeIndex"] = 2
    invalid = main.verify_lifecycle_stage(stage, artifact_id=artifact_id)
    assert invalid["errorCode"] == "artifact_lifecycle_declaration_binding_invalid", invalid
    assert build_state_hash(engine.get_xml()) == expected_hash


def test_legacy_artifact_without_declarations_does_not_borrow_a_pass(engine, monkeypatch):
    setup_engine(engine, monkeypatch, 80)
    xml = engine.get_xml()
    manifest = _artifact_manifest("final-build:legacy-state", compute_source_hash(xml), "Fireball")
    monkeypatch.setattr(
        main.generation_artifacts, "read_final_build_artifact_for_export", lambda _: (manifest, xml)
    )
    result = main.verify_lifecycle_stage("endgame_budget", artifact_id=manifest.artifact_id)
    assert result["pass"] is False
    assert "build_defining_component_online" in result["unknownChecks"]
