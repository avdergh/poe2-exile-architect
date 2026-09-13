"""Read static unique choices from the pinned PoB source, without calculating item stats."""

from __future__ import annotations

import re
from dataclasses import dataclass


_TAG = re.compile(r"\{(?:variant|version|group|tags|range|corruptedRange):[^}]*\}")
_LINK = re.compile(r"\[(?:[^\]|]*\|)?([^\]]+)\]")
_ALT_SUFFIXES = ("", " Two", " Three", " Four", " Five")
_SELECTION_SOURCE = re.compile(
    r"(?m)^\s*(?:Variant|Version|Selected Version|Selected Variant(?: Group)?):|\{(?:variant|version|group):"
)


def has_selection_syntax(raw: str) -> bool:
    return bool(_SELECTION_SOURCE.search(raw))


def _ids(line: str, tag: str) -> frozenset[int]:
    match = re.search(r"\{" + tag + r":([^}]*)\}", line)
    if not match:
        return frozenset()
    # Item.lua parseIdSpec reads positive group IDs and numeric version/variant IDs.
    values = frozenset(int(value) for value in re.findall(r"\d+", match[1]))
    if not values or any(value < 1 for value in values):
        raise ValueError("invalid unique selection IDs")
    return values


@dataclass(frozen=True)
class UniqueModifier:
    text: str
    variants: frozenset[int]
    kind: str
    versions: frozenset[int] = frozenset()
    groups: frozenset[int] = frozenset()


@dataclass(frozen=True)
class UniqueVariantGroup:
    id: int
    # (variant ID, eligible versions); version 0 means every version, as in Item.lua.
    options: tuple[tuple[int, frozenset[int]], ...]

    def eligible(self, version: int | None) -> tuple[int, ...]:
        return tuple(
            option for option, versions in self.options if 0 in versions or version in versions
        )


