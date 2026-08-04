from __future__ import annotations

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
        self.build = build or {"class": "Monk", "level": 70, "gear": {}}
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


def test_preflight_blocks_endgame_resistance_gate_without_consuming_judge():
    engine = _Engine(
        _xml(_group()),
        build={"class": "Monk", "ascendancy": "Martial Artist", "level": 85, "gear": {}},
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
