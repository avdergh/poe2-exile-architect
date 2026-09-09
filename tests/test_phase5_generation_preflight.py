from __future__ import annotations

from copy import deepcopy

import pytest

from server.generation import preflight


def _xml(groups: str) -> str:
    return f"""<PathOfBuilding>
  <Build className="Monk" ascendClassName="Martial Artist" level="70" mainSocketGroup="1" />
  <Skills activeSkillSet="1"><SkillSet id="1">{groups}</SkillSet></Skills>
  <Items activeItemSet="1"><ItemSet id="1" /></Items>
</PathOfBuilding>"""


def _group(
    active_name: str = "Tempest Flurry",
    active_id: str = "SkillGemTempestFlurry",
    supports: tuple[tuple[str, str], ...] = (("Mana Leech", "SupportGemManaLeech"),),
    *,
    enabled: bool = True,
) -> str:
    support_xml = "".join(
        f'<Gem nameSpec="{name}" gemId="Metadata/Items/Gems/{gem_id}" skillId="Support{name.replace(" ", "")}Player" />'
        for name, gem_id in supports
    )
    return (
        f'<Skill enabled="{str(enabled).lower()}">'
        f'<Gem nameSpec="{active_name}" gemId="Metadata/Items/Gems/{active_id}" skillId="{active_id}Player" />'
        f"{support_xml}</Skill>"
    )


class _Engine:
    def __init__(
        self,
        xml: str,
        *,
        build: dict[str, object] | None = None,
        resistances: dict[str, float] | None = None,
    ) -> None:
        self.xml = xml
        self.xml_reads = 0
        self.build = {
            "class": "Monk",
            "level": 70,
            "gear": {},
            "spiritAvailable": 100,
            "spiritReservedCapped": 81,
            "spiritUnreserved": 19,
            "spiritRequested": 81,
            "spiritOverBy": 0,
            "spiritUsed": 81,
            "activeWeaponSet": 1,
            "unspentPoints": 0,
            **(build or {}),
        }
        self.resistances = resistances or {
            "fire": 75,
            "cold": 75,
            "lightning": 75,
            "chaos": 75,
        }

    def get_xml(self) -> str:
        self.xml_reads += 1
        return self.xml

    def get_build(self) -> dict[str, object]:
        return self.build

    def list_jewel_sockets(self) -> dict[str, object]:
        return {"sockets": []}

    def get_defenses(self) -> dict[str, object]:
        return {"resistances": self.resistances}


def test_preflight_blocks_exact_duplicate_enabled_group_from_one_snapshot():
    engine = _Engine(_xml(_group() + _group()))

    result = preflight.inspect_generation_preflight(engine)

    assert result["readyForJudge"] is False
    assert result["blockingIssues"] == ["duplicate_enabled_skill_group"]
    assert result["duplicateGroupIndices"] == [1, 2]
    assert result["feedbackMode"] == "hard_only"
    assert result["subjectiveFeedbackSuppressed"] is True
    assert engine.xml_reads == 1


def test_preflight_allows_same_active_skill_with_different_support_responsibility():
    groups = _group() + _group(supports=(("Life Leech II", "SupportGemLifeLeechPlayer2"),))

    result = preflight.inspect_generation_preflight(_Engine(_xml(groups)))

    assert result["readyForJudge"] is True
    assert "duplicate_enabled_skill_group" not in result["blockingIssues"]


def test_preflight_ignores_disabled_duplicate_group():
    result = preflight.inspect_generation_preflight(_Engine(_xml(_group() + _group(enabled=False))))

    assert result["readyForJudge"] is True
    assert len(result["skillGroups"]) == 1


def test_preflight_blocks_multi_active_and_duplicate_supports():
    group = _group(supports=(("Mana Leech", "SupportGemManaLeech"),) * 2).replace(
        "</Skill>",
        '<Gem nameSpec="Tempest Bell" gemId="Metadata/Items/Gems/SkillGemTempestBell" skillId="TempestBellPlayer" /></Skill>',
    )

    result = preflight.inspect_generation_preflight(_Engine(_xml(group)))

    assert result["readyForJudge"] is False
    assert result["blockingIssues"] == ["invalid_socket_setup", "duplicate_support_gem"]


def test_preflight_blocks_active_gem_above_character_requirement():
    build = {
        "class": "Monk",
        "level": 75,
        "gear": {},
        "activeSkillGemLevelViolations": [
            {
                "groupIndex": 1,
                "name": "Storm Wave",
                "gemLevel": 20,
                "requiredLevel": 90,
                "characterLevel": 75,
                "maximumLegalLevel": 17,
            }
        ],
    }

    result = preflight.inspect_generation_preflight(_Engine(_xml(_group()), build=build))

    assert result["readyForJudge"] is False
    assert "active_skill_gem_level_requirement_unmet" in result["blockingIssues"]


