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
    def __init__(self, xml: str, *, build: dict[str, object] | None = None) -> None:
        self.xml = xml
        self.xml_reads = 0
        self.build = build or {"class": "Monk", "level": 70, "gear": {}}

    def get_xml(self) -> str:
        self.xml_reads += 1
        return self.xml

    def get_build(self) -> dict[str, object]:
        return self.build

    def list_jewel_sockets(self) -> dict[str, object]:
        return {"sockets": []}


def test_preflight_blocks_exact_duplicate_enabled_group_from_one_snapshot():
    engine = _Engine(_xml(_group() + _group()))

    result = preflight.inspect_generation_preflight(engine)

    assert result["readyForJudge"] is False
    assert result["blockingIssues"] == ["duplicate_enabled_skill_group"]
    assert result["duplicateGroupIndices"] == [1, 2]
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
