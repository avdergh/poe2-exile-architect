"""Exact identity, semantic name boundaries, all presentation surfaces and asset failures."""

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import json
import sqlite3

from PIL import Image
import pytest

from server.study import icons, icon_catalog, storage
from server.study.inline_names import InlineNames, Mention, visible_text
from server.study.guide import LearningGuide
from server.study.language import localized_name, normalize_language


def entry(identity, name, path="Art/2DArt/SkillIcons/Support/4k/Fixture.dds", kind="support"):
    data = dict(identity=identity, name=name, iconPath=path, kind=kind, sourceRef="fixture:static")
    return {**data, "bindingHash": storage.fingerprint(data)}


def component(identity, name, kind="support"):
    return dict(identity=identity, kind=kind, name={"en": name, "zh": name})


def test_effect_icon_boundaries_preserve_invalid_and_duplicate_declarations():
    raw = '''skills["Broken"] = {
\tname = "Wrong",
skills["Child"] = {
\tname = "Child effect",
\ticon = "Art/2DArt/Child.dds",
} end
skills["Child"] = {
\tname = "Conflicting effect",
\ticon = "Art/2DArt/Other.dds",
}
skills["Expression"] = {
\tname = "Unsafe",
\ticon = execute(),
}
'''
    assert icon_catalog._effect_icons(raw) == [
        ("Broken", None),
        ("Child", {"name": "Child effect", "icon": "Art/2DArt/Child.dds"}),
        ("Child", {"name": "Conflicting effect", "icon": "Art/2DArt/Other.dds"}),
        ("Expression", None),
    ]


def test_exact_tier_longest_name_and_repeated_mentions():
    catalog = {
        i: entry(i, n) for i, n in [("g1", "Armour Demolisher I"), ("g2", "Armour Demolisher II")]
    }
    source = {
        "c-1": component("g1", "Armour Demolisher I"),
        "c-2": component("g2", "Armour Demolisher II"),
    }
    inline = InlineNames(catalog, source, "zh")
    result = inline.split(
        "Armour Demolisher II、Armour Demolisher I，{{c-2}}。Armour Demolisher III"
    )
    assert [x.identity for x in result if isinstance(x, Mention)] == ["g2", "g1", "g2"]


def test_mechanics_and_passive_names_never_borrow_skill_icons():
    catalog = {
        "g1": entry("g1", "Flow"),
        "g2": entry("g2", "Shock"),
        "child": entry("child", "Projectile", kind="granted_skill"),
    }
    source = {
        "c-1": component("g1", "Flow"),
        "c-2": component("g2", "Shock"),
        "c-3": component("p1", "Flow State", "passive"),
    }
    inline = InlineNames(catalog, source, "zh")
    parts = inline.split("Flow State，{{term:Shock}} 状态，Projectile 速度。{{c-2}} 辅助。")
    assert [x.identity for x in parts if isinstance(x, Mention)] == ["g2"]
    assert inline.plain("{{term:Shock}} 状态") == "Shock 状态"


def test_additional_skill_identity_is_explicit_and_typography_keeps_identity():
    catalog = {
        "child": entry("child", "Gale Force", kind="granted_skill"),
        "gem": entry("gem", "Rakiata's Flow"),
    }
    source = {"c-gem": component("gem", "Rakiata's Flow")}
    inline = InlineNames(catalog, source, "zh", skill_refs=["child"])
    assert [
        x.identity for x in inline.split("Gale Force 和 Rakiata’s Flow") if isinstance(x, Mention)
    ] == ["child", "gem"]
    assert not any(
        isinstance(x, Mention) for x in InlineNames(catalog, {}, "en").split("Gale Force")
    )


def test_chinese_name_is_a_verified_alias_not_document_language():
    c = component("gem", "Spark", "skill")
    c["name"]["zh"] = "官方名称测试"
    inline = InlineNames({"gem": entry("gem", "Spark")}, {"c-gem": c}, "zh")
    assert [
        x.identity for x in inline.split("官方名称测试 和 Spark") if isinstance(x, Mention)
    ] == ["gem", "gem"]
    assert localized_name(c, "fr") == "Spark"
    assert normalize_language("zh-CN") == "zh"
    assert normalize_language("en-gb") == "en-GB"


def test_icon_url_never_guesses_or_accepts_foreign_paths():
    for path in [
        "4k/",
        "../../icon.dds",
        "Art/2DArt/SkillIcons/../secret.dds",
        "https://example.com/icon.dds",
    ]:
        assert icons.icon_url(path) is None
    assert icons.icon_url("Art/2DItems/Gems/Unique/Fixture.dds").endswith(
        "Art/2DItems/Gems/Unique/Fixture.webp"
    )


