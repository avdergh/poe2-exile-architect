"""Render only Agent-authored teaching prose; never dump internal analysis fields."""

from __future__ import annotations
import re

from .guide import LearningGuide
from .localization import TOKEN
from .language import localized_name


def resolve(value: str, components: dict, language: str) -> str:
    value = re.sub(r"\{\{term:([^{}]+)\}\}", lambda m: m[1], value)
    return TOKEN.sub(lambda m: localized_name(components[m[1]], language), value)


def markdown(guide: LearningGuide, *, title: str, language: str, components: dict, inline) -> str:
    def text(value):
        return inline.markdown(value)

    lines = ["# " + text(title), "", text(guide.subtitle), "", text(guide.introduction), ""]
    for unit in guide.units:
        lines.extend(["## " + text(unit.title), "", text(unit.introduction), ""])
        for block in unit.blocks:
            if block.type == "paragraph":
                lines.append(text(block.text))
            elif block.type == "heading":
                lines.append("### " + text(block.text))
            elif block.type == "bullets":
                lines.extend("- " + text(item) for item in block.items)
            elif block.type == "table":

                def row(values):
                    return (
                        "| "
                        + " | ".join(
                            text(x).replace("|", "\\|").replace("\n", "<br>") for x in values
                        )
                        + " |"
                    )

                lines.extend(
                    [row(block.columns), "| " + " | ".join("---" for _ in block.columns) + " |"]
                )
                lines.extend(row(values) for values in block.rows)
            elif block.type == "flow":
                lines.extend(["**" + text(block.title) + "**", ""])
                lines.extend(
                    f"{i}. **{text(step.label)}**：{text(step.explanation)}"
                    for i, step in enumerate(block.steps, 1)
                )
            elif block.type == "note":
                lines.extend(
                    [
                        "> **" + text(block.title) + "**",
                        ">",
                        "> " + text(block.text).replace("\n", "\n> "),
                    ]
                )
            lines.append("")
    return "\n".join(lines).strip() + "\n"
