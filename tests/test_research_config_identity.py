from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from server.knowledge import research_packet, research_readback


def _xml(config: str) -> str:
    return f'<PathOfBuilding2><Build level="90" className="Witch"/>{config}</PathOfBuilding2>'


def _two_sets(active: str = "2") -> str:
    return _xml(f'''<Config activeConfigSet="{active}">
      <ConfigSet id="1" title="Mapping">
        <Input name="conditionLowLife" boolean="false"/>
        <Input name="enemyIsBoss" string="None"/>
      </ConfigSet>
      <ConfigSet id="2" title="Boss">
        <Input name="conditionLowLife" boolean="true"/>
        <Input name="enemyIsBoss" string="Pinnacle"/>
        <Input name="enemyLevel" number="82"/>
        <Placeholder name="enemySpeed" number="110"/>
      </ConfigSet>
    </Config>''')


class _ConfigEngine:
    calls = 0

    def __init__(self, **_kwargs):
        type(self).calls += 1
        self.xml = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def load_build_xml(self, xml, name=""):
        self.xml = xml

    def get_stats(self, _keys):
        config = ET.fromstring(self.xml).find("Config")
        return {"stats": {"Mana": 200 if config.get("activeConfigSet") == "2" else 100}}

    def get_build(self):
        return {}

    def get_xml(self):
        return self.xml


def test_config_rows_keep_scenario_identity_types_and_placeholders():
    packet = {"rawContext": {"rawXml": _two_sets()}}
    first = research_packet.read_packet_section(packet, section="config", limit=2)
    second = research_packet.read_packet_section(packet, section="config", cursor=first["nextCursor"])
    rows = first["items"] + second["items"]
    low_life = [row for row in rows if row["name"] == "conditionLowLife"]
    assert [(row["configSetId"], row["title"], row["isActive"], row["valueType"], row["value"])
            for row in low_life] == [("1", "Mapping", False, "boolean", "false"),
                                    ("2", "Boss", True, "boolean", "true")]
    assert next(row for row in rows if row["name"] == "enemyLevel")["valueType"] == "number"
    assert next(row for row in rows if row["name"] == "enemyIsBoss")["valueType"] == "string"
    assert rows[-1]["kind"] == "placeholder"
    manifest = research_packet.inspect_packet(packet)
    assert manifest["activeSets"]["configSet"] == "2"
    assert manifest["configIdentity"]["status"] == "resolved"
    build = research_packet.read_packet_section(packet, section="build")["items"][0]
    assert build["activeConfigSet"] == "2"
    matches = research_packet.search_packet(packet, query="conditionLowLife", section="config")
    assert {row["item"]["configSetId"] for row in matches["matches"]} == {"1", "2"}


def test_empty_active_config_set_remains_visible_in_manifest():
    packet = {"rawContext": {"rawXml": _xml('<Config activeConfigSet="2"><ConfigSet id="1" title="One"/><ConfigSet id="2" title="Empty"/></Config>')}}
    result = research_packet.read_packet_section(packet, section="config")
    assert result["items"] == []
    assert result["configIdentity"]["configSetCount"] == 2
    identities = research_packet.read_packet_section(packet, section="config-sets")
    assert identities["items"][1] == {
        "configSetId": "2", "configSetIndex": 2, "title": "Empty", "isActive": True,
    }


@pytest.mark.parametrize("config, issue", [
    ('<Config><ConfigSet id="1"/><ConfigSet id="2"/></Config>', "missing_active_config_set"),
    ('<Config activeConfigSet="3"><ConfigSet id="1"/><ConfigSet id="2"/></Config>', "active_config_set_not_found"),
    ('<Config activeConfigSet="bad"><ConfigSet id="1"/><ConfigSet id="2"/></Config>', "invalid_active_config_set"),
    ('<Config activeConfigSet="1"><ConfigSet id="1"/><ConfigSet id="01"/></Config>', "duplicate_config_set_id"),
    ('<Config activeConfigSet="1"><ConfigSet id="1"/><ConfigSet/></Config>', "invalid_config_set_id"),
    ('<Config activeConfigSet="1"><Input name="x" boolean="true"/><ConfigSet id="1"/></Config>', "mixed_legacy_and_config_sets"),
    ('<Config><Input name="x" number="1" boolean="true"/></Config>', "invalid_config_input_type"),
    ('<Config><Input name="x" number="NaN"/></Config>', "invalid_config_number"),
    ('<Config><Input name="x" boolean="maybe"/></Config>', "invalid_config_boolean"),
    ('<Config><Input name="x" number="1"/><Input name="x" number="2"/></Config>', "duplicate_config_input"),
    ('<Config/><Config/>', "multiple_config_sections"),
])
def test_ambiguous_config_never_authorizes_pob_numbers(monkeypatch, config, issue):
    monkeypatch.setattr(research_readback, "PobEngine", _ConfigEngine)
    _ConfigEngine.calls = 0
    xml = _xml(config)
    manifest = research_packet.configuration_manifest({"rawContext": {"rawXml": xml}})
    assert manifest["status"] == "invalid"
    assert issue in manifest["issues"]
    assert manifest["activeConfigSet"] is None
    assert all(row["isActive"] is None for row in manifest["configSets"])
    result = research_readback.build_safe_readback(xml, source_hash_ref="source-hash:test", version_context={})
    assert result["status"] == "unavailable"
    assert result["errorCode"] == "source_config_identity_invalid"
    assert "stats" not in result
    assert _ConfigEngine.calls == 0