@dataclass(frozen=True)
class UniqueSource:
    labels: tuple[str, ...]
    alt_slots: tuple[str, ...]
    duplicates: bool
    selected: tuple[int, ...]
    modifiers: tuple[UniqueModifier, ...]
    intrinsic_corrupted: bool = False
    versions: tuple[str, ...] = ()
    selected_version: int | None = None
    groups: tuple[UniqueVariantGroup, ...] = ()
    selected_groups: tuple[tuple[int, int], ...] = ()
    selection_valid: bool = True
    properties: tuple[str, ...] = ()

    @property
    def uses_modern_selection(self) -> bool:
        return bool(self.versions or self.groups)

    @property
    def slots(self) -> int:
        if self.groups:
            return sum(bool(group.eligible(self.selected_version)) for group in self.groups)
        if self.uses_modern_selection:
            return int(bool(self.labels))
        return 1 + len(self.alt_slots)

    def project(
        self,
        selected: tuple[int, ...],
        *,
        include_implicit: bool = True,
        version: int | None = None,
        groups: dict[int, int] | None = None,
    ) -> list[str]:
        """Mirror Item:CheckModLineVariant/GetModLineVariantCount over static lines."""
        result: list[str] = []
        version = self.selected_version if version is None else version
        selections = dict(self.selected_groups) if groups is None else groups
        for modifier in self.modifiers:
            if modifier.kind == "implicit" and not include_implicit:
                continue
            if self.uses_modern_selection:
                if modifier.versions and version not in modifier.versions:
                    continue
                if modifier.groups:
                    count = int(
                        any(selections.get(group) in modifier.variants for group in modifier.groups)
                    )
                elif self.versions and self.labels and not self.groups and modifier.variants:
                    count = int(bool(selected) and selected[0] in modifier.variants)
                else:
                    count = int(not modifier.variants)
            else:
                count = (
                    sum(value in modifier.variants for value in selected)
                    if modifier.variants
                    else 1
                )
                if not self.duplicates:
                    count = min(count, 1)
            result.extend([modifier.text] * count)
        return result

    def readable_text(self, *, name: str, base: str) -> str:
        """Keep historical and alternative effects with their explicit static conditions."""
        lines = [name, base, *self.properties]
        for modifier in self.modifiers:
            conditions = []
            if modifier.versions:
                conditions.append(
                    "Version: "
                    + " / ".join(self.versions[value - 1] for value in sorted(modifier.versions))
                )
            if modifier.variants:
                label = (
                    "Variant group " + " or ".join(map(str, sorted(modifier.groups)))
                    if modifier.groups
                    else "Variant"
                )
                conditions.append(
                    label
                    + ": "
                    + " / ".join(self.labels[value - 1] for value in sorted(modifier.variants))
                )
            prefix = "[" + "; ".join(conditions) + "] " if conditions else ""
            lines.append(prefix + modifier.text)
        if self.intrinsic_corrupted:
            lines.append("Corrupted")
        return "\n".join(lines)

    def public_contract(self) -> dict:
        modifier_templates: list[dict[str, str | list[int]]] = [
            {
                "text": modifier.text,
                "kind": modifier.kind,
                "variantIds": sorted(modifier.variants),
            }
            for modifier in self.modifiers
        ]
        result = {
            "requiredSelections": self.slots,
            "allowDuplicateVariants": self.duplicates,
            "intrinsicCorrupted": self.intrinsic_corrupted,
            "options": [{"id": index, "name": label} for index, label in enumerate(self.labels, 1)],
            "modifierTemplates": modifier_templates,
            "note": "Select the required number of complete variants. Untagged modifiers are "
            "mandatory; an effect shared by selected variants applies once unless duplicates "
            "are allowed. The flattened readable text is not an equip-ready combination.",
        }
        if self.uses_modern_selection:
            result.update(
                {
                    "selectionModel": "version_group_v1",
                    "allowDuplicateVariants": False,
                    "versions": [
                        {"id": index, "name": label} for index, label in enumerate(self.versions, 1)
                    ],
                    "groups": [
                        {
                            "id": group.id,
                            "options": [
                                {
                                    "id": option,
                                    "name": self.labels[option - 1],
                                    "allVersions": 0 in versions,
                                    "versionIds": sorted(versions - {0}),
                                }
                                for option, versions in group.options
                            ],
                        }
                        for group in self.groups
                    ],
                    "defaultSelection": {
                        "versionId": self.selected_version,
                        "variantIds": list(self.selected) if not self.groups else [],
                        "groups": [
                            {"groupId": group, "variantId": variant}
                            for group, variant in self.selected_groups
                        ],
                    },
                    "note": "Select one version, and one eligible option per active group. Different groups "
                    "cannot reuse a variant. Without groups, variants are an independent single choice. "
                "Version and variant conditions apply together; multiple groups on a line are OR, "
                "and a shared effect applies only once. "
                    "Historical versions remain source facts, not current-version availability evidence. "
                    "Readable text retains all conditions and is not an equip-ready combination.",
                }
            )
            for template, modifier in zip(modifier_templates, self.modifiers, strict=True):
                template.update(
                    versionIds=sorted(modifier.versions), groupIds=sorted(modifier.groups)
                )
        return result


