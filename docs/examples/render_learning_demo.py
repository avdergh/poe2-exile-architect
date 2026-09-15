"""用实际 Learn 阅读器生成双语 README 演示；不启动研究、不写知识库、不读取 BD 或游戏美术。

在仓库根目录运行：uv run python docs/examples/render_learning_demo.py
演示仅检查教学层模型并渲染，不经过完整 BD 分析、覆盖验收或 PoB/Judge。
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from server.study.guide import LearningGuide  # noqa: E402
from server.study.html_document import build_html  # noqa: E402
from server.study.inline_names import InlineNames  # noqa: E402


def demo(language):
    def t(zh, en):
        return zh if language == "zh-CN" else en

    def unit(title, intro, blocks):
        return dict(title=title, introduction=intro, blocks=blocks,
                    topics=["demo"], componentRefs=[], groupRefs=[], mechanismRefs=[])

    title = t("读懂一个 BD：从动作到配套", "Understanding a build: from actions to choices")
    labels = {
        "active": t("技能", "Skill"), "skill": t("技能", "Skill"),
        "support": t("辅助", "Support"), "granted_skill": t("授予技能", "Granted skill"),
        "gear": t("装备", "Equipment"), "unique": t("暗金装备", "Unique"),
        "passive": t("天赋", "Passive"), "ascendancy": t("升华天赋", "Ascendancy"),
        "socketable": t("镶嵌物", "Socketable"), "concept": t("概念", "Concept"),
        "item_base": t("底材图", "Base item art"),
    }
    guide = LearningGuide.model_validate({
        "reader": {
            "searchPlaceholder": t("搜索章节与概念", "Search chapters and concepts"),
            "clearSearch": t("清除", "Clear"), "noResults": t("没有找到相关章节", "No matching chapters"),
            "showAll": t("显示全部", "Show all"), "componentDetails": t("概念说明", "Concept details"),
            "closeDetails": t("关闭", "Close"), "jumpToExplanation": t("查看正文", "Read explanation"),
            "helpText": t("点击带下划线的概念查看解释；使用搜索框筛选章节。", "Select an underlined concept for its explanation, or search to filter chapters."),
            "kindLabels": labels,
        },
        "navigationTitle": t("阅读路线", "Reading route"),
        "subtitle": t("EXILE ARCHITECT / LEARN · 阅读器演示", "EXILE ARCHITECT / LEARN · READER DEMO"),
        "introduction": t("先看战斗中做什么，再理解技能、装备和天赋为何配套。本页为原创阅读器演示，不含玩家构筑、游戏美术或实测数值。", "Start with what happens in combat, then connect skills, equipment, and passives. This original reader demo contains no player build, game artwork, or measured statistics."),
        "chatIntroduction": t("从战斗循环开始阅读，再查看条件和失效场景。", "Start with the combat loop, then review conditions and failure cases."),
        "concepts": [
            {"term": t("战斗循环", "combat loop"), "category": t("操作概念", "Gameplay concept"),
             "explanation": t("一组需要反复完成的动作：建立条件、产生输出、维持资源，以及中断后重新启动。实际顺序应依据具体构筑解释。", "The repeated actions that establish conditions, produce damage, maintain resources, and restart after an interruption. The actual order depends on the build.")},
            {"term": t("模型覆盖", "model coverage"), "category": t("证据概念", "Evidence concept"),
             "explanation": t("计算工具能表示的那部分机制。没有读数不等于没有收益；无法建模的部分应保留未知或另列有依据的估计。", "The mechanics that a calculation tool can represent. A missing reading does not mean no benefit; unsupported behavior remains unknown or receives a separately justified estimate.")},
        ],
        "units": [
            unit(t("先看一轮战斗怎样运转", "Start with one combat loop"),
                 t("先把操作顺序讲清楚，配装选择才有上下文。以下是讲解结构，不是某个技能的机制结论。", "Explain the action sequence before the equipment choices. This is an explanation pattern, not a claim about a particular skill."), [
                {"type": "flow", "title": t("战斗循环：建立 → 输出 → 恢复", "The combat loop: prepare → act → recover"), "steps": [
                    {"label": t("建立条件", "Prepare"), "explanation": t("说明起手动作，以及哪些条件必须先成立。", "Explain the opening action and the conditions it needs.")},
                    {"label": t("完成输出", "Act"), "explanation": t("找到实际伤害来源，区分主技能与配套职责。", "Identify the damage source and the role of each supporting choice.")},
                    {"label": t("维持与重启", "Recover"), "explanation": t("解释资源如何恢复，中断后如何重新开始。", "Explain resource recovery and how to restart after interruption.")},
                ]},
                {"type": "note", "kind": "practice", "title": t("带着一个问题阅读", "A question to keep in mind"),
                 "text": t("遇到每项选择，先问它承担哪一步职责，再看它需要什么条件。", "For each choice, ask which step it supports and what conditions it requires.")},
            ]),
            unit(t("把配套选择放回各自职责", "Connect choices to their roles"),
                 t("同一张面板无法说明所有选择的价值。比较时要把条件一起列出来。", "One stat panel cannot explain every choice. Keep the conditions beside the comparison."), [
                {"type": "table", "columns": [t("对象", "Choice"), t("讲解重点", "What to explain"), t("需要核实", "What to check")], "rows": [
                    [t("技能与辅助", "Skills and supports"), t("输出、触发或维持条件", "Damage, triggers, or upkeep"), t("实际作用对象与资源成本", "Affected skill and resource cost")],
                    [t("装备与天赋", "Equipment and passives"), t("机制配套与防御职责", "Mechanic and defense roles"), t("等级、属性和成立条件", "Level, attributes, and conditions")],
                    [t("战斗配置", "Combat configuration"), t("面板使用了什么情景", "The scenario behind a reading"), t("是否能在实际战斗中维持", "Whether combat can sustain it")],
                ]},
            ]),
            unit(t("把失效场景和未知写在一起", "Explain failure cases and unknowns"),
                 t("明确边界有助于玩家判断什么时候需要调整操作或继续验证。", "Clear boundaries help a player decide when to change their actions or investigate further."), [
                {"type": "bullets", "items": [
                    t("没有小怪时，触发条件还能否建立？", "Can the required condition start without adds?"),
                    t("长时间移动或中断之后，怎样恢复战斗循环？", "How does the combat loop resume after movement or interruption?"),
                    t("哪些结论来自来源事实，哪些仍是推断？", "Which conclusions are source facts, and which remain inferences?"),
                ]},
                {"type": "note", "kind": "check", "title": t("模型覆盖与实战表现分开看", "Keep model coverage in context"),
                 "text": t("本演示没有 PoB 测量。真实学习文档应说明数值对应的技能、状态和版本，并保留尚未验证的部分。", "This demo includes no PoB measurements. A real guide should identify the skill, state, and version behind its readings and preserve unresolved questions.")},
            ]),
        ],
        "teachingReview": dict(languageConsistent=True, readerJourneyReviewed=True, detailPreserved=True,
                               conditionsExplainedInContext=True, visualsExplainRelationships=True,
                               noAuditDump=True, summary=t("仅审读原创演示教学文本，不声明已完成 BD 验收。", "Review of original demonstration prose only; no BD acceptance claimed.")),
    })
    return build_html(guide, title=title, language=language, components={},
                      inline=InlineNames({}, {}, language))


if __name__ == "__main__":
    for language in ("en", "zh-CN"):
        path = Path(__file__).with_name(f"learning-guide-demo.{language}.html")
        path.write_text(demo(language), encoding="utf-8", newline="\n")
        print(path.relative_to(ROOT))