def test_legacy_flat_inputs_bind_to_documented_default_set():
    packet = {"rawContext": {"rawXml": _xml('<Config><Input name="x" boolean="false"/></Config>')}}
    result = research_packet.read_packet_section(packet, section="config")
    assert result["configIdentity"]["status"] == "legacy_default"
    assert result["items"][0]["configSetId"] == "1"
    assert result["items"][0]["isActive"] is True
    assert result["items"][0]["value"] == "false"


def test_readback_binds_recomputed_numbers_to_observed_active_set(monkeypatch):
    monkeypatch.setattr(research_readback, "PobEngine", _ConfigEngine)
    results = []
    for active in ("1", "2"):
        xml = _two_sets(active)
        result = research_readback.build_safe_readback(xml, source_hash_ref="source-hash:test", version_context={})
        assert result["status"] == "available"
        assert result["stateBinding"]["activeConfigSet"] == active
        assert result["stateBinding"]["sourceActiveConfigSet"] == active
        assert result["stateBinding"]["configScope"] == "source_active_config_set"
        packet = {"rawContext": {"rawXml": xml}, "pobReadback": result,
                  "safeMetadata": {"sourceRef": "source-hash:test"}}
        assert research_packet.validated_pob_readback(packet) == result
        results.append(result)
    assert [result["stats"]["Mana"] for result in results] == [100, 200]
    assert results[0]["stateRef"] != results[1]["stateRef"]


@pytest.mark.parametrize("observed", [_two_sets("1"), _xml("")])
def test_readback_rejects_engine_config_fallback(monkeypatch, observed):
    class FallbackEngine(_ConfigEngine):
        def get_xml(self):
            return observed
    monkeypatch.setattr(research_readback, "PobEngine", FallbackEngine)
    result = research_readback.build_safe_readback(_two_sets("2"), source_hash_ref="source-hash:test", version_context={})
    assert result["errorCode"] == "pob_active_config_set_mismatch"
    assert "stats" not in result


def test_readback_rejects_lost_explicit_default_config(monkeypatch):
    class DroppedConfig(_ConfigEngine):
        def get_xml(self):
            return _xml("")
    monkeypatch.setattr(research_readback, "PobEngine", DroppedConfig)
    result = research_readback.build_safe_readback(_two_sets("1"), source_hash_ref="source-hash:test", version_context={})
    assert result["errorCode"] == "pob_active_config_set_mismatch"
    assert "stats" not in result


@pytest.mark.parametrize("binding", [
    {"configScope": "source_active_snapshot"},
    {"configScope": "source_active_config_set", "activeConfigSet": "1", "sourceActiveConfigSet": "1"},
])
def test_cached_unbound_or_cross_scenario_numbers_are_not_reexposed(binding):
    packet = {"rawContext": {"rawXml": _two_sets()}, "pobReadback": {
        "status": "available", "stateBinding": binding, "stats": {"Mana": 999},
    }}
    readback = research_packet.read_packet_section(packet, section="pob-readback")["items"][0]
    assert readback["status"] == "unavailable"
    assert readback["errorCode"] == "config_readback_binding_missing_or_mismatched"
    assert "stats" not in readback


def _with_sets(xml: str, *, skill: str = "2", item: str = "3", spec: str = "2") -> str:
    sets = (
        f'<Skills activeSkillSet="{skill}"><SkillSet id="1"/><SkillSet id="2"/></Skills>'
        f'<Items activeItemSet="{item}"><ItemSet id="1"/><ItemSet id="3"/></Items>'
        f'<Tree activeSpec="{spec}"><Spec/><Spec/></Tree>'
    )
    return xml.replace("</PathOfBuilding2>", sets + "</PathOfBuilding2>")