def test_preflight_enforces_final_create_completion_gates():
    engine = _Engine(
        _xml(_group()),
        build={
            "spiritAvailable": 100,
            "spiritReservedCapped": 80,
            "spiritUnreserved": 20,
            "spiritRequested": 80,
            "spiritUsed": 80,
            "unspentPoints": 1,
        },
    )
    engine.list_jewel_sockets = lambda: {
        "sockets": [{"socket": 1, "allocated": True, "filled": False}]
    }

    result = preflight.inspect_generation_preflight(engine)

    assert result["readyForJudge"] is False
    assert "spirit_utilization_not_above_80_percent" not in result["blockingIssues"]
    assert "unspent_passive_points_remaining" in result["blockingIssues"]
    assert "allocated_passive_jewel_socket_empty" in result["blockingIssues"]


def test_preflight_blocks_endgame_resistance_gate_without_consuming_judge():
    engine = _Engine(
        _xml(_group()),
        build={
            "class": "Monk",
            "ascendancy": "Martial Artist",
            "level": 85,
            "gear": {
                "Flask 1": {"name": "Fixture Unique Life Flask", "rarity": "unique"},
                "Flask 2": {
                    "name": "Fixture Magic Mana Flask",
                    "rarity": "magic",
                    "itemLevel": 82,
                    "affixPrefixes": 1,
                    "affixSuffixes": 1,
                    "affixLegality": {"ok": True, "issues": []},
                },
            },
        },
        resistances={"fire": 60, "cold": 59, "lightning": 60, "chaos": 29},
    )

    result = preflight.inspect_generation_preflight(engine)

    assert result["readyForJudge"] is False
    assert result["readinessReady"] is False
    assert result["blockingIssues"] == [
        "endgame_elemental_resistance_below_60",
        "endgame_chaos_resistance_below_30",
    ]
    assert result["readinessGates"]["endgameResistances"]["belowElemental"] == ["cold"]


def test_main_skill_socket_evidence_uses_active_main_group():
    result = preflight.inspect_main_skill_socketed(_xml(_group(active_name="Glacial Cascade")))

    assert result == {
        "status": "passed",
        "socketed": True,
        "groupIndex": 1,
        "activeSkillCount": 1,
        "activeSkills": ["Glacial Cascade"],
    }


def test_main_skill_socket_evidence_rejects_missing_active_main_group():
    result = preflight.inspect_main_skill_socketed(_xml(_group(enabled=False)))

    assert result["status"] == "failed"
    assert result["socketed"] is False
    assert result["errorCode"] == "missing_active_skill_group"


def test_lifecycle_skill_evidence_reads_ascendancy_supports_and_named_duty():
    groups = _group(active_name="Storm Wave") + _group(
        active_name="Tempest Bell",
        active_id="SkillGemTempestBell",
    )

    result = preflight.inspect_lifecycle_skill_evidence(
        _xml(groups),
        single_target_skill_name="Tempest Bell",
    )

    assert result["ascendancyOrKeySupport"] == {
        "verified": True,
        "ascendancy": "Martial Artist",
        "ascendancyActive": True,
        "mainGroupSupportCount": 1,
    }
    assert result["singleTargetDuty"] == {
        "verified": True,
        "requestedSkillName": "Tempest Bell",
        "matchedSkillName": "Tempest Bell",
        "groupIndex": 2,
        "role": "additional_skill_group",
    }


def test_resource_model_gap_detects_mana_remnants_skill_group():
    groups = _group(active_name="Ice Shot", active_id="SkillGemIceShot") + _group(
        active_name="Mana Remnants",
        active_id="SkillGemManaRemnants",
    )

    result = preflight.inspect_resource_model_gap(_xml(groups), {})

    assert result["detected"] is True
    assert "mana_remnants" in result["mechanismKeys"]
    assert "Mana Remnants" in result["mechanismNames"]
    assert result["evidenceSource"] == "active_snapshot_and_gear_readback"


def test_resource_model_gap_detects_lavianga_spirits_flask():
    gear = {
        "Flask 1": {"name": "Ultimate Life Flask", "base": "Ultimate Life Flask"},
        "Flask 2": {
            "name": "Lavianga's Spirits",
            "base": "Gargantuan Mana Flask",
        },
    }

    result = preflight.inspect_resource_model_gap(_xml(_group()), gear)

    assert result["detected"] is True
    assert "lavianga_spirits" in result["mechanismKeys"]
    assert result["mechanismNames"] == ["Lavianga's Spirits"]


