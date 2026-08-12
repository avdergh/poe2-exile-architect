from server.knowledge import pob_xml_meta


def test_main_skill_follows_main_socket_group_positional() -> None:
    xml = """<PathOfBuilding2>
  <Build className="Warrior" ascendClassName="Titan" mainSocketGroup="2" />
  <Skills>
    <Skill mainActiveSkillCalcs="Dread Banner">
      <Gem nameSpec="Dread Banner" skillId="DreadBannerPlayer" />
    </Skill>
    <Skill mainActiveSkillCalcs="Molten Blast">
      <Gem nameSpec="Molten Blast" skillId="MoltenBlastPlayer" />
      <Gem nameSpec="Cooldown Recovery II" skillId="SupportGemIngenuityTwo" />
    </Skill>
  </Skills>
</PathOfBuilding2>"""
    assert pob_xml_meta.main_skill_from_pob_xml(xml) == "Molten Blast"


def test_main_skill_matches_explicit_group_id() -> None:
    xml = """<PathOfBuilding>
  <Build className="Witch" mainSocketGroup="3" />
  <Skills>
    <Skill id="1"><Gem nameSpec="Spark" skillId="SparkPlayer" /></Skill>
    <Skill id="2"><Gem nameSpec="Flame Wall" skillId="FlameWallPlayer" /></Skill>
    <Skill id="3" mainActiveSkill="Comet">
      <Gem nameSpec="Comet" skillId="CometPlayer" />
    </Skill>
  </Skills>
</PathOfBuilding>"""
    assert pob_xml_meta.main_skill_from_pob_xml(xml) == "Comet"


def test_main_skill_numeric_active_skill_index() -> None:
    xml = """<PathOfBuilding>
  <Build className="Ranger" mainSocketGroup="1" />
  <Skills>
    <Skill mainActiveSkill="2">
      <Gem nameSpec="Freezing Salvo" skillId="FreezingSalvoPlayer" />
      <Gem nameSpec="Ice Shot" skillId="IceShotPlayer" />
    </Skill>
  </Skills>
</PathOfBuilding>"""
    assert pob_xml_meta.main_skill_from_pob_xml(xml) == "Ice Shot"


def test_main_skill_numeric_index_skips_support_gems() -> None:
    xml = """<PathOfBuilding>
  <Build className="Witch" mainSocketGroup="1" />
  <Skills>
    <Skill mainActiveSkill="2">
      <Gem nameSpec="Heft" skillId="SupportGemHeft" />
      <Gem nameSpec="Bonestorm" skillId="BonestormPlayer" />
      <Gem nameSpec="Execute III" skillId="SupportGemExecuteThree" />
      <Gem nameSpec="Thunderstorm" skillId="ThunderstormPlayer" />
    </Skill>
  </Skills>
</PathOfBuilding>"""
    assert pob_xml_meta.main_skill_from_pob_xml(xml) == "Thunderstorm"


def test_main_skill_numeric_index_out_of_active_range_returns_none() -> None:
    xml = """<PathOfBuilding>
  <Build className="Witch" mainSocketGroup="1" />
  <Skills>
    <Skill mainActiveSkill="2">
      <Gem nameSpec="Heft" skillId="SupportGemHeft" />
      <Gem nameSpec="Bonestorm" skillId="BonestormPlayer" />
    </Skill>
  </Skills>
</PathOfBuilding>"""
    assert pob_xml_meta.main_skill_from_pob_xml(xml) is None


def test_main_skill_numeric_index_skips_disabled_gems() -> None:
    xml = """<PathOfBuilding>
  <Build className="Witch" mainSocketGroup="1" />
  <Skills>
    <Skill mainActiveSkill="1">
      <Gem nameSpec="Bonestorm" skillId="BonestormPlayer" enabled="false" />
      <Gem nameSpec="Thunderstorm" skillId="ThunderstormPlayer" enabled="true" />
    </Skill>
  </Skills>
</PathOfBuilding>"""
    assert pob_xml_meta.main_skill_from_pob_xml(xml) == "Thunderstorm"


