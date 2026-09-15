"""One self-contained H5 learning reader with exact entity icons and explanations."""

from __future__ import annotations

import base64
from html import escape
import json
from pathlib import Path
import re
import secrets

from .inline_names import Mention
from .storage import fingerprint


def build_html(guide, *, title, language, components, inline):
    template_dir = Path(__file__).with_name("templates")
    css = (template_dir / "reader.css").read_text("utf-8")
    js = (template_dir / "reader.js").read_text("utf-8")
    nonce = secrets.token_hex(16)
    labels = guide.reader.kindLabels
    data, symbols = {}, {}
    first_sections = {}
    concepts = {c.term: c for c in guide.concepts}
    pattern = (
        re.compile(
            "|".join(
                r"(?<![A-Za-z0-9_])" + re.escape(t) + r"(?![A-Za-z0-9_])"
                for t in sorted(concepts, key=len, reverse=True)
            )
        )
        if concepts
        else None
    )

    def key(identity):
        return "e-" + fingerprint(identity)[:24]

    def icon(identity):
        asset = inline.assets[identity]
        symbol = "i-" + asset["sha256"][:24]
        if symbol not in symbols:
            encoded = base64.b64encode(Path(asset["path"]).read_bytes()).decode("ascii")
            symbols[symbol] = (
                f'<symbol id="{symbol}" viewBox="0 0 100 100"><image width="100" height="100" preserveAspectRatio="xMidYMid meet" href="data:image/png;base64,{encoded}"/></symbol>'
            )
        return symbol

    for identity, asset in inline.assets.items():
        category = asset.get("kind", "gear")
        category_label = labels.get(
            category + ":" + str(asset.get("itemClass", "")), labels.get(category, labels["gear"])
        )
        data[key(identity)] = {
            "name": asset["name"],
            "category": category_label,
            "icon": icon(identity),
            "caption": labels["item_base"] if asset.get("iconKind") == "item_base" else "",
            "description": "",
        }
    for concept in guide.concepts:
        data[key("concept:" + concept.term)] = {
            "name": concept.term,
            "category": concept.category or labels["concept"],
            "icon": None,
            "caption": "",
            "description": "",
        }

    def concept_text(value):
        if not pattern:
            return escape(value)
        output, pos = [], 0
        for match in pattern.finditer(value):
            output.append(escape(value[pos : match.start()]))
            output.append(
                f'<button type="button" class="concept" data-entity="{key("concept:" + match[0])}">{escape(match[0])}</button>'
            )
            pos = match.end()
        output.append(escape(value[pos:]))
        return "".join(output)

    def text(value, section=None, interactive=True):
        output = []
        for part in inline.split(value):
            if isinstance(part, Mention):
                entity_key = key(part.identity)
                if section:
                    first_sections.setdefault(entity_key, section)
                symbol = data[entity_key]["icon"]
                category = data[entity_key]["category"]
                content = f'<span class="entity-label">{escape(part.text)}</span><svg class="entity-icon" viewBox="0 0 100 100" aria-hidden="true"><use href="#{symbol}"/></svg>'
                output.append(
                    f'<button type="button" class="entity" data-entity="{entity_key}" title="{escape(category, quote=True)}">{content}</button>'
                    if interactive
                    else f'<span class="entity">{content}</span>'
                )
            else:
                output.append(concept_text(part).replace("\n", "<br>"))
        return "".join(output)

    body, toc = [], []
    for index, unit in enumerate(guide.units, 1):
        section = f"section-{index}"
        toc.append(
            f'<a href="#{section}" data-section="{section}"><span>{index:02d}</span><span>{text(unit.title, interactive=False)}</span></a>'
        )
        blocks = [
            f'<div class="section-heading"><span class="section-number">{index:02d}</span><h2>{text(unit.title, section)}</h2></div>',
            f'<p class="section-intro">{text(unit.introduction, section)}</p>',
        ]
        for block in unit.blocks:
            if block.type == "paragraph":
                blocks.append(f"<p>{text(block.text, section)}</p>")
            elif block.type == "heading":
                blocks.append(f"<h3>{text(block.text, section)}</h3>")
            elif block.type == "bullets":
                blocks.append(
                    "<ul>" + "".join(f"<li>{text(v, section)}</li>" for v in block.items) + "</ul>"
                )
            elif block.type == "table":
                header = "".join(f'<th scope="col">{text(v, section)}</th>' for v in block.columns)
                rows = "".join(
                    "<tr>" + "".join(f"<td>{text(v, section)}</td>" for v in row) + "</tr>"
                    for row in block.rows
                )
                blocks.append(
                    f'<div class="table-wrap cols-{len(block.columns)}"><table><thead><tr>{header}</tr></thead><tbody>{rows}</tbody></table></div>'
                )
            elif block.type == "flow":
                steps = "".join(
                    f'<li><span class="step-index">{i:02d}</span><h4>{text(step.label, section)}</h4><p>{text(step.explanation, section)}</p></li>'
                    for i, step in enumerate(block.steps, 1)
                )
                blocks.append(
                    f'<figure class="mechanism"><figcaption>{text(block.title, section)}</figcaption><ol class="flow steps-{len(block.steps)}">{steps}</ol></figure>'
                )
            elif block.type == "note":
                blocks.append(
                    f'<aside class="teaching-note {block.kind}"><h4>{text(block.title, section)}</h4><p>{text(block.text, section)}</p></aside>'
                )
        body.append(
            f'<section id="{section}" class="learning-section">' + "".join(blocks) + "</section>"
        )
    for identity, description in guide.componentNotes.items():
        entity_identity = components.get(identity, {}).get("identity", identity)
        if key(entity_identity) in data:
            data[key(entity_identity)]["description"] = text(description)
    for concept in guide.concepts:
        data[key("concept:" + concept.term)]["description"] = text(concept.explanation)
    for entity_key, section in first_sections.items():
        data[entity_key]["section"] = section
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
    reader = guide.reader
    csp = f"default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'nonce-{nonce}'; font-src 'self'; base-uri 'none'; form-action 'none'; connect-src 'none'"
    return f'''<!doctype html>
<html lang="{escape(language, quote=True)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="{escape(csp, quote=True)}"><title>{escape(inline.plain(title))}</title><style>{css}</style></head>
<body><svg class="icon-library" aria-hidden="true"><defs>{"".join(symbols.values())}</defs></svg>
<header class="reader-bar"><a class="reader-title" href="#top">{text(title, interactive=False)}</a><div class="search"><input id="guide-search" type="search" aria-label="{escape(reader.searchPlaceholder, quote=True)}" placeholder="{escape(reader.searchPlaceholder, quote=True)}"><button type="button" id="clear-search">{escape(reader.clearSearch)}</button></div></header>
<div class="layout"><aside class="sidebar"><details open><summary>{escape(guide.navigationTitle)}</summary><nav aria-label="{escape(guide.navigationTitle, quote=True)}">{"".join(toc)}</nav></details></aside>
<main id="top"><header class="guide-cover"><p class="subtitle">{text(guide.subtitle)}</p><h1>{text(title)}</h1><p class="lead">{text(guide.introduction)}</p><p class="reader-help">{escape(reader.helpText)}</p></header>
<div id="no-results" role="status" hidden><p>{escape(reader.noResults)}</p><button type="button" id="show-all">{escape(reader.showAll)}</button></div>{"".join(body)}</main></div>
<dialog id="entity-dialog" aria-labelledby="entity-name"><button type="button" id="close-dialog" class="close-dialog" aria-label="{escape(reader.closeDetails, quote=True)}">×</button><p class="detail-label">{escape(reader.componentDetails)}</p><div class="entity-detail-heading"><svg id="detail-icon" viewBox="0 0 100 100" aria-hidden="true"><use/></svg><div><span id="entity-kind"></span><h2 id="entity-name"></h2></div></div><p id="entity-caption"></p><div id="entity-description"></div><a id="entity-jump">{escape(reader.jumpToExplanation)}</a></dialog>
<script type="application/json" nonce="{nonce}" id="entity-data">{payload}</script><script nonce="{nonce}">{js}</script></body></html>'''
