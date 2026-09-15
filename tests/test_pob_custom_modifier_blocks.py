"""0.5.5 自定义修饰块：活动场景、禁用内容与原生迁移须一致。"""

from copy import deepcopy
from pathlib import Path
import re
import subprocess

import pytest

from server.compute.engine import _find_luajit
from server.compute.pob_config import active_custom_modifier_hash, custom_modifier_projection
from server.compute.pob_xml_input import parse_pob_xml
from server.compute.state import build_state_hash
from server.knowledge import research_packet, research_readback


def _xml(config):
    return f'<PathOfBuilding2><Build level="90"/>{config}</PathOfBuilding2>'


def _config(blocks, *, legacy="", flat=False):
    body = (f'<Input name="customMods" string="{legacy}"/>' if legacy else "") + blocks
    return f'<Config>{body}</Config>' if flat else f'<Config activeConfigSet="1"><ConfigSet id="1">{body}</ConfigSet></Config>'


def _block(text, *, enabled=None, title="Default"):
    flag = f' enabled="{enabled}"' if enabled is not None else ""
    return f'<CustomModifierBlock title="{title}"{flag}>{text}</CustomModifierBlock>'


@pytest.mark.parametrize("body,expected", [
    ("  +100 to maximum Mana\n  +20 to maximum Life  ", "+100 to maximum Mana\n  +20 to maximum Life"),
    ("<![CDATA[  +100 to maximum Mana  ]]>", "  +100 to maximum Mana  "),
    ("<![CDATA[+100 to maximum Mana]]>+9000 to maximum Mana", "+100 to maximum Mana"),
    ("+100 to maximum Mana<![CDATA[+9000 to maximum Mana]]>", "+100 to maximum Mana"),
    ("&unknown;<![CDATA[+9000 to maximum Mana]]>", ""),
    ("+100<!-- ignored --> to maximum Mana", "+100 to maximum Mana"),
    ("<![CDATA[ \n ]]><!---->+100 to maximum Mana", "+100 to maximum Mana"),
])
def test_block_text_is_the_first_native_lua_segment(body, expected):
    xml = _xml(_config(_block(body)))
    value = parse_pob_xml(xml).find(".//CustomModifierBlock").text or ""
    assert value == expected
    decoder = Path(__file__).resolve().parents[1] / "pob/PathOfBuilding-PoE2/runtime/lua/xml.lua"
    lua = (
        "local x=dofile(arg[0]); local t,e=x.ParseXML(io.read('*a')); assert(t,e); "
        "local v=t[1][2][1][1][1] or ''; local b={}; "
        "for i=1,#v do b[#b+1]=string.byte(v,i) end; io.write(table.concat(b,','))"
    )
    result = subprocess.run([_find_luajit(), "-e", lua, "--", str(decoder)],
                            input=xml.encode(), capture_output=True, check=True, timeout=20)
    assert result.stdout.decode() == ",".join(str(byte) for byte in expected.encode())


@pytest.mark.parametrize("blocks,legacy,flat,expected", [
    ("", "+100 to maximum Mana", False, "+100 to maximum Mana"),
    (_block(""), "+100 to maximum Mana", False, "+100 to maximum Mana"),
    (_block("", enabled="false"), "+100 to maximum Mana", False, "+100 to maximum Mana"),
    (_block("+200 to maximum Mana"), "+100 to maximum Mana", False, "+200 to maximum Mana"),
    (_block("+200 to maximum Mana", enabled="false"), "+100 to maximum Mana", False, ""),
    (_block("") + _block(""), "+100 to maximum Mana", False, ""),
    ("", "+100 to maximum Mana", True, "+100 to maximum Mana"),
    (_block(""), "+100 to maximum Mana", True, ""),
    (_block("+200 to maximum Mana"), "+100 to maximum Mana", True, "+200 to maximum Mana"),
    (_block("+200 to maximum Mana", enabled="TRUE"), "", False, ""),
])
def test_xml_load_migration_never_resurrects_ignored_legacy_text(blocks, legacy, flat, expected):
    root = parse_pob_xml(_xml(_config(blocks, legacy=legacy, flat=flat)))
    container = root.find("Config") if flat else root.find(".//ConfigSet")
    projection = custom_modifier_projection(container)
    assert "\n".join(block["value"] for block in projection["effectiveBlocks"]) == expected


def test_research_exposes_every_block_and_separates_active_enabled_and_legacy():
    xml = _xml('<Config activeConfigSet="2"><ConfigSet id="1" title="Mapping">'
               + _block("+100 to maximum Mana", title="Mapping-only")
               + '</ConfigSet><ConfigSet id="2" title="Boss"><Input name="customMods" string="+9000 to maximum Mana"/>'
               + _block("+200 to maximum Mana", title="Boss-known")
               + _block("+8000 to maximum Mana", enabled="false", title="Experimental")
               + '</ConfigSet></Config>')
    packet = {"rawContext": {"rawXml": xml}}
    rows = research_packet.read_packet_section(packet, section="config")["items"]
    assert len(rows) == 4
    assert [(row["value"], row["isActive"], row["appliesToActiveConfig"]) for row in rows] == [
        ("+100 to maximum Mana", False, False), ("+9000 to maximum Mana", True, False),
        ("+200 to maximum Mana", True, True), ("+8000 to maximum Mana", True, False),
    ]
    matches = research_packet.search_packet(packet, query="Experimental", section="config")
    assert matches["matches"][0]["item"]["enabled"] is False


