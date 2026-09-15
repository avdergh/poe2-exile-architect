"""H5 delivery keeps real entity categories, embedded art and safe continuous prose."""

from io import BytesIO
import struct

from PIL import Image
import pytest

from server.study.guide import LearningGuide
from server.study.html_document import build_html
from server.study.inline_names import InlineNames
from server.study import passive_art
from tests.test_study_workflow import guide_for
from tests.test_study_icons import component, entry


def test_equipment_aliases_and_passives_get_their_own_categories(tmp_path):
    picture = tmp_path / "icon.png"
    Image.new("RGBA", (32, 32), (40, 80, 120, 255)).save(picture)
    gear = {
        "ref": "c-gear",
        **component("base", "Slipstrike Vest", "gear"),
        "displayAliases": ["Loath Ward"],
    }
    passive = {"ref": "c-passive", **component("node", "Beastial Skin", "passive")}
    catalog = {
        "base": {
            **entry("base", "Slipstrike Vest", kind="gear"),
            "iconKind": "item_base",
            "itemClass": "Body Armour",
        },
        "node": entry("node", "Beastial Skin", kind="passive"),
    }
    assets = {
        identity: {**e, "path": str(picture), "sha256": identity, "width": 32, "height": 32}
        for identity, e in catalog.items()
    }
    source = {gear["ref"]: gear, passive["ref"]: passive}
    g = guide_for([gear, passive])
    g["reader"]["kindLabels"]["gear:Body Armour"] = "胸甲"
    g["concepts"] = [{"term": "Ward", "category": "防御属性", "explanation": "这是属性。"}]
    g["componentNotes"] = {"base": "这件胸甲的名字是 Loath Ward，底材是 Slipstrike Vest。"}
    g["units"][0]["blocks"][0] = {
        "type": "paragraph",
        "text": "Loath Ward 的 Slipstrike Vest 配合 Beastial Skin。Ward 是属性。",
    }
    guide = LearningGuide.model_validate(g)
    inline = InlineNames(catalog, source, "zh", assets)
    html = build_html(guide, title="认识装备", language="zh", components=source, inline=inline)
    assert html.startswith("<!doctype html>") and '<html lang="zh">' in html
    assert 'class="concept"' in html and 'class="entity"' in html
    assert "胸甲" in html and "底材图" in html and "防御属性" in html
    assert "data:image/png;base64," in html
    assert str(tmp_path) not in html
    assert "connect-src &#x27;none&#x27;" in html


def test_h5_escapes_source_text_and_has_no_raw_analysis(tmp_path):
    source = {"c-fixture": {"ref": "c-fixture", **component("p", "Fixture", "passive")}}
    g = guide_for(list(source.values()))
    g["units"][0]["blocks"] = [
        {"type": "paragraph", "text": '</script><img src="https://example.invalid/x">'}
    ]
    guide = LearningGuide.model_validate(g)
    html = build_html(
        guide,
        title="中文学习页",
        language="zh",
        components=source,
        inline=InlineNames({}, source, "zh"),
    )
    assert '<img src="https://example.invalid/x">' not in html
    assert "&lt;/script&gt;" in html
    assert "sourceHash" not in html and "evidenceRefs" not in html


def test_passive_icons_use_exact_one_based_texture_layer(monkeypatch):
    # Two native BC1 layers, red then blue, make off-by-one selection visible.
    header = bytearray(148)
    header[:4] = b"DDS "
    struct.pack_into("<I", header, 4, 124)
    struct.pack_into("<II", header, 12, 4, 4)
    struct.pack_into("<I", header, 28, 1)
    struct.pack_into("<II", header, 76, 32, 4)
    header[84:88] = b"DX10"
    struct.pack_into("<5I", header, 128, 71, 3, 0, 2, 0)
    raw = bytes(header) + struct.pack("<HHI", 0xF800, 0, 0) + struct.pack("<HHI", 0x001F, 0, 0)
    monkeypatch.setattr(passive_art, "_array", lambda *args: raw)
    binding = {
        "treeVersion": "0_5",
        "file": "skills_4_4_BC1.dds.zst",
        "sha256": "fixture",
        "layer": 1,
    }
    with Image.open(BytesIO(passive_art.read_icon(binding))) as image:
        assert image.getpixel((0, 0))[:3] == (255, 0, 0)
    with Image.open(BytesIO(passive_art.read_icon({**binding, "layer": 2}))) as image:
        assert image.getpixel((0, 0))[:3] == (0, 0, 255)
    with pytest.raises(ValueError, match="layer"):
        passive_art.read_icon({**binding, "layer": 3})


def test_bundle_keeps_enabled_passive_icon_arrays(tmp_path):
    from scripts.build_bundle import _copy_study_passive_art

    source, target = tmp_path / "source", tmp_path / "target"
    (source / "0_5").mkdir(parents=True)
    (source / "0_5/skills_64_64_BC1.dds.zst").write_bytes(b"enabled")
    (source / "0_5/skills-disabled_64_64_BC1.dds.zst").write_bytes(b"disabled")
    (source / "0_5/background_1024_1024_BC7.dds.zst").write_bytes(b"background")
    _copy_study_passive_art(source, target)
    assert [p.name for p in (target / "0_5").iterdir()] == ["skills_64_64_BC1.dds.zst"]


def test_magic_base_readback_binds_slot_id_and_serialized_name(monkeypatch):
    from server.study.component_icons import missing_base_names
    from server.compute import engine
    from server.knowledge import research_packet

    source = {
        "base": "",
        "activeItemSet": True,
        "slot": "Flask 1",
        "itemId": "8",
        "itemSetId": "1",
        "name": "Magic Flask Name",
    }
    observed = dict(source)

    class Readback:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def load_build_xml(self, *args, **kwargs):
            pass

        def get_xml(self):
            return "fixture"

        def get_build(self):
            return {"gear": {"Flask 1": {"base": "Ultimate Life Flask"}}}

    monkeypatch.setattr(engine, "PobEngine", Readback)
    monkeypatch.setattr(research_packet, "_packet_sections", lambda p: {"gear": [observed]})
    assert missing_base_names("fixture", [source]) == {"Flask 1": "Ultimate Life Flask"}
    observed["itemId"] = "other"
    assert missing_base_names("fixture", [source]) == {}