def test_resource_model_gap_empty_without_unmodelled_mechanisms():
    gear = {
        "Flask 1": {"name": "Ultimate Life Flask", "base": "Ultimate Life Flask"},
        "Flask 2": {"name": "Ultimate Mana Flask", "base": "Ultimate Mana Flask"},
    }

    result = preflight.inspect_resource_model_gap(_xml(_group()), gear)

    assert result["detected"] is False
    assert result["mechanismKeys"] == []
    assert result["mechanismNames"] == []


def test_lifecycle_skill_evidence_does_not_accept_unmatched_named_duty():
    result = preflight.inspect_lifecycle_skill_evidence(
        _xml(_group(active_name="Storm Wave")),
        single_target_skill_name="Tempest Bell",
    )

    assert result["singleTargetDuty"]["verified"] is False
    assert result["singleTargetDuty"]["matchedSkillName"] == ""


def test_lifecycle_component_evidence_matches_enabled_skill_and_ascendancy():
    xml = _xml(_group(active_name="Whirling Assault"))

    skill = preflight.inspect_lifecycle_component_evidence(
        xml,
        component_kind="skill",
        component_name="Whirling Assault",
    )
    ascendancy = preflight.inspect_lifecycle_component_evidence(
        xml,
        component_kind="ascendancy",
        component_name="Martial Artist",
    )

    assert skill == {
        "verified": True,
        "kind": "skill",
        "requestedName": "Whirling Assault",
        "matchedName": "Whirling Assault",
        "groupIndex": 1,
        "role": "pob_main_group",
    }
    assert ascendancy["verified"] is True
    assert ascendancy["matchedName"] == "Martial Artist"


def test_lifecycle_component_evidence_matches_only_equipped_active_set_item():
    xml = _xml(_group()).replace(
        '<Items activeItemSet="1"><ItemSet id="1" /></Items>',
        """<Items activeItemSet="1">
    <Item id="1">Rarity: UNIQUE
Choir of the Storm
Lapis Amulet</Item>
    <Item id="2">Rarity: UNIQUE
Dream Fragments
Sapphire Ring</Item>
    <ItemSet id="1"><Slot name="Amulet" itemId="1" /></ItemSet>
    <ItemSet id="2"><Slot name="Ring 1" itemId="2" /></ItemSet>
  </Items>""",
    )

    equipped = preflight.inspect_lifecycle_component_evidence(
        xml,
        component_kind="item",
        component_name="Choir of the Storm",
    )
    inactive = preflight.inspect_lifecycle_component_evidence(
        xml,
        component_kind="item",
        component_name="Dream Fragments",
    )

    assert equipped["verified"] is True
    assert equipped["matchedName"] == "Choir of the Storm"
    assert equipped["slot"] == "Amulet"
    assert inactive["verified"] is False


def _runtime_selection_engine():
    engine = _Engine(_xml(_group()))
    runtime = {
        "groups": [{
            "index": 1,
            "rootSkillId": "SkillGemTempestFlurryPlayer",
            "mainActiveSkillCalcs": 2,
            "activeSkills": [
                {"index": 2, "name": "Command"},
                {"index": 1, "name": "Tempest Flurry"},
            ],
        }],
    }
    engine.call = lambda _: deepcopy(runtime)
    return engine, runtime


def test_preflight_projects_runtime_effect_order_and_selected_index_together():
    engine, _ = _runtime_selection_engine()
    result = preflight.inspect_generation_preflight(engine)
    group = result["skillGroups"][0]
    assert group["activeSkills"] == ["Tempest Flurry", "Command"]
    assert group["mainActiveSkillCalcs"] == 2
    assert group["activeSkillSelectionError"] is None


def test_preflight_keeps_duplicate_effect_names_at_distinct_runtime_indices():
    engine, runtime = _runtime_selection_engine()
    runtime["groups"][0]["activeSkills"][0]["name"] = "Tempest Flurry"
    group = preflight.inspect_generation_preflight(engine)["skillGroups"][0]
    assert group["activeSkills"] == ["Tempest Flurry", "Tempest Flurry"]
    assert group["mainActiveSkillCalcs"] == 2


def test_preflight_preserves_unnamed_identified_effect_without_shifting_selected_output():
    engine, runtime = _runtime_selection_engine()
    runtime["groups"][0]["activeSkills"] = [
        {"index": 1, "name": "", "effectId": "InternalSpawnPlayer"},
        {"index": 2, "name": "Tempest Flurry", "effectId": "SkillGemTempestFlurryPlayer"},
        {"index": 3, "name": "Command", "effectId": "CommandPlayer"},
    ]
    runtime["groups"][0]["mainActiveSkillCalcs"] = 3
    group = preflight.inspect_generation_preflight(engine)["skillGroups"][0]
    assert group["activeSkills"] == ["", "Tempest Flurry", "Command"]
    assert group["mainActiveSkillCalcs"] == 3
    assert group["activeSkillSelectionError"] is None
    runtime["groups"][0]["mainActiveSkillCalcs"] = 1
    selected_unnamed = preflight.inspect_generation_preflight(engine)["skillGroups"][0]
    assert selected_unnamed["mainActiveSkillCalcs"] is None
    assert selected_unnamed["activeSkillSelectionError"] == "runtime_active_skill_selection_invalid"


