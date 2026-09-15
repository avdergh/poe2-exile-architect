"""R4 活动实例贯通和配置分页的独立回归。"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from scripts.research_mature_builds import _assert_transient_view_payload
from server.knowledge import research_packet, research_readback


def _packet(body: str) -> dict:
    return {"safeMetadata": {"sourceRef": "source-hash:synthetic"}, "rawContext": {
        "rawXml": '<PathOfBuilding2><Build level="90"/>' + body + '</PathOfBuilding2>',
    }}


def _all_rows(packet: dict, section: str, *, limit: int = 50) -> list:
    cursor = 0
    rows = []
    while True:
        page = research_packet.read_packet_section(
            packet, section=section, cursor=cursor, limit=limit,
            response_metadata={"sampleId": "case:synthetic", "packetSafeHash": "f" * 64},
        )
        _assert_transient_view_payload(page, enforce_size=True)
        assert len(json.dumps(page, ensure_ascii=False, indent=2)) <= 12_000
        rows.extend(page["items"])
        if page["complete"]:
            return rows
        assert page["nextCursor"] == cursor + page["returnedCount"] > cursor
        cursor = page["nextCursor"]


def test_spec_identity_ignores_external_id_across_passives_and_jewels(monkeypatch):
    monkeypatch.setattr(research_packet, "_passive_node_metadata", lambda _version: {
        "101": {"nodeTypes": ["jewel_socket"]}, "202": {"nodeTypes": ["jewel_socket"]},
    })
    packet = _packet('''<Tree activeSpec="01">
      <Spec id="2" classId="2" treeVersion="0_5" nodes="101"><Sockets><Socket nodeId="101" itemId="01"/></Sockets></Spec>
      <Spec id="1" classId="1" treeVersion="0_5" nodes="202"><Sockets><Socket nodeId="202" itemId="2"/></Sockets></Spec>
      </Tree><Items><Item id="1">Rarity: RARE\nFirst Jewel\nRuby</Item><Item id="2">Rarity: RARE\nSecond Jewel\nRuby</Item></Items>''')
    identity = research_packet.active_set_identity(ET.fromstring(packet["rawContext"]["rawXml"]))
    assert identity["issues"] == []
    assert identity["activeSets"]["passiveSpec"] == "1"
    specs = [item for item in _all_rows(packet, "passives") if item["kind"] == "spec"]
    assert [(item["specId"], item["sourceSpecId"], item["classId"], item["activeSpec"])
            for item in specs] == [("1", "2", "2", True), ("2", "1", "1", False)]
    jewels = _all_rows(packet, "jewels")
    assert [(item["specId"], item["name"]) for item in jewels] == [("1", "First Jewel")]
    counts = research_packet.jewel_counts(packet)
    assert counts["activeAllocatedFilled"][0]["specId"] == "1"
    assert counts["otherSpecSocketed"][0]["specId"] == "2"


def test_numeric_set_aliases_are_shared_by_evidence_and_build_identity():
    packet = _packet('''<Skills activeSkillSet="01"><SkillSet id="1"><Skill><Gem nameSpec="Fireball"/></Skill></SkillSet></Skills>
      <Items activeItemSet="01"><Item id="01">Rarity: RARE\nTest Helm\nIron Circlet</Item><ItemSet id="001"><Slot name="Helmet" itemId="1"/></ItemSet></Items>''')
    manifest = research_packet.build_skill_evidence_manifest(packet)
    assert manifest["activeSkillGroups"][0]["groupRef"] == "skill-set:1:group:1"
    gear = _all_rows(packet, "gear")
    assert gear[0]["itemSetId"] == gear[0]["itemId"] == "1"
    assert gear[0]["activeItemSet"] is True
    assert research_packet.inspect_packet(packet)["unslottedItemCount"] == 0


def test_legacy_root_spec_is_readable_in_all_passive_and_jewel_views(monkeypatch):
    monkeypatch.setattr(research_packet, "_passive_node_metadata", lambda _version: {"101": {"nodeTypes": ["jewel_socket"]}})
    packet = _packet('''<Spec id="99" classId="2" treeVersion="0_5" nodes="101"><Sockets><Socket nodeId="101" itemId="1"/></Sockets></Spec>
      <Items><Item id="1">Rarity: RARE\nLegacy Jewel\nRuby</Item></Items>''')
    assert _all_rows(packet, "passives")[0]["specId"] == "1"
    assert _all_rows(packet, "jewels")[0]["name"] == "Legacy Jewel"
    counts = research_packet.jewel_counts(packet)
    assert counts["status"] == "ok"
    assert len(counts["activeAllocatedFilled"]) == 1


@pytest.mark.parametrize("body,section,flag", [
    ('<Skills activeSkillSet="1"><SkillSet id="1"><Skill><Gem nameSpec="Fireball"/></Skill></SkillSet><SkillSet id="01"><Skill><Gem nameSpec="Frostbolt"/></Skill></SkillSet></Skills>', "skills", "activeSkillSet"),
    ('<Tree activeSpec="3"><Spec nodes="101"/><Spec nodes="202"/></Tree>', "passives", "activeSpec"),
    ('<Tree activeSpec="1"><Spec nodes="101"/></Tree><Spec nodes="202"/>', "passives", "activeSpec"),
])
def test_invalid_axis_never_marks_structural_evidence_active(body, section, flag):
    packet = _packet(body)
    assert research_packet.active_set_identity(ET.fromstring(packet["rawContext"]["rawXml"]))["issues"]
    assert all(item[flag] is False for item in _all_rows(packet, section))


@pytest.mark.parametrize("config_count,limit", [(32, 24), (80, 1)])
def test_config_identity_and_inputs_remain_readable_under_real_transport_guard(config_count, limit):
    sets = ''.join(
        f'<ConfigSet id="{index}" title="Scenario {index} {"x" * 80}">'
        + ''.join(f'<Input name="setting_{key}" string="{"v" * 80}"/>' for key in range(25))
        + '</ConfigSet>' for index in range(1, config_count + 1)
    )
    packet = _packet('<Config activeConfigSet="1">' + sets + '</Config>')
    first = research_packet.read_packet_section(packet, section="config", limit=limit)
    _assert_transient_view_payload(first, enforce_size=True)
    assert "configSets" not in first["configIdentity"]
    assert first["configIdentity"]["configSetCount"] == config_count
    _assert_transient_view_payload(research_packet.inspect_packet(packet), enforce_size=True)
    identities = _all_rows(packet, "config-sets", limit=limit)
    assert [item["configSetId"] for item in identities] == [str(i) for i in range(1, config_count + 1)]
    rows = _all_rows(packet, "config")
    assert len(rows) == config_count * 25
    assert len({(item["configSetIndex"], item["name"]) for item in rows}) == config_count * 25


@pytest.mark.parametrize("section,field", [("config", "value"), ("config-sets", "title")])
def test_oversized_configuration_item_has_lossless_continuation(section, field):
    long_text = "a condition requiring explicit verification; " * 600
    packet = _packet(f'<Config activeConfigSet="1"><ConfigSet id="1" title="{long_text if field == "title" else "Default"}"><Input name="custom" string="{long_text if field == "value" else "value"}"/></ConfigSet></Config>')
    # The view is transient structured evidence; this test exercises pagination, while
    # copy-safety may independently reject unusually long prose at the product boundary.
    cursor = 0
    fragments = []
    while True:
        page = research_packet.read_packet_section(packet, section=section, cursor=cursor, limit=1)
        assert len(json.dumps(page, ensure_ascii=False, indent=2)) <= 12_000
        fragments.extend(page["items"])
        assert "itemDetailTruncated" not in page
        if page["complete"]:
            break
        cursor = page["nextCursor"]
    assert [row["fragmentIndex"] for row in fragments] == list(range(len(fragments)))
    assert all(row["fragmentCount"] == len(fragments) for row in fragments)
    item = json.loads(''.join(row["jsonFragment"] for row in fragments))
    assert item[field] == long_text


def test_normalized_structures_keep_readback_bound_and_reject_stale_snapshot(monkeypatch):
    packet = _packet('<Skills activeSkillSet="01"><SkillSet id="1"><Skill><Gem nameSpec="Fireball"/></Skill></SkillSet></Skills><Tree activeSpec="01"><Spec id="2" classId="2"/><Spec id="1" classId="1"/></Tree>')

    class Engine:
        def __init__(self, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def load_build_xml(self, xml, **_kwargs): self.xml = xml
        def get_stats(self, _keys): return {"stats": {"Mana": 100}}
        def get_build(self): return {}
        def get_xml(self): return self.xml.replace('activeSkillSet="01"', 'activeSkillSet="1"').replace('activeSpec="01"', 'activeSpec="1"')
        def inspect_reservation_ledger(self):
            from server.compute.state import build_state_hash
            return {"schemaVersion": "pob_reservation_ledger_v1", "status": "available",
                    "effects": [], "groups": [],
                    "totals": {pool: {} for pool in ("Life", "Mana", "Spirit")},
                    "activeWeaponSet": self.get_build().get("activeWeaponSet"), "readOnlyVerified": True,
                    "buildStateHash": build_state_hash(self.get_xml())}

    monkeypatch.setattr(research_readback, "PobEngine", Engine)
    packet["pobReadback"] = research_readback.build_safe_readback(packet["rawContext"]["rawXml"], source_hash_ref="source-hash:synthetic", version_context={})
    assert research_packet.validated_pob_readback(packet)["status"] == "available"
    packet["rawContext"]["rawXml"] = packet["rawContext"]["rawXml"].replace('activeSpec="01"', 'activeSpec="2"')
    assert research_packet.validated_pob_readback(packet)["status"] == "unavailable"
