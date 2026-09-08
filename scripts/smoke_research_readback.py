"""Pinned-PoB E2E smoke for the Research active-snapshot readback."""

from __future__ import annotations

from pathlib import Path
import sys
import copy
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.compute.engine import PobEngine  # noqa: E402
from server.knowledge import research_packet, research_readback  # noqa: E402


def main() -> int:
    with PobEngine(show_engine_logs=False) as engine:
        engine.new_build()
        engine.paste_skill("Fireball 20/0  1")
        xml = engine.get_xml()
    result = research_readback.build_safe_readback(
        xml,
        source_hash_ref="source-hash:readback-smoke",
        version_context={"pobVersionOrCommit": "pinned"},
    )
    if result.get("status") != "available":
        raise RuntimeError(f"Research readback unavailable: {result.get('errorCode')}")
    if result.get("stateBinding", {}).get("weaponSetState") != "active":
        raise RuntimeError("Research readback did not bind the active weapon state")
    if any(key in result.get("stats", {}) for key in ("TotalDPS", "FullDPS")):
        raise RuntimeError("Research readback exposed out-of-scope damage metrics")
    serialized = str(result).casefold()
    if "<pathofbuilding" in serialized or "rawxml" in serialized:
        raise RuntimeError("Research readback exposed raw source material")
    # Exercise source structure selectors against the real pinned loader. Spec.id is an
    # ignored external alias; numeric skill/item IDs are normalized by tonumber upstream.
    root = ET.fromstring(xml)
    tree = root.find("Tree")
    assert tree is not None
    first = tree.findall("Spec")[0]
    second = copy.deepcopy(first)
    first.set("id", "2")
    second.set("id", "1")
    second.set("classId", "1" if first.get("classId") != "1" else "2")
    tree.append(second)
    tree.set("activeSpec", "01")
    for section, selector in (("Skills", "activeSkillSet"), ("Items", "activeItemSet")):
        node = root.find(section)
        assert node is not None
        node.set(selector, "0" + str(node.get(selector)))
    source_xml = ET.tostring(root, encoding="unicode")
    normalized = research_readback.build_safe_readback(
        source_xml, source_hash_ref="source-hash:selection-smoke", version_context={},
    )
    if normalized.get("status") != "available":
        raise RuntimeError(f"Research selection readback unavailable: {normalized.get('errorCode')}")
    packet = {"rawContext": {"rawXml": source_xml}, "pobReadback": normalized,
              "safeMetadata": {"sourceRef": "source-hash:selection-smoke"}}
    specs = [item for item in research_packet.read_packet_section(packet, section="passives")["items"]
             if item.get("kind") == "spec" and item.get("activeSpec")]
    if len(specs) != 1 or specs[0]["classId"] != first.get("classId") or specs[0]["specId"] != "1":
        raise RuntimeError("Research structural evidence selected a different passive instance")
    if not research_packet.build_skill_evidence_manifest(packet)["activeSkillGroups"]:
        raise RuntimeError("Research structural evidence lost the canonical active skill set")
    if research_packet.validated_pob_readback(packet).get("status") != "available":
        raise RuntimeError("Research canonical source readback lost its valid binding")
    print("RESEARCH READBACK SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