@pytest.mark.parametrize("effect_id", [None, "", " ", 123, True])
def test_preflight_unnamed_effect_requires_a_real_runtime_identifier(effect_id):
    engine, runtime = _runtime_selection_engine()
    runtime["groups"][0]["activeSkills"][1].update(name="", effectId=effect_id)
    group = preflight.inspect_generation_preflight(engine)["skillGroups"][0]
    assert group["mainActiveSkillCalcs"] is None
    assert group["activeSkillSelectionError"] == "runtime_active_skills_invalid"


@pytest.mark.parametrize("character,ascendancy,payload", [("Huntress", "Amazon", "Ice Shot"), ("Ranger", "Deadeye", "Lightning Arrow")])
def test_real_mirage_payload_preflight_keeps_pob_effect_index(engine, character, ascendancy, payload):
    from server.generation.validation_checkpoint import _projected_active_index

    engine.new_build()
    engine.set_class(character, ascendancy)
    engine.set_level(95)
    engine.paste_skill(f"{payload} 20/0 1")
    engine.add_skill_group(f"Mirage Archer 20/0 1\n{payload} 20/0 1")
    listed = engine.call("list_skill_groups")["groups"][1]
    effects = listed["activeSkills"]
    assert effects[0]["name"] == "" and effects[0]["effectId"]
    actual_index = next(effect["index"] for effect in effects if effect["name"] == payload)
    assert engine.call("set_skill_group_state", index=2, activeSkillIndex=actual_index)["ok"]
    group = preflight.inspect_generation_preflight(engine)["skillGroups"][1]
    assert group["activeSkillSelectionError"] is None
    assert group["mainActiveSkillCalcs"] == actual_index == 3
    assert group["activeSkills"][actual_index - 1] == payload
    assert _projected_active_index(group) == actual_index


@pytest.mark.parametrize("change,error", [
    ({"rootSkillId": "OtherPlayer"}, "runtime_skill_group_identity_mismatch"),
    ({"source": "Tree:123"}, "runtime_skill_group_identity_mismatch"),
    ({"enabled": False}, "runtime_skill_group_identity_mismatch"),
    ({"mainActiveSkillCalcs": None}, "runtime_active_skill_selection_invalid"),
    ({"mainActiveSkillCalcs": 0}, "runtime_active_skill_selection_invalid"),
    ({"mainActiveSkillCalcs": 3}, "runtime_active_skill_selection_invalid"),
    ({"mainActiveSkillCalcs": True}, "runtime_active_skill_selection_invalid"),
    ({"activeSkills": []}, "runtime_active_skills_missing"),
    ({"activeSkills": [{"index": 2, "name": "Command"}]}, "runtime_active_skills_invalid"),
    ({"activeSkills": [
        {"index": 1, "name": "Command"}, {"index": 1, "name": "Command"},
    ]}, "runtime_active_skills_invalid"),
    ({"activeSkills": [
        {"index": 1, "name": "Tempest Flurry"}, {"index": 2, "name": ""},
    ]}, "runtime_active_skills_invalid"),
])
def test_preflight_cannot_project_guessed_runtime_selection(change, error):
    engine, runtime = _runtime_selection_engine()
    runtime["groups"][0].update(change)
    group = preflight.inspect_generation_preflight(engine)["skillGroups"][0]
    assert group["mainActiveSkillCalcs"] is None
    assert group["activeSkillSelectionError"] == error


@pytest.mark.parametrize("failure,error", [
    ("missing", "runtime_skill_group_unavailable"),
    ("exception", "runtime_skill_group_unavailable"),
    ("ambiguous", "runtime_skill_group_ambiguous"),
])
def test_preflight_requires_one_identity_matched_runtime_group(failure, error):
    engine, runtime = _runtime_selection_engine()
    if failure == "missing":
        runtime["groups"] = []
    elif failure == "ambiguous":
        runtime["groups"].append(deepcopy(runtime["groups"][0]))
    else:
        def fail(_):
            raise RuntimeError("synthetic unavailable runtime")
        engine.call = fail
    group = preflight.inspect_generation_preflight(engine)["skillGroups"][0]
    assert group["mainActiveSkillCalcs"] is None
    assert group["activeSkillSelectionError"] == error
