"""Synthetic sources exercise the complete non-writing educational lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from server.study import analysis, service, storage
from server.study.models import CHAPTERS


SYNTHETIC_XML = """<PathOfBuilding>
<Build level="80" className="Sorceress" ascendClassName="Stormweaver" mainSocketGroup="1"/>
<Skills activeSkillSet="1"><SkillSet id="1"><Skill enabled="true" mainActiveSkill="1">
<Gem nameSpec="Spark" gemId="Metadata/Items/Gems/SkillGemSpark" skillId="SparkPlayer" level="18" enabled="true"/>
<Gem nameSpec="Arcane Tempo" gemId="Metadata/Items/Gems/SupportGemFasterCast" skillId="SupportFasterCastPlayer" level="1" enabled="true"/>
</Skill></SkillSet></Skills>
<Items activeItemSet="1"><Item id="1">Rarity: RARE
Synthetic Example
Withered Wand
Item Level: 80
10% increased Spell Damage</Item><ItemSet id="1"><Slot name="Weapon 1" itemId="1"/></ItemSet></Items>
<Tree activeSpec="1"><Spec id="1" treeVersion="0_5" classId="3" ascendClassId="1" nodes="4"/></Tree>
<Config activeConfigSet="1"><ConfigSet id="1" title="Synthetic"><Input name="enemyIsBoss" string="Pinnacle"/></ConfigSet></Config>
</PathOfBuilding>"""


def bilingual(en="Reviewed fixture.", zh="测试审读。"):
    return {"en": en, "zh": zh}


@pytest.fixture
def study(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path / "user"))
    monkeypatch.setattr(analysis, "_exact", lambda table, name, identity="": None)
    file = tmp_path / "synthetic.xml"
    file.write_text(SYNTHETIC_XML, encoding="utf-8")
    # Test art is a local PNG fixture; workflow tests never use network game images.
    from server.study import icon_catalog, icons
    from PIL import Image

    image_path = tmp_path / "fixture.png"
    Image.new("RGBA", (24, 24), (50, 90, 130, 255)).save(image_path)
    binding = {
        "identity": "Metadata/Items/Gems/SkillGemSpark",
        "name": "Spark",
        "iconPath": "Art/2DArt/SkillIcons/4k/SorceressSpark.dds",
        "bindingHash": "fixture-spark",
    }
    monkeypatch.setattr(icon_catalog, "load_catalog", lambda: {binding["identity"]: binding})
    monkeypatch.setattr(
        icons,
        "prepare",
        lambda entries, cache: {
            key: {
                **value,
                "path": str(image_path),
                "sha256": storage.fingerprint(image_path.read_bytes()),
                "width": 24,
                "height": 24,
                "url": "fixture:local",
            }
            for key, value in entries.items()
        },
    )
    return service.start(source_file=str(file), source_patch="0.5.5", user_language="zh")


def read_all(run_ref):
    from server.knowledge.research_packet import RESEARCH_READ_ORDER

    refs = []
    for section in RESEARCH_READ_ORDER:
        cursor = 0
        while True:
            page = service.read(run_ref, section, cursor=cursor)
            refs.append(page["evidenceRef"])
            if page["complete"]:
                break
            cursor = page["nextCursor"]
    return refs


def lesson_for(run_ref):
    from server.study.models import DepthReview

    refs = read_all(run_ref)
    contract = service.contract(run_ref)
    rows = contract["components"]
    direct = [c for c in rows if c["kind"] in {"skill", "support", "gear", "jewel"}]
    passive = [c for c in rows if c["kind"] in {"passive", "ascendancy"}]
    groups = sorted({c["groupRef"] for c in rows if c.get("groupRef")})
    notes = []
    for row in direct:
        note = dict(
            componentRef=row["ref"],
            role="合成测试职责",
            sourceFacts=["测试来源中的组件"],
            reasoning="只测试合同，不把此说明作为真实 BD 攻略。",
            synergies=[],
            conditions="合成来源",
            tradeoffs="未完成构筑",
            failureModes="不能作为终局推荐",
            evidenceRefs=list(refs),
            status="inferred",
        )
        if row["kind"] in {"skill", "support"}:
            note["gemAnalysis"] = dict(
                effectRole="测试技能或辅助",
                levelQuality="读取源等级；无品质加成声明",
                application="只验证组内对应",
                targetRefs=[
                    c["ref"]
                    for c in rows
                    if c.get("groupRef") == row["groupRef"] and c["kind"] == "skill"
                ],
            )
        notes.append(note)
    return dict(
        schemaVersion="study_explanation_v5",
        sourceHash=contract["sourceHash"],
        language=contract["outputLanguage"],
        title="合成来源合同验证",
        chapters=[dict(key=k, paragraphs=["仅供合同测试。"], evidenceRefs=refs) for k in CHAPTERS],
        components=notes,
        mechanisms=[
            dict(
                id=k,
                chapter=k,
                title=k,
                chain=["合成输入", "观察输出"],
                componentRefs=[direct[0]["ref"]],
                scaling="无数值声明",
                conditions="测试状态",
                tradeoffs="未完成",
                failureModes="不推荐",
                evidenceRefs=refs,
                status="inferred",
            )
            for k in ("offense", "rotation")
        ],
        skillGroups=[
            dict(
                groupRef=g,
                role="组内职责",
                outputMode="测试输出",
                sequence="先确认组内对象",
                supportLogic="逐辅助检查",
                conditions="合成条件",
                failureModes="未验证机制",
                evidenceRefs=refs,
            )
            for g in groups
        ],
        passivePlan=dict(
            attributesSought=["测试属性"],
            pathLogic="只测试覆盖",
            clusters=[
                dict(
                    title="合成天赋",
                    componentRefs=[c["ref"] for c in passive],
                    purpose="覆盖",
                    scaling="无声明",
                    keyPointNotes={c["ref"]: "测试节点说明" for c in passive},
                    conditions="测试",
                    tradeoffs="测试",
                    evidenceRefs=refs,
                )
            ]
            if passive
            else [],
        ),
        depthReview={
            k: ("仅验证结构；不声明已评估真实讲解质量。" if k == "summary" else True)
            for k in DepthReview.model_fields
        },
        guide=guide_for(rows, contract["outputLanguage"]),
    )


def guide_for(rows, language="zh"):
    guide = {
        "reader": {
            "searchPlaceholder": "搜索名称",
            "clearSearch": "清除",
            "noResults": "没有结果",
            "showAll": "显示全部",
            "componentDetails": "名称说明",
            "closeDetails": "关闭",
            "jumpToExplanation": "查看正文",
            "helpText": "点击名称查看类型。",
            "kindLabels": {
                "active": "技能",
                "skill": "技能",
                "support": "辅助",
                "granted_skill": "授予技能",
                "gear": "装备",
                "unique": "暗金装备",
                "passive": "天赋",
                "ascendancy": "升华天赋",
                "socketable": "镶嵌物",
                "concept": "概念",
                "item_base": "底材图",
            },
        },
        "navigationTitle": "阅读路线",
        "subtitle": "从一次施放开始理解配套",
        "introduction": "先认识主技能，再看辅助如何改变动作。",
        "chatIntroduction": "学习文档已整理，建议先读技能配合图。",
        "units": [
            {
                "title": "先看主技能怎样完成输出",
                "introduction": "技能承担输出，辅助改变它的使用方式。",
                "topics": list(CHAPTERS),
                "componentRefs": [c["ref"] for c in rows],
                "groupRefs": sorted({c["groupRef"] for c in rows if c.get("groupRef")}),
                "mechanismRefs": ["offense", "rotation"],
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": "阅读 {{" + rows[0]["ref"] + "}} 时，先找到伤害来自哪个技能。",
                    },
                    {
                        "type": "flow",
                        "title": "一次技能使用",
                        "steps": [
                            {"label": "施放技能", "explanation": "输入动作"},
                            {"label": "命中敌人", "explanation": "建立输出事件"},
                        ],
                    },
                    {
                        "type": "note",
                        "kind": "practice",
                        "title": "观察一个动作",
                        "text": "留意投射物是否接触目标。",
                    },
                    {
                        "type": "table",
                        "columns": ["对象", "作用"],
                        "rows": [["主技能", "承担输出"], ["辅助", "改变技能行为"]],
                    },
                ],
            }
        ],
        "teachingReview": {
            "languageConsistent": True,
            "readerJourneyReviewed": True,
            "detailPreserved": True,
            "conditionsExplainedInContext": True,
            "visualsExplainRelationships": True,
            "noAuditDump": True,
            "summary": "测试教学层与内部分析分离。",
        },
    }
    if language.startswith("en"):
        guide["reader"] = {
            "searchPlaceholder": "Search names",
            "clearSearch": "Clear",
            "noResults": "No results",
            "showAll": "Show all",
            "componentDetails": "About this name",
            "closeDetails": "Close",
            "jumpToExplanation": "Read explanation",
            "helpText": "Select a name to see its category.",
            "kindLabels": {
                "active": "Skill",
                "skill": "Skill",
                "support": "Support",
                "granted_skill": "Granted skill",
                "gear": "Equipment",
                "unique": "Unique",
                "passive": "Passive",
                "ascendancy": "Ascendancy",
                "socketable": "Socketable",
                "concept": "Concept",
                "item_base": "Base item art",
            },
        }
        guide.update(
            navigationTitle="Reading route",
            subtitle="Understand the skill's role",
            introduction="Begin with one cast, then study its supports.",
            chatIntroduction="The guide explains the skill step by step.",
        )
        guide["units"][0].update(
            title="Understand one cast",
            introduction="Find the damage source before comparing supports.",
            blocks=[
                {
                    "type": "paragraph",
                    "text": "Study {{" + rows[0]["ref"] + "}} and its actual output.",
                },
                {
                    "type": "flow",
                    "title": "One cast",
                    "steps": [
                        {"label": "Cast", "explanation": "Use the selected skill."},
                        {"label": "Hit", "explanation": "Observe contact with the target."},
                    ],
                },
            ],
        )
    return guide


def test_complete_returns_learning_document_without_leaking_internal_analysis(study):
    ref = study["runRef"]
    lesson = lesson_for(ref)
    checked = service.validate_lesson(ref, lesson)
    assert checked["status"] == "valid", checked
    result = service.complete(ref, lesson)
    assert result["delivery"] == "learning_document"
    assert set(result["files"]) == {"learning-guide.html", "learning-guide.md"}
    markdown = Path(result["files"]["learning-guide.md"]["path"]).read_text("utf-8")
    assert "Spark" in markdown
    assert "先看主技能怎样完成输出" in markdown
    assert "仅供合同测试" not in markdown
    assert "合成测试职责" not in markdown
    assert "evidenceRef" not in markdown
    html = Path(result["files"]["learning-guide.html"]["path"]).read_text("utf-8")
    assert html.startswith("<!doctype html>")
    assert 'lang="zh"' in html
    assert "data:image/png;base64," in html
    assert "仅供合同测试" not in html and "合成测试职责" not in html
    assert "markdown" not in result and "html" not in result
    assert {p.name for p in storage.root().parent.iterdir()} - {".corpus-update.lock"} == {"study"}
    assert not list(storage.root().rglob("*.pdf"))
    assert lesson["title"] not in (storage.directory(ref) / "run.json").read_text("utf-8")
    assert service.complete(ref, lesson)["explanationHash"] == result["explanationHash"]
    assert service.cleanup(ref)["rawSourceRemoved"]
    assert Path(result["files"]["learning-guide.html"]["path"]).is_file()
    with pytest.raises(storage.StudyError, match="cleaned"):
        service.read(ref, "skills")


@pytest.mark.parametrize(
    "change,code",
    [
        ("chapter", "study_explanation_schema"),
        ("v1", "study_explanation_schema"),
        ("component", "study_component_coverage_incomplete"),
        ("gem", "study_gem_detail_required"),
        ("target", "study_support_target_required"),
        ("wrong_target", "study_support_target_not_in_group"),
        ("group", "study_skill_group_coverage_incomplete"),
        ("mechanism", "study_output_mechanism_required"),
        ("passive", "study_passive_coverage_incomplete"),
        ("source", "study_explanation_source_mismatch"),
        ("evidence", "study_evidence_not_from_run"),
        ("raw", "study_explanation_raw_material"),
        ("token", "study_unknown_name_token"),
        ("guide", "study_guide_coverage_incomplete"),
        ("guide_flow", "study_guide_mechanism_visual_required"),
        ("language_review", "study_explanation_schema"),
    ],
)
def test_depth_and_source_failures_cannot_complete(study, change, code):
    ref = study["runRef"]
    lesson = lesson_for(ref)
    if change == "chapter":
        lesson["chapters"].pop()
    elif change == "v1":
        lesson["schemaVersion"] = "study_lesson_v1"
    elif change == "component":
        lesson["components"].pop()
    elif change == "gem":
        lesson["components"][0]["gemAnalysis"] = None
    elif change == "target":
        lesson["components"][1]["gemAnalysis"]["targetRefs"] = []
    elif change == "wrong_target":
        lesson["components"][1]["gemAnalysis"]["targetRefs"] = [
            lesson["components"][-1]["componentRef"]
        ]
    elif change == "group":
        lesson["skillGroups"].clear()
    elif change == "mechanism":
        lesson["mechanisms"] = [m for m in lesson["mechanisms"] if m["chapter"] != "offense"]
    elif change == "passive":
        lesson["passivePlan"]["clusters"].clear()
    elif change == "source":
        lesson["sourceHash"] = "0" * 64
    elif change == "evidence":
        lesson["components"][0]["evidenceRefs"] = ["study-evidence:other"]
    elif change == "raw":
        lesson["chapters"][0]["paragraphs"] = ["<PathOfBuilding>raw"]
    elif change == "guide":
        lesson["guide"]["units"][0]["componentRefs"].pop()
    elif change == "guide_flow":
        lesson["guide"]["units"][0]["blocks"] = [{"type": "paragraph", "text": "只有段落"}]
    elif change == "language_review":
        lesson["guide"]["teachingReview"]["languageConsistent"] = False
    else:
        lesson["chapters"][0]["paragraphs"] = ["{{c-nonexistent}}"]
    result = service.complete(ref, lesson)
    assert result["status"] == "needs_revision"
    assert code in [i["code"] for i in result["issues"]]
    assert "markdown" not in result


def test_read_coverage_cannot_be_skipped(study):
    ref = study["runRef"]
    service.read(ref, "skills", cursor=99)
    assert service.inspect(ref)["coverage"]["skills"]["complete"] is False
    lesson = lesson_for(ref)
    directory = storage.directory(ref)
    meta = storage.read_json(directory / "run.json")
    meta["coverage"]["gear"]["complete"] = False
    storage.atomic_json(directory / "run.json", meta)
    assert "study_source_read_incomplete" in [
        i["code"] for i in service.validate_lesson(ref, lesson)["issues"]
    ]


def test_supported_requires_subject_corroboration(study):
    ref = study["runRef"]
    lesson = lesson_for(ref)
    lesson["components"][0]["status"] = "supported"
    assert "study_causal_corroboration_missing" in [
        i["code"] for i in service.validate_lesson(ref, lesson)["issues"]
    ]
    evidence = service.review_evidence(
        ref,
        subject_refs=[lesson["components"][0]["componentRef"]],
        source_ref="fixture:review",
        conclusion=bilingual(),
        relevance=bilingual(),
        finding="supports",
    )
    lesson["components"][0]["evidenceRefs"].append(evidence["evidenceRef"])
    assert service.validate_lesson(ref, lesson)["status"] == "valid"


def test_source_tampering_and_expiry_cannot_resume(study):
    ref = study["runRef"]
    path = storage.directory(ref)
    with pytest.raises(storage.StudyError, match="cleanup_requires"):
        service.cleanup(ref)
    (path / "quarantine" / "source.xml").write_text(
        SYNTHETIC_XML.replace('level="80"', 'level="81"'), encoding="utf-8"
    )
    with pytest.raises(storage.StudyError, match="hash_mismatch"):
        service.read(ref, "skills")
    meta = storage.read_json(path / "run.json")
    meta["expiresAt"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    storage.atomic_json(path / "run.json", meta)
    with pytest.raises(storage.StudyError, match="expired"):
        service.contract(ref)
    assert service.cleanup(ref)["rawSourceRemoved"]


def test_english_delivery_follows_user_without_explicit_output_override(study, tmp_path):
    run = service.start(source_file=str(tmp_path / "synthetic.xml"), user_language="en")
    lesson = lesson_for(run["runRef"])
    lesson["title"] = "English fixture"
    lesson["guide"]["units"][0]["title"] = "Understand one cast"
    result = service.complete(run["runRef"], lesson)
    text = Path(result["files"]["learning-guide.md"]["path"]).read_text("utf-8")
    assert "## Understand one cast" in text
    assert "## 输出机制" not in text
    assert result["language"] == "en"


def test_language_mismatch_rejected_even_with_english_skill_names(study):
    lesson = lesson_for(study["runRef"])
    lesson["language"] = "en"
    result = service.complete(study["runRef"], lesson)
    assert result["status"] == "needs_revision"
    assert "study_language_mismatch" in [x["code"] for x in result["issues"]]


def test_explicit_language_override_and_locale_are_preserved(study, tmp_path):
    run = service.start(
        source_file=str(tmp_path / "synthetic.xml"), user_language="zh-CN", output_language="en-GB"
    )
    assert run["userLanguage"] == "zh"
    assert run["outputLanguage"] == "en-GB"
    assert run["languageSelection"] == "explicit_user_override"
    with pytest.raises(TypeError):
        service.start(source_file=str(tmp_path / "synthetic.xml"))


def test_published_document_is_verified_before_reuse(study):
    ref = study["runRef"]
    lesson = lesson_for(ref)
    result = service.complete(ref, lesson)
    Path(result["files"]["learning-guide.html"]["path"]).write_bytes(b"changed")
    with pytest.raises(storage.StudyError, match="integrity_failed"):
        service.complete(ref, lesson)


def test_critical_passive_needs_individual_explanation(study):
    from server.study.validation import validate

    ref = study["runRef"]
    lesson = lesson_for(ref)
    meta = storage.read_json(storage.directory(ref) / "run.json")
    components = {c["ref"]: c for c in service.contract(ref)["components"]}
    passive = next(c for c in components.values() if c["kind"] == "passive")
    passive["nodeTypes"] = ["notable"]
    lesson["passivePlan"]["clusters"][0]["keyPointNotes"].clear()
    _, issues = validate(lesson, meta, components)
    assert "study_key_passive_explanation_missing" in [i["code"] for i in issues]


def test_official_name_review_is_per_run_and_source_bound(study, monkeypatch):
    from server.study import localization

    ref = study["runRef"]
    row = service.contract(ref)["components"][0]
    excerpt = row["name"]["en"] + " 官方测试词"
    raw = ("<h1>" + row["name"]["en"] + "</h1><span>官方测试词</span>").encode()

    class Page:
        url = "https://www.pathofexile2.com/test-fixture"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            return raw

    monkeypatch.setattr(localization, "urlopen", lambda *args, **kwargs: Page())
    arguments = dict(
        component_ref=row["ref"],
        chinese_name="官方测试词",
        source_url=Page.url,
        bilingual_excerpt=excerpt,
        review_basis=bilingual(),
        same_entity_reviewed=True,
        official_publisher_reviewed=True,
    )
    with pytest.raises(storage.StudyError, match="requires_official"):
        service.review_terminology(
            ref, **{**arguments, "source_url": "https://poe2db.tw/cn/example"}
        )
    with pytest.raises(storage.StudyError, match="not_bound"):
        service.review_terminology(ref, **{**arguments, "chinese_name": "自造词"})
    result = service.review_terminology(ref, **arguments)
    assert result["authority"] == "agent_reviewed"
    assert service.contract(ref)["components"][0]["name"]["zh"] == "官方测试词"
    assert json.loads(localization.CATALOG.read_text("utf-8"))["entries"] == []
