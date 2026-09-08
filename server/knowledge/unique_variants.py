"""Read static unique choices from the pinned PoB source, without calculating item stats."""

from __future__ import annotations

import re
from dataclasses import dataclass


_VARIANT = re.compile(r"\{variant:([\d,]+)\}")
_TAG = re.compile(r"\{(?:variant|tags|range|corruptedRange):[^}]*\}")
_LINK = re.compile(r"\[(?:[^\]|]*\|)?([^\]]+)\]")
_ALT_SUFFIXES = ("", " Two", " Three", " Four", " Five")


@dataclass(frozen=True)
class UniqueModifier:
    text: str
    variants: frozenset[int]
    kind: str


@dataclass(frozen=True)
class UniqueSource:
    labels: tuple[str, ...]
    alt_slots: tuple[str, ...]
    duplicates: bool
    selected: tuple[int, ...]
    modifiers: tuple[UniqueModifier, ...]

    @property
    def slots(self) -> int:
        return 1 + len(self.alt_slots)

    def project(self, selected: tuple[int, ...], *, include_implicit: bool = True) -> list[str]:
        """Mirror Item:CheckModLineVariant/GetModLineVariantCount over static lines."""
        result: list[str] = []
        for modifier in self.modifiers:
            if modifier.kind == "implicit" and not include_implicit:
                continue
            count = (
                sum(value in modifier.variants for value in selected) if modifier.variants else 1
            )
            if not self.duplicates:
                count = min(count, 1)
            result.extend([modifier.text] * count)
        return result

    def public_contract(self) -> dict:
        return {
            "requiredSelections": self.slots,
            "allowDuplicateVariants": self.duplicates,
            "options": [{"id": index, "name": label} for index, label in enumerate(self.labels, 1)],
            "modifierTemplates": [
                {
                    "text": modifier.text,
                    "kind": modifier.kind,
                    "variantIds": sorted(modifier.variants),
                }
                for modifier in self.modifiers
            ],
            "note": "Select the required number of complete variants. Untagged modifiers are "
            "mandatory; an effect shared by selected variants applies once unless duplicates "
            "are allowed. The flattened readable text is not an equip-ready combination.",
        }


def parse_unique_source(raw: str, *, name: str, base: str) -> UniqueSource:
    lines = [line.strip() for line in raw.splitlines()]
    metadata = {
        line.split(":", 1)[0]: line.split(":", 1)[1].strip()
        for line in lines
        if ":" in line and not line.startswith("{")
    }
    labels = tuple(line[len("Variant:") :].strip() for line in lines if line.startswith("Variant:"))
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
    implicit_remaining = 0
    for line in lines:
        if not line or line in {name, base} or set(line) == {"-"}:
            continue
        if line.startswith("Implicits:"):
            implicit_remaining = int(line.split(":", 1)[1].strip())
            continue
        variant = _VARIANT.search(line)
        variants = (
            frozenset(int(value) for value in variant[1].split(",")) if variant else frozenset()
        )
        value = _LINK.sub(r"\1", _TAG.sub("", line)).strip()
        kind = "implicit" if implicit_remaining else "explicit"
        # Metadata does not consume PoB's implicit-line counter.
        if ":" in value and not value.startswith("{") and not value.startswith("Grants Skill:"):
            continue
        if value.casefold().startswith("requires level ") or value.casefold() == "corrupted":
            continue
        if implicit_remaining:
            implicit_remaining -= 1
        if value:
            modifiers.append(UniqueModifier(value, variants, kind))
    return UniqueSource(
        labels,
        alt_slots,
        metadata.get("Allow Duplicate Variants") == "true",
        selected,
        tuple(modifiers),
    )
