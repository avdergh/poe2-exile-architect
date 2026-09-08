"""C3 用合成 PoB 状态验证 public lifecycle 与 checkpoint 的同状态证据复用。"""

from collections import OrderedDict

import pytest

from server import main
from server.compute.pob_xml_input import parse_pob_xml
from server.compute.state import build_state_hash
from server.generation import lifecycle_observation, validation_checkpoint


@pytest.mark.parametrize("level", [80, 92])
def test_real_pob_lifecycle_refreshes_cached_checkpoint_for_exact_skill(
    engine, monkeypatch, level
):
    engine.new_build()
    engine.set_class("Sorceress", "Stormweaver")
    engine.set_level(level)
    fireball_group = engine.paste_skill("Fireball 1/0 1")
    spark_group = engine.add_skill_group("Spark 1/0 1")
    assert fireball_group.get("ok") is not False, fireball_group
    assert spark_group.get("ok") is not False, spark_group
    engine.set_config(custom_mods="\n".join([
        "+5000 to maximum Life",
        "+500 to Strength",
        "+500 to Dexterity",
        "+500 to Intelligence",
        "+200% to all Elemental Resistances",
        "Regenerate 1000 Mana per second",
    ]))
    selected = engine.call(
        "set_skill_group_state", index=1, makeMain=True, activeSkillIndex=1
    )
    assert selected["ok"] is True, selected
    monkeypatch.setattr(main, "get_engine", lambda: engine)
    monkeypatch.setattr(
        engine, lifecycle_observation._SESSION_ATTRIBUTE, OrderedDict(), raising=False
    )
    # 辅助/珠宝/镶嵌优化不属于本回归；PoB 读数、硬合法性、选择与 lifecycle gate 均真实执行。
    monkeypatch.setattr(
        validation_checkpoint,
        "_create_quality_checklist",
        lambda **_kwargs: {},
    )
    validation_checkpoint.clear_validation_checkpoint_cache()
    snapshot = engine.get_xml()
    snapshot_hash = build_state_hash(snapshot)
    fireball = next(
        gem for gem in parse_pob_xml(snapshot).findall("./Skills/SkillSet/Skill/Gem")
        if gem.get("nameSpec") == "Fireball"
    )
    assert fireball.get("skillId")
    component_key = f"skill:{fireball.get('skillId')}"
    declaration = {
        "buildDefiningComponentKind": "skill",
        "buildDefiningComponentName": "Fireball",
        "buildDefiningComponentKey": component_key,
        "buildDefiningEvidenceRefs": [component_key],
    }
    selector = {"offense_skill_group_index": 1, "expected_skill_name": "Fireball"}

    before = main.inspect_generation_checkpoint(**selector)
    assert before.get("status") != "error", before
    assert before["sameStateVerified"] is True
    assert before["stats"]["Life"] >= 4500
    assert before["defenses"]["resistances"]["fire"] >= 60
    assert before["lifecycleVerification"]["mechanismDeclarationAvailable"] is False
    if level == 80:
        assert before["lifecycleVerification"]["status"] == "unknown"
        assert before["lifecycleVerification"]["unknownChecks"] == ["build_defining_component_online"]
    else:
        # 92 级原合同不要求 budget 阶段组件；本回归不改变该 gate。
        assert before["lifecycleVerification"]["pass"] is True
    assert build_state_hash(engine.get_xml()) == snapshot_hash

    verified = main.verify_lifecycle_stage(
        before["lifecycleVerification"]["stage"],
        state=declaration,
        detail="full",
        **selector,
    )
    assert verified["pass"] is True, verified
    assert verified["stateSnapshot"]["buildDefiningComponent"]["verified"] is True
    assert verified["stateSnapshot"]["mechanismObservation"]["stateHash"] == snapshot_hash
    assert build_state_hash(engine.get_xml()) == snapshot_hash

    after = main.inspect_generation_checkpoint(**selector)
    assert after["cacheHit"] is True
    assert after["stateHash"] == snapshot_hash
    assert after["stats"] == before["stats"]
    assert after["defenses"] == before["defenses"]
    assert after["lifecycleVerification"]["mechanismDeclarationAvailable"] is True
    assert after["lifecycleVerification"]["pass"] is True
    assert after["lifecycleVerification"]["requiredChecks"] == verified["requiredChecks"]
    assert after["lifecycleVerification"]["observationTarget"] == verified["observationTarget"]
    assert build_state_hash(engine.get_xml()) == snapshot_hash

    wrong_name = main.verify_lifecycle_stage(
        before["lifecycleVerification"]["stage"], state=declaration,
        offense_skill_group_index=1, expected_skill_name="Spark",
    )
    assert wrong_name["pass"] is False
    assert wrong_name["errorCode"] == "lifecycle_observation_target_conflict"
    assert build_state_hash(engine.get_xml()) == snapshot_hash
    other_output = main.inspect_generation_checkpoint(
        offense_skill_group_index=2, expected_skill_name="Spark"
    )
    assert other_output.get("status") != "error", other_output
    assert other_output["calculationContext"]["groupIndex"] == 2
    assert other_output["lifecycleVerification"]["mechanismDeclarationAvailable"] is False
    if level == 80:
        assert other_output["lifecycleVerification"]["unknownChecks"] == ["build_defining_component_online"]
    assert build_state_hash(engine.get_xml()) == snapshot_hash
    validation_checkpoint.clear_validation_checkpoint_cache()