def test_exact_gem_item_fallback_is_bound_to_the_same_id(tmp_path, monkeypatch):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE gems(id TEXT,name TEXT,raw TEXT)")
    con.execute("CREATE TABLE items(id TEXT,name TEXT,raw TEXT)")
    con.execute(
        "INSERT INTO gems VALUES (?,?,?)",
        ("g1", "Unique Support", json.dumps({"icon_dds_file": "4k/", "gem_type": "support"})),
    )
    con.execute(
        "INSERT INTO items VALUES (?,?,?)",
        (
            "g1",
            "Unique Support",
            json.dumps({"visual_identity": {"dds_file": "Art/2DItems/Gems/Unique/Fixture.dds"}}),
        ),
    )
    monkeypatch.setattr(icon_catalog.db, "_conn", lambda: con)
    monkeypatch.setattr(
        icon_catalog.paths, "pob_runtime_pair", lambda: SimpleNamespace(src_dir=tmp_path)
    )
    bound = icon_catalog.load_catalog()["g1"]
    assert bound["iconKind"] == "exact_gem_item"
    assert bound["iconPath"].endswith("Fixture.dds")
    con.execute("UPDATE items SET id='other'")
    assert icon_catalog.load_catalog()["g1"]["iconPath"] == "4k/"


def test_download_failure_and_changed_cache_cannot_return_wrong_art(tmp_path, monkeypatch):
    b = BytesIO()
    Image.new("RGBA", (32, 32), (30, 60, 90, 255)).save(b, format="PNG")
    monkeypatch.setattr(icons, "_download", lambda url: b.getvalue())
    e = entry("g1", "Fixture")
    result = icons.prepare({"g1": e}, tmp_path)["g1"]
    assert result["identity"] == "g1"
    Path(result["path"]).write_bytes(b"corrupt")
    monkeypatch.setattr(icons, "_download", lambda url: b"<html>not an image</html>")
    with pytest.raises(icons.IconCoverageError):
        icons.prepare({"g1": e}, tmp_path)


def test_all_visible_text_surfaces_pass_through_the_same_icon_renderer(tmp_path):
    from server.study.pdf_document import build_pdf
    from tests.test_study_workflow import guide_for

    c = {"ref": "c-gem", "groupRef": "group", **component("g1", "Spark", "skill")}
    g = guide_for([c])
    g["navigationTitle"] = "Spark 阅读路线"
    g["subtitle"] = "Spark 副标题"
    g["introduction"] = "Spark 导读"
    g["units"][0].update(title="Spark 章节", introduction="Spark 开始")
    g["units"][0]["blocks"] = [
        {"type": "heading", "text": "Spark 标题"},
        {"type": "paragraph", "text": "Spark 正文"},
        {"type": "bullets", "items": ["Spark 列表"]},
        {"type": "table", "columns": ["Spark 列名", "职责"], "rows": [["Spark 单元格", "测试"]]},
        {"type": "note", "kind": "remember", "title": "Spark 提示", "text": "Spark 说明"},
        {
            "type": "flow",
            "title": "Spark 流程",
            "steps": [
                {"label": "Spark 步骤一", "explanation": "Spark 描述一"},
                {"label": "Spark 步骤二", "explanation": "Spark 描述二"},
            ],
        },
    ]
    guide = LearningGuide.model_validate(g)
    image = tmp_path / "icon.png"
    Image.new("RGBA", (24, 24), (50, 80, 120, 255)).save(image)
    seen = []

    class TracedInline(InlineNames):
        def pdf(self, value, size=12):
            seen.append(value)
            return super().pdf(value, size)

    inline = TracedInline(
        {"g1": entry("g1", "Spark")},
        {"c-gem": c},
        "zh",
        {"g1": {"path": str(image), "width": 24, "height": 24}},
    )
    result = build_pdf(
        guide, title="Spark 封面", language="zh", components={"c-gem": c}, inline=inline
    )
    assert result.startswith(b"%PDF-")
    assert b"/Lang (zh)" in result
    assert set(visible_text(guide, "Spark 封面")) <= set(seen)
    assert inline.pdf("Spark Spark").count("<img ") == 2


def test_inline_icon_never_wraps_without_its_skill_word(tmp_path):
    from reportlab.lib.styles import ParagraphStyle
    from server.study.pdf_inline import Paragraph

    image = tmp_path / "icon.png"
    Image.new("RGBA", (24, 24), (50, 80, 120, 255)).save(image)
    inline = InlineNames(
        {"g1": entry("g1", "Spark")},
        {"c-1": component("g1", "Spark")},
        "en",
        {"g1": {"path": str(image), "width": 24, "height": 24}},
    )
    for width in range(90, 180, 7):
        para = Paragraph(
            inline.pdf("A short setup before Spark. Then use Spark again. " * 3),
            ParagraphStyle("inline", fontName="Helvetica", fontSize=11, leading=18),
        )
        para.wrap(width, 1000)
        for line in para.blPara.lines:
            preceding = ""
            for fragment in line.words:
                if getattr(getattr(fragment, "cbDefn", None), "kind", None) == "img":
                    assert preceding.rstrip().endswith("Spark")
                else:
                    preceding += fragment.text


def test_language_rule_precedes_other_skill_and_host_instructions():
    root = Path(__file__).resolve().parents[1]
    for path in (
        root / "poe-bd-creator-plugin/skills/poe-bd-learn/SKILL.md",
        root / "dsh/agent-presets/poe-bd/skills/poe-bd-learn/SKILL.md",
    ):
        text = path.read_text("utf-8")
        body = text.split("---", 2)[2].lstrip()
        assert body.startswith("# 最高优先级 输出语言必须与用户一致")
        assert "不根据 PoB、网页、技能名或辅助名中的英文切换" in body
