"""V10：输入hash与Research值必须遵循真实PoB XML解码，而非XML标准归一化。"""

from copy import deepcopy
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import pytest

from server.compute.engine import _find_luajit
from server.compute.pob_xml_input import (
    XML_INPUT_SEMANTICS_VERSION,
    parse_pob_xml,
    requires_preserved_input_semantics,
)
from server.compute.state import _semantic_element, build_state_hash, canonical_payload_hash
from server.knowledge import research_packet, research_readback


def _xml(value: str, *, quote: str = '"') -> str:
    return '<PathOfBuilding2><Build level="90"/><Config activeConfigSet="1"><ConfigSet id="1">' + (
        f'<Input name="customMods" string={quote}{value}{quote}/>'
    ) + '</ConfigSet></Config></PathOfBuilding2>'


@pytest.mark.parametrize("value,expected", [
    ("line one\nline two", "line one\nline two"),
    ("line one\r\nline two", "line one\r\nline two"),
    ("line one\rline two", "line one\rline two"),
    ("one\ttwo", "one\ttwo"),
    ("&lt;&gt;&amp;&apos;&quot;", "<>&'\""),
    ("before&#10;after", "beforeafter"),
    ("before&#xA;after", "beforeafter"),
    ("before&unknown;after", "beforeafter"),
    ("before&AMP;after", "beforeafter"),
    ("&amp;#10; &amp;lt;", "&#10; &lt;"),
    ("one & bare", "one & bare"),
    ("&unknown&amp;", ""),
])
@pytest.mark.parametrize("quote", ['"', "'"])
def test_attribute_values_match_the_pinned_lua_decoder(value, expected, quote):
    xml = _xml(value, quote=quote)
    parsed = parse_pob_xml(xml).find('.//Input[@name="customMods"]').get("string")
    assert parsed == expected
    decoder = Path(__file__).resolve().parents[1] / "pob/PathOfBuilding-PoE2/runtime/lua/xml.lua"
    lua = (
        "local x = dofile(arg[0]); local input={}; "
        "for n in io.read('*a'):gmatch('%d+') do input[#input+1]=string.char(tonumber(n)) end; "
        "local t,err = x.ParseXML(table.concat(input)); assert(t,err); "
        "local value=t[1][2][1][1].attrib.string; local bytes={}; "
        "for i=1,#value do bytes[#bytes+1]=string.byte(value,i) end; "
        "io.write(table.concat(bytes,','))"
    )
    result = subprocess.run(
        [_find_luajit(), "-e", lua, "--", str(decoder)],
        input=",".join(str(byte) for byte in xml.encode()).encode(), capture_output=True,
        timeout=20, check=True,
    )
    expected_bytes = ",".join(str(byte) for byte in expected.encode())
    assert result.stdout.decode() == expected_bytes


@pytest.mark.parametrize("xml", [
    _xml("100% increased Fire Damage"),
    _xml("&lt; &gt; &quot; &amp; &apos;"),
    '<PathOfBuilding2><Skills activeSkillSet="1"><SkillSet id="1"><Skill><Gem nameSpec="Fireball"/></Skill></SkillSet></Skills><Tree activeSpec="1"><Spec nodes="3,2,1"/></Tree></PathOfBuilding2>',
])
def test_ordinary_semantic_hashes_remain_backward_compatible(xml):
    old_hash = canonical_payload_hash(_semantic_element(ET.fromstring(xml)))
    assert build_state_hash(xml) == old_hash
    assert requires_preserved_input_semantics(xml) is False


def test_numeric_references_are_removed_once_in_attributes_and_text():
    assert build_state_hash(_xml("first&#10;second")) == build_state_hash(_xml("firstsecond"))
    assert build_state_hash(_xml("first&#10;second")) != build_state_hash(_xml("first\nsecond"))
    root = parse_pob_xml('<Root><Item>one&#10;two &amp;#10;</Item><Item><![CDATA[one&#10;two]]></Item></Root>')
    assert root[0].text == "onetwo &#10;"
    assert root[1].text == "one&#10;two"