def parse_unique_source(raw: str, *, name: str, base: str) -> UniqueSource:
    lines = [line.strip() for line in raw.splitlines()]
    metadata = {
        line.split(":", 1)[0]: line.split(":", 1)[1].strip()
        for line in lines
        if ":" in line and not line.startswith("{")
    }
    labels = tuple(line[len("Variant:") :].strip() for line in lines if line.startswith("Variant:"))
    # Item.lua retains the old {tag}VariantName spelling as a label alias.
    labels = tuple(re.sub(r"^\{[\w_]+\}(.+)$", r"\1", label) for label in labels)
    versions = tuple(
        line[len("Version:") :].strip() for line in lines if line.startswith("Version:")
    )
    selected_version = (
        int(metadata.get("Selected Version", str(len(versions)))) if versions else None
    )
    alt_slots = tuple(suffix for suffix in _ALT_SUFFIXES if "Has Alt Variant" + suffix in metadata)
    selected = (
        tuple(
            int(metadata.get(key, str(len(labels))))
            for key in (
                "Selected Variant",
                *("Selected Alt Variant" + suffix for suffix in alt_slots),
            )
        )
        if labels
        else ()
    )
    modifiers: list[UniqueModifier] = []
    properties: list[str] = []
    implicit_remaining = 0
    for line in lines:
        if not line or line in {name, base} or set(line) == {"-"}:
            continue
        if line.startswith("Implicits:"):
            implicit_remaining = int(line.split(":", 1)[1].strip())
            continue
        variants, mod_versions, groups = (
            _ids(line, tag) for tag in ("variant", "version", "group")
        )
        if (
            (versions or groups)
            and any(value > len(labels) for value in variants)
            or any(value > len(versions) for value in mod_versions)
        ):
            raise ValueError("unique modifier references unknown selection")
        if groups and not variants:
            raise ValueError("grouped unique modifier has no variant")
        value = _LINK.sub(r"\1", _TAG.sub("", line)).strip()
        kind = "implicit" if implicit_remaining else "explicit"
        # Metadata does not consume PoB's implicit-line counter.
        if ":" in value and not value.startswith("{") and not value.startswith("Grants Skill:"):
            if not value.startswith(
                (
                    "Rarity:",
                    "Source:",
                    "Version:",
                    "Variant:",
                    "Selected ",
                    "Has Alt Variant",
                    "Allow Duplicate Variants:",
                )
            ):
                properties.append(value)
            continue
        if value.casefold().startswith("requires level ") or value.casefold() == "corrupted":
            if value.casefold().startswith("requires level "):
                properties.append(value)
            continue
        if implicit_remaining:
            implicit_remaining -= 1
        if value:
            modifiers.append(UniqueModifier(value, variants, kind, mod_versions, groups))
    group_options: dict[int, dict[int, set[int]]] = {}
    for modifier in modifiers:
        for group_id in modifier.groups:
            for variant in modifier.variants:
                group_options.setdefault(group_id, {}).setdefault(variant, set()).update(
                    modifier.versions or {0}
                )
    variant_groups = tuple(
        UniqueVariantGroup(
            group,
            tuple((variant, frozenset(eligible)) for variant, eligible in sorted(options.items())),
        )
        for group, options in sorted(group_options.items())
    )
    supplied_groups: dict[int, int] = {}
    for line in lines:
        if line.startswith("Selected Variant Group:"):
            match = re.fullmatch(r"Selected Variant Group:\s*(\d+)\s*=\s*(\d+)", line)
            if not match or int(match[1]) in supplied_groups:
                raise ValueError("invalid or repeated unique group selection")
            supplied_groups[int(match[1])] = int(match[2])
    valid = (
        selected_version in range(1, len(versions) + 1)
        if versions
        else "Selected Version" not in metadata
    )
    resolved_groups: dict[int, int] = {}
    if versions or variant_groups:
        selected = selected[:1] if not variant_groups else ()
        used: set[int] = set()
        # Preserve eligible explicit choices before filling missing groups, as Item.lua does.
        for group in variant_groups:
            if group.id in supplied_groups:
                choice = supplied_groups[group.id]
                if choice not in group.eligible(selected_version) or choice in used:
                    valid = False
                else:
                    resolved_groups[group.id] = choice
                    used.add(choice)
        valid = valid and not (supplied_groups.keys() - {group.id for group in variant_groups})
        for group in variant_groups:
            if group.id in resolved_groups or not group.eligible(selected_version):
                continue
            options = [value for value in group.eligible(selected_version) if value not in used]
            if not options:
                valid = False
                continue
            resolved_groups[group.id] = options[0]
            used.add(options[0])
        if not variant_groups and labels:
            valid = valid and len(selected) == 1 and 1 <= selected[0] <= len(labels)
    else:
        valid = not supplied_groups and "Selected Version" not in metadata
        valid = valid and all(1 <= value <= len(labels) for value in selected)
        valid = valid and (
            metadata.get("Allow Duplicate Variants") == "true"
            or len(set(selected)) == len(selected)
        )
    return UniqueSource(
        labels,
        alt_slots,
        metadata.get("Allow Duplicate Variants") == "true",
        selected,
        tuple(modifiers),
        # Item.lua recognizes this exact, untagged metadata line before mod parsing.
        intrinsic_corrupted="Corrupted" in lines,
        versions=versions,
        selected_version=selected_version,
        groups=variant_groups,
        selected_groups=tuple(sorted(resolved_groups.items())),
        selection_valid=bool(valid),
        properties=tuple(properties),
    )