def test_main_skill_enabled_parsing_matches_xml_bool_semantics() -> None:
    xml = """<PathOfBuilding>
  <Build className="Witch" mainSocketGroup="1" />
  <Skills>
    <Skill mainActiveSkill="1">
      <Gem nameSpec="ZeroDisabled" skillId="ZeroDisabledPlayer" enabled="0" />
      <Gem nameSpec="EmptyDisabled" skillId="EmptyDisabledPlayer" enabled="" />
      <Gem nameSpec="OneEnabled" skillId="OneEnabledPlayer" enabled="1" />
      <Gem nameSpec="Bonestorm" skillId="BonestormPlayer" />
    </Skill>
  </Skills>
</PathOfBuilding>"""
    assert pob_xml_meta.main_skill_from_pob_xml(xml) == "OneEnabled"


def test_main_skill_uses_only_active_skill_set() -> None:
    xml = """<PathOfBuilding>
  <Build className="Ranger" mainSocketGroup="2" />
  <Skills activeSkillSet="2"><SkillSet id="1">
    <Skill><Gem nameSpec="Rain of Blades" skillId="RainOfBladesPlayer" /></Skill>
  </SkillSet><SkillSet id="2">
    <Skill><Gem nameSpec="Trinity" skillId="TrinityPlayer" /></Skill>
    <Skill><Gem nameSpec="Ice Shot" skillId="IceShotPlayer" /></Skill>
  </SkillSet></Skills>
</PathOfBuilding>"""
    assert pob_xml_meta.main_skill_from_pob_xml(xml) == "Ice Shot"


def test_main_skill_skill_id_selector() -> None:
    xml = """<PathOfBuilding>
  <Build className="Witch" mainSocketGroup="1" />
  <Skills>
    <Skill mainActiveSkillCalcs="CometPlayer">
      <Gem nameSpec="Spark" skillId="SparkPlayer" />
      <Gem nameSpec="Comet" skillId="CometPlayer" />
    </Skill>
  </Skills>
</PathOfBuilding>"""
    assert pob_xml_meta.main_skill_from_pob_xml(xml) == "Comet"


def test_main_skill_group_first_gem_without_selector() -> None:
    xml = """<PathOfBuilding>
  <Build className="Witch" mainSocketGroup="1" />
  <Skills>
    <Skill>
      <Gem nameSpec="Bonestorm" skillId="BonestormPlayer" />
      <Gem nameSpec="Heft" skillId="SupportGemHeft" />
    </Skill>
  </Skills>
</PathOfBuilding>"""
    assert pob_xml_meta.main_skill_from_pob_xml(xml) == "Bonestorm"


def test_main_skill_skillset_flattened_order() -> None:
    xml = """<PathOfBuilding>
  <Build className="Ranger" mainSocketGroup="2" />
  <Skills activeSkillSet="1"><SkillSet id="1">
    <Skill><Gem nameSpec="Rain of Blades" skillId="RainOfBladesPlayer" /></Skill>
    <Skill><Gem nameSpec="Trinity" skillId="TrinityPlayer" /></Skill>
  </SkillSet></Skills>
</PathOfBuilding>"""
    assert pob_xml_meta.main_skill_from_pob_xml(xml) == "Trinity"


def test_main_skill_falls_back_to_first_name_spec() -> None:
    xml = """<PathOfBuilding>
  <Build className="Witch" mainSocketGroup="9" />
  <Skills>
    <Skill><Gem nameSpec="Bonestorm" skillId="BonestormPlayer" /></Skill>
  </Skills>
</PathOfBuilding>"""
    assert pob_xml_meta.main_skill_from_pob_xml(xml) == "Bonestorm"


def test_main_skill_legacy_no_build_attrs() -> None:
    xml = """<PathOfBuilding>
  <Build className="Witch" />
  <Skills>
    <Skill mainActiveSkillCalcs="Dread Banner">
      <Gem nameSpec="Dread Banner" skillId="DreadBannerPlayer" />
    </Skill>
    <Skill mainActiveSkillCalcs="Molten Blast">
      <Gem nameSpec="Molten Blast" skillId="MoltenBlastPlayer" />
    </Skill>
  </Skills>
</PathOfBuilding>"""
    assert pob_xml_meta.main_skill_from_pob_xml(xml) == "Dread Banner"


def test_main_skill_empty_or_malformed() -> None:
    assert pob_xml_meta.main_skill_from_pob_xml("") is None
    assert (
        pob_xml_meta.main_skill_from_pob_xml("<PathOfBuilding><Build /></PathOfBuilding>") is None
    )
