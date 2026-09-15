"""One exact-name tokenizer shared by headings, prose, tables, diagrams and Markdown."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from xml.sax.saxutils import escape, quoteattr

from .language import localized_name
from .icons import IconCoverageError
from .storage import fingerprint

MENTION_TOKEN = re.compile(r"\{\{(?:(term:[^{}]+)|([a-z0-9-]+))\}\}")


def _typography(text):
    return text.replace("’", "'")


@dataclass
class Mention:
    text: str
    identity: str


class InlineNames:
    def __init__(
        self,
        catalog: dict,
        components: dict,
        language: str,
        assets: dict | None = None,
        *,
        skill_refs=(),
        component_refs=(),
    ):
        self.catalog, self.components, self.language = dict(catalog), components, language
        self.assets = assets or {}
        labels = {}
        if (set(skill_refs) | set(component_refs)) - set(catalog):
            raise IconCoverageError([{"reason": "unknown_skill_icon_identity"}])
        allowed = (
            {c["identity"] for c in components.values()} | set(skill_refs) | set(component_refs)
        )
        for c in components.values():
            allowed.update(c.get("augmentIconRefs", []))
        for identity, entry in catalog.items():
            if identity not in allowed:
                continue
            # Child labels can be generic words such as "Projectile". Only explicitly selected
            # effect identities authorize matching them in learner prose.
            if entry.get("kind") == "granted_skill" and identity not in skill_refs:
                continue
            labels.setdefault(_typography(entry["name"]), set()).add(identity)
        for component in components.values():
            identity = component["identity"]
            if identity in catalog:
                for name in {
                    component["name"]["en"],
                    localized_name(component, language),
                    *component.get("displayAliases", []),
                }:
                    labels.setdefault(_typography(name), set()).add(identity)
            elif component["kind"] not in {"skill", "support"}:
                # Protect full equipment/passive names from partial skill-name matches.
                for name in {component["name"]["en"], localized_name(component, language)}:
                    labels.setdefault(_typography(name), set()).add(None)
        # Same-named small nodes may share the exact same art. Preserve all node identities;
        # this is only a shared visual, never a new physical graph node or merged knowledge.
        for name, identities in labels.items():
            if len(identities) < 2 or None in identities:
                continue
            entries = [catalog[identity] for identity in sorted(identities)]
            if (
                len(
                    {
                        (
                            e.get("kind"),
                            e.get("iconPath"),
                            e.get("treeVersion"),
                            fingerprint(e.get("atlas")),
                        )
                        for e in entries
                    }
                )
                == 1
            ):
                shared = {
                    "identity": "visual-group:" + fingerprint(sorted(identities))[:24],
                    "name": entries[0]["name"],
                    "kind": entries[0]["kind"],
                    "iconPath": entries[0].get("iconPath"),
                    "memberIdentities": sorted(identities),
                    "sourceRefs": [e.get("sourceRef") for e in entries],
                    "scope": "shared_icon_only",
                    "atlas": entries[0].get("atlas"),
                }
                shared["bindingHash"] = fingerprint(shared)
                self.catalog[shared["identity"]] = shared
                labels[name] = {shared["identity"]}
        self.labels = labels
        terms = sorted(labels, key=lambda name: (-len(name), name))
        self.pattern = (
            re.compile(
                "|".join(
                    r"(?<![A-Za-z0-9_])" + re.escape(term) + r"(?![A-Za-z0-9_])" for term in terms
                )
            )
            if terms
            else None
        )

    def _literal(self, value):
        if not self.pattern:
            return [value]
        parts, pos = [], 0
        for match in self.pattern.finditer(_typography(value)):
            parts.append(value[pos : match.start()])
            identities = self.labels[match.group()]
            if len(identities) != 1:
                raise IconCoverageError(
                    [{"reason": "ambiguous_skill_icon", "name": value[match.start() : match.end()]}]
                )
            identity = next(iter(identities))
            parts.append(
                Mention(value[match.start() : match.end()], identity)
                if identity is not None
                else value[match.start() : match.end()]
            )
            pos = match.end()
        parts.append(value[pos:])
        return parts

    def split(self, value):
        parts, pos = [], 0
        for match in MENTION_TOKEN.finditer(value):
            parts.extend(self._literal(value[pos : match.start()]))
            if match[1]:
                parts.append(match[1][len("term:") :])
                pos = match.end()
                continue
            component = self.components[match[2]]
            label = localized_name(component, self.language)
            identity = component["identity"]
            if identity in self.catalog:
                parts.append(Mention(label, identity))
            elif component["kind"] in {"skill", "support"}:
                raise IconCoverageError([{"reason": "skill_identity_missing", "name": label}])
            else:
                parts.append(label)
            pos = match.end()
        parts.extend(self._literal(value[pos:]))
        return parts

    def plain(self, value):
        return "".join(
            part.text if isinstance(part, Mention) else part for part in self.split(value)
        )

    def required(self, guide, title):
        entries = {}
        for value in visible_text(guide, title):
            for part in self.split(value):
                if isinstance(part, Mention):
                    entries[part.identity] = self.catalog[part.identity]
        return entries

    def pdf(self, value, size=22):
        parts = []
        for part in self.split(value):
            if isinstance(part, str):
                parts.append(escape(part).replace("\n", "<br/>"))
                continue
            asset = self.assets.get(part.identity)
            if not asset:
                raise IconCoverageError([{"reason": "skill_icon_missing", "name": part.text}])
            # Attach the last word (or CJK character) to its icon while earlier words may wrap.
            tail = re.search(r"[A-Za-z0-9'’]+$|.$", part.text).start()
            dimension = max(asset.get("width", 1), asset.get("height", 1))
            width, height = (
                size * asset.get("width", 1) / dimension,
                size * asset.get("height", 1) / dimension,
            )
            parts.append(
                escape(part.text[:tail])
                + "<nobr>"
                + escape(part.text[tail:])
                + f'&#160;<img src={quoteattr(asset["path"])} width="{width:g}" height="{height:g}" valign="middle"/></nobr>'
            )
        return "".join(parts)

    def markdown(self, value):
        parts = []
        for part in self.split(value):
            if isinstance(part, str):
                parts.append(escape(part))
            else:
                asset = self.assets[part.identity]
                name = Path(asset["path"]).name
                parts.append(
                    escape(part.text)
                    + f' <img src="assets/{name}" width="32" height="32" alt={quoteattr(part.text + " icon")}/>'
                )
        return "".join(parts)


def visible_text(guide, title):
    yield title
    for field in ("subtitle", "introduction", "navigationTitle"):
        yield getattr(guide, field)
    yield from guide.componentNotes.values()
    for concept in guide.concepts:
        yield concept.explanation
    for unit in guide.units:
        yield unit.title
        yield unit.introduction
        for block in unit.blocks:
            if block.type in {"paragraph", "heading"}:
                yield block.text
            elif block.type == "bullets":
                yield from block.items
            elif block.type == "table":
                yield from block.columns
                for row in block.rows:
                    yield from row
            elif block.type == "flow":
                yield block.title
                for step in block.steps:
                    yield step.label
                    yield step.explanation
            elif block.type == "note":
                yield block.title
                yield block.text