def test_mixed_flat_block_and_explicit_sets_do_not_authorize_a_scenario():
    xml = _xml('<Config activeConfigSet="1">' + _block("+9999 to maximum Mana") + '<ConfigSet id="1"/></Config>')
    identity = research_packet.config_set_identity(parse_pob_xml(xml))
    assert identity["activeConfigSet"] is None
    assert "mixed_legacy_and_config_sets" in identity["issues"]


def test_legacy_string_placeholder_follows_native_input_assignment_order():
    inputs = '<Input name="customMods" string="+100 to maximum Mana"/><Placeholder name="customMods" string="+200 to maximum Mana"/>'
    xml = _xml(_config(inputs))
    rows = research_packet.read_packet_section({"rawContext": {"rawXml": xml}}, section="config")["items"]
    assert [row["appliesToActiveConfig"] for row in rows] == [False, True]
    assert active_custom_modifier_hash(parse_pob_xml(xml), "1") == active_custom_modifier_hash(
        parse_pob_xml(_xml(_config(_block("+200 to maximum Mana")))), "1")
    assert build_state_hash(xml) != build_state_hash(xml.replace("+200", "+9000"))
    reverse = '<Placeholder name="customMods" string="+200 to maximum Mana"/><Input name="customMods" string="+100 to maximum Mana"/>'
    assert build_state_hash(xml) != build_state_hash(_xml(_config(reverse)))


def test_block_changes_are_bound_without_making_config_input_order_significant():
    first = _block("+100 to maximum Mana", title="A")
    second = _block("+200 to maximum Mana", enabled="false", title="B")
    xml = _xml(_config(first + second))
    for changed in (xml.replace("+100", "+101"), xml.replace('enabled="false"', 'enabled="true"'),
                    xml.replace(first + second, second + first), xml.replace('title="A"', 'title="B"')):
        assert build_state_hash(changed) != build_state_hash(xml)
    inputs = '<Input name="x" number="1"/><Input name="y" number="2"/>'
    reverse = '<Input name="y" number="2"/><Input name="x" number="1"/>'
    assert build_state_hash(_xml(_config(inputs + first))) == build_state_hash(_xml(_config(reverse + first)))
    default = _xml(_config('<CustomModifierBlock>+100 to maximum Mana</CustomModifierBlock>'))
    explicit = _xml(_config(_block("+100 to maximum Mana", enabled="true")))
    assert build_state_hash(default) == build_state_hash(explicit)
    assert build_state_hash(default) != build_state_hash(default.replace('<CustomModifierBlock>', '<CustomModifierBlock enabled="nil">'))


class _ReadbackEngine:
    observed = None
    def __init__(self, **_kwargs): pass
    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def load_build_xml(self, xml, **_kwargs): self.xml = xml
    def get_xml(self): return type(self).observed or self.xml
    def get_stats(self, _keys): return {"stats": {"Mana": 100}}
    def get_build(self): return {}
    def inspect_reservation_ledger(self):
        return {"schemaVersion": "pob_reservation_ledger_v1", "status": "available",
                "effects": [], "groups": [],
                "totals": {pool: {} for pool in ("Life", "Mana", "Spirit")},
                "activeWeaponSet": self.get_build().get("activeWeaponSet"), "readOnlyVerified": True,
                "buildStateHash": build_state_hash(self.get_xml())}


def test_new_block_readbacks_require_exact_recomputed_semantics(monkeypatch):
    monkeypatch.setattr(research_readback, "PobEngine", _ReadbackEngine)
    xml = _xml(_config(_block("+100 to maximum Mana")))
    result = research_readback.build_safe_readback(xml, source_hash_ref="source-hash:synthetic", version_context={})
    packet = {"rawContext": {"rawXml": xml}, "pobReadback": result,
              "safeMetadata": {"sourceRef": "source-hash:synthetic"}}
    assert research_packet.validated_pob_readback(packet)["status"] == "available"
    old = deepcopy(result)
    old["stateBinding"].pop("customModifierSemanticsVersion")
    packet["pobReadback"] = old
    assert research_packet.validated_pob_readback(packet)["status"] == "unavailable"
    monkeypatch.setattr(_ReadbackEngine, "observed", xml.replace("+100", "+9999"))
    changed = research_readback.build_safe_readback(xml, source_hash_ref="source-hash:synthetic", version_context={})
    assert changed["errorCode"] == "pob_active_custom_modifiers_mismatch"
    assert "stats" not in changed