def test_readback_and_packet_jointly_bind_all_four_active_axes(monkeypatch):
    monkeypatch.setattr(research_readback, "PobEngine", _ConfigEngine)
    xml = _with_sets(_two_sets())
    result = research_readback.build_safe_readback(xml, source_hash_ref="source-hash:test", version_context={})
    expected = {"configSet": "2", "skillSet": "2", "itemSet": "3", "passiveSpec": "2"}
    assert result["status"] == "available"
    assert result["stateBinding"]["activeSets"] == expected
    assert result["stateBinding"]["sourceActiveSets"] == expected
    packet = {"rawContext": {"rawXml": xml}, "pobReadback": result,
              "safeMetadata": {"sourceRef": "source-hash:test"}}
    assert research_packet.inspect_packet(packet)["activeSets"] == expected
    assert research_packet.validated_pob_readback(packet) == result


@pytest.mark.parametrize("changed_axis", ["skill", "item", "spec"])
def test_engine_selection_drift_on_another_axis_discards_numbers(monkeypatch, changed_axis):
    class DriftEngine(_ConfigEngine):
        def get_xml(self):
            return _with_sets(_two_sets(), **{changed_axis: "1"})
    monkeypatch.setattr(research_readback, "PobEngine", DriftEngine)
    result = research_readback.build_safe_readback(_with_sets(_two_sets()), source_hash_ref="source-hash:test", version_context={})
    assert result["errorCode"] == "pob_active_set_mismatch"
    assert "stats" not in result


@pytest.mark.parametrize("axis_xml", [
    '<Skills activeSkillSet="9"><SkillSet id="1"/></Skills>',
    '<Skills activeSkillSet="1"><SkillSet id="1"/><SkillSet id="01"/></Skills>',
    '<Items><ItemSet id="1"/><ItemSet id="2"/></Items>',
    '<Items activeItemSet="0"><ItemSet id="1"/></Items>',
    '<Tree activeSpec="3"><Spec/><Spec/></Tree>',
    '<Tree><Spec/><Spec/></Tree>',
])
def test_invalid_other_axis_identity_cannot_authorize_readback(monkeypatch, axis_xml):
    monkeypatch.setattr(research_readback, "PobEngine", _ConfigEngine)
    _ConfigEngine.calls = 0
    xml = _two_sets().replace("</PathOfBuilding2>", axis_xml + "</PathOfBuilding2>")
    result = research_readback.build_safe_readback(xml, source_hash_ref="source-hash:test", version_context={})
    assert result["errorCode"] == "source_active_set_identity_invalid"
    assert _ConfigEngine.calls == 0


def test_legacy_selection_axes_normalize_to_upstream_default_one():
    root = ET.fromstring(_xml('<Skills><Skill/></Skills><Items><Slot name="Helmet"/></Items><Spec/><Config/>'))
    identity = research_packet.active_set_identity(root)
    assert identity["issues"] == []
    assert identity["activeSets"] == {
        "configSet": "1", "skillSet": "1", "itemSet": "1", "passiveSpec": "1",
    }


@pytest.mark.parametrize("change", ["source_ref", "same_id_condition", "placeholder", "other_axis"])
def test_cached_readback_requires_exact_source_and_snapshot(monkeypatch, change):
    monkeypatch.setattr(research_readback, "PobEngine", _ConfigEngine)
    xml = _with_sets(_two_sets())
    result = research_readback.build_safe_readback(xml, source_hash_ref="source-hash:test", version_context={})
    packet = {"rawContext": {"rawXml": xml}, "pobReadback": result,
              "safeMetadata": {"sourceRef": "source-hash:test"}}
    assert research_packet.validated_pob_readback(packet)["status"] == "available"
    if change == "source_ref":
        packet["safeMetadata"]["sourceRef"] = "source-hash:other"
    elif change == "same_id_condition":
        packet["rawContext"]["rawXml"] = xml.replace('string="Pinnacle"', 'string="None"')
    elif change == "placeholder":
        packet["rawContext"]["rawXml"] = xml.replace('number="110"', 'number="200"')
    else:
        packet["rawContext"]["rawXml"] = xml.replace('activeItemSet="3"', 'activeItemSet="1"')
    assert research_packet.validated_pob_readback(packet)["status"] == "unavailable"