@pytest.mark.parametrize("xml", [
    '<Root x="one" x="two"/>',
    '<!DOCTYPE Root [<!ENTITY custom "value">]><Root/>',
    '<Root x = "ignored-by-lua"/>',
])
def test_ambiguous_or_unsupported_source_syntax_fails_closed(xml):
    with pytest.raises(ET.ParseError):
        parse_pob_xml(xml)


class _ReadbackEngine:
    def __init__(self, **_kwargs): pass
    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def load_build_xml(self, xml, **_kwargs): self.xml = xml
    def get_xml(self): return self.xml
    def get_stats(self, _keys): return {"stats": {"Mana": 100}}
    def get_build(self): return {}


@pytest.mark.parametrize("value,affected", [("one\ntwo", True), ("one\r\ntwo", True),
                                            ("one&#10;two", True), ("one two", False)])
def test_only_affected_old_readbacks_require_recomputation(monkeypatch, value, affected):
    monkeypatch.setattr(research_readback, "PobEngine", _ReadbackEngine)
    xml = _xml(value)
    readback = research_readback.build_safe_readback(xml, source_hash_ref="source-hash:synthetic", version_context={})
    packet = {"rawContext": {"rawXml": xml}, "pobReadback": readback,
              "safeMetadata": {"sourceRef": "source-hash:synthetic"}}
    assert research_packet.validated_pob_readback(packet)["status"] == "available"
    assert readback["stateBinding"]["xmlInputSemanticsVersion"] == XML_INPUT_SEMANTICS_VERSION
    old = deepcopy(readback)
    old["stateBinding"].pop("xmlInputSemanticsVersion")
    old["stateBinding"].pop("sourceInputStateHash")
    packet["pobReadback"] = old
    expected = "unavailable" if affected else "available"
    assert research_packet.validated_pob_readback(packet)["status"] == expected
    old["stateBinding"]["xmlInputSemanticsVersion"] = XML_INPUT_SEMANTICS_VERSION
    # A caller-added version marker alone cannot give an old binding new input semantics.
    assert research_packet.validated_pob_readback(packet)["status"] == expected
    assert "xmlInputSemanticsVersion" not in readback.get("versionContext", {})


def test_real_pob_multiline_changes_stats_and_hash_while_research_preserves_values(engine):
    engine.new_build()
    engine.paste_skill("Fireball 20/0  1")
    mods = "+2000 to maximum Mana\n100% increased Fire Damage"
    engine.set_config(custom_mods=mods)
    original = engine.get_xml()
    flattened = ET.tostring(ET.fromstring(original), encoding="unicode")
    engine.load_build_xml(original)
    before = engine.get_stats(["Mana", "TotalDPS"])["stats"]
    before_observed = engine.get_xml()
    engine.load_build_xml(flattened)
    after = engine.get_stats(["Mana", "TotalDPS"])["stats"]
    after_observed = engine.get_xml()
    assert before["Mana"] > after["Mana"] and before["TotalDPS"] > after["TotalDPS"]
    assert build_state_hash(original) != build_state_hash(flattened)
    assert build_state_hash(before_observed) != build_state_hash(after_observed)
    readbacks = [research_readback.build_safe_readback(xml, source_hash_ref="source-hash:synthetic", version_context={})
                 for xml in (original, flattened)]
    assert all(value["status"] == "available" for value in readbacks)
    assert readbacks[0]["snapshotRef"] != readbacks[1]["snapshotRef"]
    packet = {"rawContext": {"rawXml": original}, "pobReadback": readbacks[0],
              "safeMetadata": {"sourceRef": "source-hash:synthetic"}}
    rows = research_packet.read_packet_section(packet, section="config")["items"]
    assert next(row for row in rows if row.get("name") == "customMods")["value"] == mods
    assert research_packet.validated_pob_readback(packet)["status"] == "available"
    packet["rawContext"]["rawXml"] = flattened
    assert research_packet.validated_pob_readback(packet)["status"] == "unavailable"
