"""Pinned PoB base implicits; never infer item-granted levels from character requirements."""

from __future__ import annotations

from functools import lru_cache
import re
from typing import Any

from server import paths
from . import pob_gem_details

_BLOCK = re.compile(r'^itemBases\["([^"\r\n]+)"\] = \{\r?\n(.*?)^\}', re.M | re.S)
_GRANT = re.compile(r'^Grants Skill: (?:Level (\d+|\(\d+-\d+\)) )?(.+)$')
_VARIANT = re.compile(r'^\{variant:([\d,]+)\}')
_RANGE = re.compile(r'\((-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)\)')


class ItemBaseSourceError(ValueError):
    """A missing static source/selection must be actionable, not an optimizer failure."""


@lru_cache(maxsize=4)
def _catalog(keys: tuple) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for key in keys:
        text, source = pob_gem_details._source(key)
        for match in _BLOCK.finditer(text):
            implicit, status = pob_gem_details._field(match[2], 'implicit', 1)
            variants, variant_status = pob_gem_details._field(match[2], 'variantList', 1)
            if match[1] in result:
                result[match[1]] = {'status': 'ambiguous'}
                continue
            result[match[1]] = {
                'status': ('available' if status in {'available', 'source_field_missing'}
                           and variant_status in {'available', 'source_field_missing'}
                           else 'source_field_parse_failed'),
                'lines': str(implicit or '').splitlines(),
                'variants': list(variants.values()) if isinstance(variants, dict) else [],
                'variantStatus': variant_status,
                'sourceRef': source,
            }
    return result


def base_source(base: str) -> dict[str, Any]:
    files = sorted((paths.pob_src_dir() / 'Data' / 'Bases').glob('*.lua'))
    try:
        return dict(_catalog(tuple(pob_gem_details._file_key(p) for p in files)).get(base) or {})
    except (OSError, ValueError):
        return {'status': 'unavailable'}


def _active_lines(raw: str) -> list[str]:
    selected = re.search(r'^Selected Variant:\s*(\d+)\s*$', raw, re.M)
    # PoB defaults a declared variant list to its last entry.
    selection = int(selected[1]) if selected else len(re.findall(r'^Variant:', raw, re.M)) or None
    result = []
    for line in raw.splitlines():
        line = line.strip()
        marker = _VARIANT.match(line)
        if marker:
            if selection not in {int(v) for v in marker[1].split(',')}:
                continue
            line = line[marker.end():]
        result.append(line)
    return result


def _matches_grant(declaration: str, actual: str) -> bool:
    expected, observed = _GRANT.fullmatch(declaration), _GRANT.fullmatch(actual)
    if not expected or not observed or expected[2] != observed[2]:
        return False
    if expected[1] is None:
        return observed[1] is None
    if not observed[1] or not observed[1].isdigit():
        return False
    if expected[1].isdigit():
        return observed[1] == expected[1]
    low, high = (int(v) for v in expected[1][1:-1].split('-'))
    return low <= int(observed[1]) <= high


def _selected_declarations(source: dict, reference_raw: str, variant: str | int | None) -> list[str]:
    variants = source.get('variants') or []
    if variants and variant is None:
        active = _active_lines(reference_raw)
        choices = set()
        for line in source['lines']:
            marker = _VARIANT.match(line)
            if marker and any(_matches_grant(line[marker.end():], row) for row in active):
                choices.update(int(v) for v in marker[1].split(','))
        if len(choices) != 1:
            raise ItemBaseSourceError('item_base_variant_required')
        variant = choices.pop()
    if variants:
        if isinstance(variant, str) and variant in variants:
            variant = variants.index(variant) + 1
        if type(variant) is not int or not 1 <= variant <= len(variants):
            raise ItemBaseSourceError('item_base_variant_invalid')
    lines = []
    for line in source.get('lines') or []:
        marker = _VARIANT.match(line)
        if marker:
            if variant not in {int(v) for v in marker[1].split(',')}:
                continue
            line = line[marker.end():]
        lines.append(line)
    return list(dict.fromkeys(lines))


def implicit_lines(
    base: str, *, item_level: int | None, reference_raw: str | None = None,
    variant: str | int | None = None, charm_slots: int | None = None,
) -> list[str]:
    source = base_source(base)
    if source.get('status') != 'available':
        raise ItemBaseSourceError('item_base_implicit_source_unavailable')
    reference = reference_raw or ''
    if reference and base not in [line.strip() for line in reference.splitlines()[:8]]:
        raise ItemBaseSourceError('item_base_reference_mismatch')
    prior = _active_lines(reference)
    lines = _selected_declarations(source, reference, variant)
    result = []
    for line in lines:
        grant = _GRANT.fullmatch(line)
        if grant and grant[1] and grant[1].startswith('('):
            matches = list(dict.fromkeys(row for row in prior if _matches_grant(line, row)))
            if len(matches) != 1:
                # The native range is not an ilvl -> skill-level acquisition rule.
                raise ItemBaseSourceError('item_base_grant_level_required')
            line = matches[0]
        elif re.fullmatch(r'Has \(1-3\) Charm Slots?', line) and charm_slots is not None:
            line = f'Has {charm_slots} Charm ' + ('Slot' if charm_slots == 1 else 'Slots')
        else:
            def roll(match):
                low, high = float(match[1]), float(match[2])
                digits = max(len(value.partition('.')[2]) for value in match.groups())
                value = round(low + .85 * (high - low), digits)
                return str(int(value)) if value.is_integer() else f'{value:g}'
            line = _RANGE.sub(roll, line)
        result.append(line)
    return list(dict.fromkeys(result))


def audit_required_grants(base: str, raw: str, *, rarity: str) -> dict[str, Any]:
    """Check known mandatory ordinary-base grants; unique alternatives have their own authority."""
    if rarity.casefold() == 'unique':
        return {'status': 'unique_source_audit', 'issues': []}
    actual = [line for line in _active_lines(raw) if _GRANT.fullmatch(line)]
    source = base_source(base)
    if source.get('status') != 'available':
        return {'status': 'unknown', 'issues': [], 'additionalGrants': actual}
    declared = [line for line in source.get('lines', []) if 'Grants Skill:' in line]
    if not declared:
        return {'status': 'not_applicable', 'issues': [], 'additionalGrants': actual}
    try:
        expected = [line for line in _selected_declarations(source, raw, None) if _GRANT.fullmatch(line)]
    except ValueError as exc:
        return {'status': 'missing', 'issues': [str(exc)], 'sourceRef': source['sourceRef']}
    missing = [line for line in expected if not any(_matches_grant(line, row) for row in actual)]
    duplicated = [line for line in expected if sum(_matches_grant(line, row) for row in actual) > 1]
    additional = [line for line in actual if not any(_matches_grant(row, line) for row in expected)]
    return {
        'status': 'missing' if missing else 'invalid' if duplicated else 'verified_base_requirement',
        'issues': (["item_base_skill_grant_missing_or_invalid"] if missing else [])
        + (["item_base_skill_grant_duplicated"] if duplicated else []),
        'missingGrants': missing,
        'additionalGrants': additional,
        'sourceRef': source['sourceRef'],
        'itemLevelRelation': 'unknown',
    }