def _load_config(engine, config):
    engine.new_build()
    xml = engine.get_xml()
    changed, count = re.subn(r"<Config\b[^>]*>.*?</Config>", lambda _m: config, xml, flags=re.DOTALL)
    assert count == 1
    engine.load_build_xml(changed)
    return changed


def test_native_blocks_preserve_active_scenario_options_and_explicit_replacement(engine):
    controls = {}
    for value in (0, 300, 400):
        engine.new_build()
        engine.set_config(custom_mods=f"+{value} to maximum Mana" if value else "")
        controls[value] = engine.get_stats(["Mana"])["stats"]["Mana"]
    config = ('<Config activeConfigSet="2"><ConfigSet id="1">'
              + _block("+7000 to maximum Mana", title="Inactive")
              + '</ConfigSet><ConfigSet id="2">'
              + _block("+100 to maximum Mana", title="First")
              + _block("+9000 to maximum Mana", enabled="false", title="Disabled")
              + _block("+200 to maximum Mana", title="Second") + '</ConfigSet></Config>')
    source = _load_config(engine, config)
    assert engine.get_stats(["Mana"])["stats"]["Mana"] == controls[300]
    assert engine.get_build()["customMods"] == "+100 to maximum Mana\n+200 to maximum Mana"
    snapshot = engine.get_xml()
    initial_hash = build_state_hash(snapshot)
    engine.load_build_xml(snapshot)
    assert build_state_hash(engine.get_xml()) == initial_hash
    assert engine.get_stats(["Mana"])["stats"]["Mana"] == controls[300]
    assert active_custom_modifier_hash(parse_pob_xml(source), "2") == active_custom_modifier_hash(parse_pob_xml(snapshot), "2")
    engine.set_config(options={"enemyIsBoss": "Pinnacle"})
    after_options = parse_pob_xml(engine.get_xml())
    assert len(after_options.findall(".//CustomModifierBlock")) == 4
    assert engine.get_stats(["Mana"])["stats"]["Mana"] == controls[300]
    engine.set_config(custom_mods="+400 to maximum Mana")
    assert engine.get_stats(["Mana"])["stats"]["Mana"] == controls[400]
    assert engine.get_build()["customMods"] == "+400 to maximum Mana"
    snapshot = engine.get_xml()
    engine.load_build_xml(snapshot)
    assert build_state_hash(engine.get_xml()) == build_state_hash(snapshot)
    assert engine.get_stats(["Mana"])["stats"]["Mana"] == controls[400]
    assert "+7000 to maximum Mana" in engine.get_xml()
    engine.set_config(custom_mods="")
    assert engine.get_build()["customMods"] == ""
    assert engine.get_stats(["Mana"])["stats"]["Mana"] == controls[0]
    engine.load_build_xml(engine.get_xml())
    assert engine.get_stats(["Mana"])["stats"]["Mana"] == controls[0]


@pytest.mark.parametrize("blocks,flat,expected", [
    ("", False, 100), (_block("", enabled="false"), False, 100),
    (_block("+200 to maximum Mana", enabled="false"), False, 0),
    (_block(""), True, 0), (_block("+200 to maximum Mana"), True, 200),
])
def test_loaded_legacy_migration_matches_the_native_calculation(engine, blocks, flat, expected):
    engine.new_build()
    engine.set_config(custom_mods=f"+{expected} to maximum Mana" if expected else "")
    control = engine.get_stats(["Mana"])["stats"]["Mana"]
    source = _load_config(engine, _config(blocks, legacy="+100 to maximum Mana", flat=flat))
    assert engine.get_stats(["Mana"])["stats"]["Mana"] == control
    assert active_custom_modifier_hash(parse_pob_xml(source), "1") == active_custom_modifier_hash(parse_pob_xml(engine.get_xml()), "1")


def test_unicode_modifier_prefix_cannot_reuse_another_numeric_checkpoint(engine):
    from server.generation.validation_checkpoint import inspect_generation_checkpoint

    engine.new_build()
    engine.set_level(20)
    engine.paste_skill("Fireball 7/0  1")
    original = engine.get_xml()
    observations = []
    for prefix in ("", "\u00a0", "\u2003"):
        config = _config(_block(prefix + "+100 to maximum Mana"))
        xml, count = re.subn(r"<Config\b[^>]*>.*?</Config>", lambda _m: config, original, flags=re.S)
        assert count == 1
        engine.load_build_xml(xml)
        actual = engine.get_stats(["Mana"])["stats"]["Mana"]
        checkpoint = inspect_generation_checkpoint(engine)
        assert checkpoint["stats"]["Mana"] == actual
        assert checkpoint["cacheHit"] is False
        observations.append((build_state_hash(engine.get_xml()), actual, checkpoint["validationRef"]))
    assert observations[0][1] > observations[1][1] == observations[2][1]
    assert len({row[0] for row in observations}) == 3
    assert len({row[2] for row in observations}) == 3
