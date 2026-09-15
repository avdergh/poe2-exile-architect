"""Read exact generated PoB gem/effect data without evaluating Lua or build numbers.

The deliberately small literal reader rejects expressions. Skill implementation/statMap code
is never executed; only generated fields and literal stat-description tables are projected.
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET
from collections import Counter

from .. import paths
from .physical_graph import _pob_skill_blocks


class LiteralError(ValueError):
    pass


_TOKEN = re.compile(
    r'\s+|--[^\n]*|"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?'
    r"|[A-Za-z_]\w*|[{}\[\]=,;.]",
    re.S,
)


class _LiteralReader:
    def __init__(self, text: str):
        self.text, self.pos = text, 0

    def token(self) -> str:
        while self.pos < len(self.text):
            match = _TOKEN.match(self.text, self.pos)
            if not match:
                raise LiteralError("unsupported_literal")
            self.pos = match.end()
            token = match[0]
            if not token.isspace() and not token.startswith("--"):
                return token
        return ""

    def peek(self) -> str:
        pos = self.pos
        try:
            return self.token()
        finally:
            self.pos = pos

    def require(self, token: str) -> None:
        if self.token() != token:
            raise LiteralError("invalid_literal")

    def value(self, depth: int = 0) -> Any:
        if depth > 32:
            raise LiteralError("literal_depth_exceeded")
        token = self.token()
        if token == "{":
            result, next_index = {}, 1
            while self.peek() != "}":
                if not self.peek():
                    raise LiteralError("incomplete_literal")
                if self.peek() == "[":
                    self.token()
                    key = self.value(depth + 1)
                    self.require("]")
                    self.require("=")
                else:
                    pos = self.pos
                    candidate = self.token()
                    if re.fullmatch(r"[A-Za-z_]\w*", candidate) and self.peek() == "=":
                        key = candidate
                        self.token()
                    else:
                        self.pos, key = pos, next_index
                        next_index += 1
                if not isinstance(key, (str, int)) or isinstance(key, bool) or key in result:
                    raise LiteralError("duplicate_or_invalid_literal_key")
                result[key] = self.value(depth + 1)
                if self.peek() in (",", ";"):
                    self.token()
                elif self.peek() != "}":
                    raise LiteralError("literal_expression_not_supported")
            self.token()
            return result
        if token.startswith('"'):
            return json.loads(token)
        if re.fullmatch(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", token):
            return float(token) if any(c in token for c in ".eE") else int(token)
        if token in ("true", "false", "nil"):
            return {"true": True, "false": False, "nil": None}[token]
        if token == "SkillType":
            self.require(".")
            name = self.token()
            if re.fullmatch(r"[A-Za-z_]\w*", name):
                return name
        raise LiteralError("literal_expression_not_supported")


def _field(body: str, name: str, indent: int) -> tuple[Any, str]:
    prefix = "\t" * indent
    matches = list(re.finditer(rf"^{prefix}{re.escape(name)}\s*=", body, re.M))
    if not matches:
        return None, "source_field_missing"
    if len(matches) != 1:
        return None, "source_field_ambiguous"
    reader = _LiteralReader(body[matches[0].end() :])
    try:
        result = reader.value()
        # Fields are generated with an optional comma and then a newline/end.
        rest = reader.text[reader.pos :].split("\n", 1)[0].strip()
        if rest not in ("", ","):
            raise LiteralError("literal_expression_not_supported")
        return result, "available"
    except (ValueError, RecursionError):
        return None, "source_field_parse_failed"


def _file_key(path: Path) -> tuple[str, int, int, int, int]:
    stat = path.stat()
    return str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino


@lru_cache(maxsize=64)
def _source(key: tuple[str, int, int, int, int]) -> tuple[str, str]:
    raw = Path(key[0]).read_bytes()
    return raw.decode("utf-8"), "pob-static:sha256:" + hashlib.sha256(raw).hexdigest()


@lru_cache(maxsize=2)
def _index(
    keys: tuple[tuple[str, int, int, int, int], ...],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    gems: dict[str, list[tuple[list[Any], str, str]]] = {}
    effects: dict[str, list[tuple[str | None, str]]] = {}
    version = "unknown"
    for key in keys:
        text, source = _source(key)
        name = Path(key[0]).name
        if name == "manifest.xml":
            node = ET.fromstring(text).find("Version")
            version = node.get("number", "unknown") if node is not None else "unknown"
        elif name == "Gems.lua":
            blocks = list(
                re.finditer(
                    r'^\t\["([^"\r\n]+)"\] = \{\r?\n(.*?)(?=^\t\["|^\})',
                    text,
                    re.M | re.S,
                )
            )
            counts = Counter(m[1] for m in blocks)
            duplicates = {gem_id for gem_id, count in counts.items() if count > 1}
            for match in blocks:
                body = match[2]
                _alias, alias_status = _field(body, "gameId", 2)
                primary, status = _field(body, "grantedEffectId", 2)
                fields = re.findall(r"^\t\t(additionalGrantedEffectId\d+)\s*=", body, re.M)
                grant_ids = [primary]
                for field in fields:
                    value, child_status = _field(body, field, 2)
                    grant_ids.append(value)
                    if child_status != "available":
                        status = child_status
                if (
                    match[1] in duplicates
                    or alias_status not in ("available", "source_field_missing")
                    or not all(isinstance(x, str) and x for x in grant_ids)
                    or len(set(grant_ids)) != len(grant_ids)
                    or not re.search(r"^\t\},?[ \t\r\n]*\Z", body, re.M)
                ):
                    status = "source_field_ambiguous"
                # Preserve even invalid aliases; a valid sibling must not hide them.
                aliases = {match[1]}
                for declaration in re.findall(r"^\t\tgameId\s*=[^\n]*", body, re.M):
                    value, _ = _field(declaration, "gameId", 2)
                    if isinstance(value, str):
                        aliases.add(value)
                for gem_id in aliases:
                    gems.setdefault(gem_id, []).append((grant_ids, status, source))
        else:
            for effect_id, body in _pob_skill_blocks(text):
                effects.setdefault(effect_id, []).append((body, source))
    return gems, effects, version


@lru_cache(maxsize=32)
def _translations(key: tuple[str, int, int, int, int]) -> tuple[dict, str]:
    text, source = _source(key)
    reader = _LiteralReader(text)
    reader.require("return")
    value = reader.value()
    if not isinstance(value, dict) or reader.token():
        raise LiteralError("invalid_translation_source")
    return value, source


def _stat_text(
    data: Path, scope: str, stat_id: str, value: Any
) -> tuple[str, str, str | None, list]:
    if not re.fullmatch(r"[A-Za-z0-9_]+", scope):
        return "", "translation_scope_missing", None, []
    root = data / "StatDescriptions"
    candidates = [root / f"{scope}.lua", root / "Specific_Skill_Stat_Descriptions" / f"{scope}.lua"]
    existing = [p for p in candidates if p.is_file()]
    if len(existing) != 1:
        return "", "translation_source_missing_or_ambiguous", None, []
    try:
        table, source = _translations(_file_key(existing[0]))
    except (OSError, ValueError, RecursionError):
        return "", "translation_source_parse_failed", None, []
    entry_id = table.get(stat_id)
    entry = table.get(entry_id) if isinstance(entry_id, int) else None
    if not isinstance(entry, dict) or entry.get("stats") != {1: stat_id}:
        return "", "translation_requires_other_stats", source, []
    variants = entry.get(1)
    if not isinstance(variants, dict):
        return "", "translation_missing", source, []
    templates = [
        {
            "text": v.get("text"),
            "limits": v.get("limit"),
            "transforms": [x for k, x in v.items() if isinstance(k, int)],
        }
        for v in variants.values()
        if isinstance(v, dict)
    ]
    matches = []
    for variant in variants.values():
        if not isinstance(variant, dict) or set(variant) - {"limit", "text"}:
            continue  # Transform functions are not implemented or guessed.
        text = variant.get("text")
        limits_by_stat = variant.get("limit")
        if not isinstance(limits_by_stat, dict) or set(limits_by_stat) != {1}:
            continue
        limits = limits_by_stat[1]
        if not isinstance(text, str) or not isinstance(limits, dict) or set(limits) != {1, 2}:
            continue
        lo, hi = limits[1], limits[2]
        if value is None:
            if lo != "#" or hi != "#" or "{" in text:
                continue
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            if lo != "#" and (not isinstance(lo, (int, float)) or value < lo):
                continue
            if hi != "#" and (not isinstance(hi, (int, float)) or value > hi):
                continue
        else:
            continue
        if "{" in text:
            # Only the exact single numeric placeholder is supported. No expression engine.
            if value is None or re.sub(r"\{0\}", "", text).find("{") >= 0:
                continue
            text = text.replace("{0}", str(value))
        matches.append(text)
    if len(matches) != 1:
        return "", "translation_unresolved", source, templates
    return matches[0], "available", source, templates


def _stat_sets(body: str, data: Path, source: str) -> tuple[list[dict], list[str]]:
    matches = re.findall(r"^\tstatSets\s*=", body, re.M)
    if not matches:
        return [], ["stat_sets_missing"]
    if len(matches) != 1:
        return [], ["stat_sets_ambiguous"]
    # Keep statMap expressions out of the literal reader, using generated field indentation.
    region = re.search(r"^\tstatSets\s*=\s*\{\r?\n(.*?)^\t\},?\s*$", body, re.M | re.S)
    if not region:
        return [], ["stat_sets_parse_failed"]
    blocks = list(
        re.finditer(r"^\t\t\[(\d+)\]\s*=\s*\{\r?\n(.*?)^\t\t\},?\s*$", region[1], re.M | re.S)
    )
    declared = re.findall(r"^\t\t\[(\d+)\]\s*=", region[1], re.M)
    if (
        not blocks
        or len({m[1] for m in blocks}) != len(blocks)
        or declared != [m[1] for m in blocks]
    ):
        return [], ["stat_sets_parse_failed"]
    output, issues = [], []
    for block in blocks:
        section = block[2]
        label, _ = _field(section, "label", 3)
        scope, _ = _field(section, "statDescriptionScope", 3)
        row = {"statSetIndex": int(block[1]), "label": label, "sourceRef": source, "stats": []}
        for field in ("constantStats", "stats"):
            values, status = _field(section, field, 3)
            if status == "source_field_missing":
                continue
            if status != "available" or not isinstance(values, dict):
                issues.append(f"{field}_parse_failed")
                continue
            for index, raw in values.items():
                stat_id, value = (raw.get(1), raw.get(2)) if isinstance(raw, dict) else (raw, None)
                if (
                    not isinstance(index, int)
                    or not isinstance(stat_id, str)
                    or (
                        field == "constantStats"
                        and (
                            not isinstance(raw, dict)
                            or set(raw) != {1, 2}
                            or not isinstance(value, (int, float))
                            or isinstance(value, bool)
                        )
                    )
                ):
                    issues.append(f"{field}_parse_failed")
                    continue
                text, text_status, text_source, templates = _stat_text(
                    data, scope if isinstance(scope, str) else "", stat_id, value
                )
                row["stats"].append(
                    {
                        "statId": stat_id,
                        "value": value,
                        "valueKind": "constant"
                        if field == "constantStats"
                        else "per_level_or_flag",
                        "valueStatus": "explicit" if value is not None else "not_explicit",
                        "text": text,
                        "textStatus": text_status,
                        "textSourceRef": text_source,
                        "textTemplates": templates,
                    }
                )
                if text_status != "available":
                    issues.append(text_status)
        output.append(row)
    return output, sorted(set(issues))


def get_details(gem_id: str, grants: list[str]) -> dict[str, Any]:
    """Project all explicitly bound effects, keeping missing source and ambiguity distinct."""
    result: dict[str, Any] = {
        "schemaVersion": "pob_gem_effect_details_v1",
        "status": "unavailable",
        "source": "pinned_pob_static",
        "gemId": gem_id,
        "effects": [],
        "mechanismCompleteness": "not_certified",
        "scope": "explicit_gem_grants_and_literal_stat_sets",
        "limitations": [
            "Static source values are not character calculations or compatibility checks.",
            "Per-level values, statMap expressions and linked buffs without an explicit effect ID "
            "are not expanded; missing duration/recovery values remain unknown.",
        ],
    }
    if (
        not grants
        or any(not isinstance(x, str) or not x for x in grants)
        or len(set(grants)) != len(grants)
    ):
        return {**result, "reason": "corpus_granted_effects_missing_or_ambiguous"}
    pair = paths.pob_runtime_pair()
    data = pair.src_dir / "Data"
    files = [data / "Gems.lua", *sorted((data / "Skills").glob("*.lua"))]
    manifest = pair.src_dir.parent / "manifest.xml"
    if manifest.is_file():
        files.append(manifest)
    try:
        bindings, effects, version = _index(tuple(_file_key(p) for p in files))
    except FileNotFoundError:
        return {**result, "reason": "static_source_missing"}
    except OSError:
        return {**result, "reason": "static_source_read_failed"}
    except (ValueError, ET.ParseError):
        return {**result, "reason": "static_source_parse_failed"}
    matches = bindings.get(gem_id, [])
    if not matches:
        return {**result, "reason": "gem_binding_missing"}
    if len(matches) != 1:
        return {**result, "reason": "gem_binding_ambiguous"}
    effect_ids, binding_status, gem_source = matches[0]
    if binding_status != "available":
        return {**result, "reason": "gem_binding_parse_failed"}
    result.update(
        gemSourceRef=gem_source,
        pobVersion=version,
        runtimeSource=pair.source,
        grantedEffectIds=effect_ids,
    )
    if set(grants) != set(effect_ids):
        return {**result, "reason": "corpus_runtime_granted_effects_mismatch"}
    issues = []
    for effect_id in effect_ids:
        row: dict[str, Any] = {"effectId": effect_id, "status": "unavailable"}
        definitions = effects.get(effect_id, [])
        if len(definitions) != 1 or definitions[0][0] is None:
            reason = (
                "effect_missing"
                if not definitions
                else ("effect_ambiguous" if len(definitions) > 1 else "effect_parse_failed")
            )
            row["reason"] = reason
            issues.append(reason)
        else:
            body, source = definitions[0]
            name, _ = _field(body, "name", 1)
            description, description_status = _field(body, "description", 1)
            support, support_status = _field(body, "support", 1)
            stats, stat_issues = _stat_sets(body, data, source)
            issues.extend(stat_issues)
            row.update(
                name=name,
                sourceRef=source,
                isSupport=support,
                supportStatus=support_status,
                description=description if isinstance(description, str) else "",
                descriptionStatus=description_status,
                statSets=stats,
            )
            constraints = {}
            for field in ("requireSkillTypes", "excludeSkillTypes", "addSkillTypes"):
                values, status = _field(body, field, 1)
                constraints[field] = {
                    "status": status,
                    "values": list(values.values())
                    if status == "available" and isinstance(values, dict)
                    else [],
                }
            row["supportConstraints"] = constraints
            row["issues"] = stat_issues
            if not isinstance(description, str) or not description.strip():
                texts = [s["text"] for st in stats for s in st["stats"] if s["text"]]
                # Never replace an invalid declaration or a multi-stat-set explanation.
                if (
                    description_status == "source_field_missing"
                    and len(stats) == 1
                    and texts
                    and not stat_issues
                ):
                    row["description"] = "\n".join(texts)
                    row["descriptionOrigin"] = "stat_text_projection"
                else:
                    issues.append(
                        "effect_description_missing"
                        if description_status == "source_field_missing"
                        else "effect_description_parse_failed"
                    )
            else:
                row["descriptionOrigin"] = "effect_description"
            row["status"] = "partial" if stat_issues or not row["description"] else "available"
        result["effects"].append(row)
    if not any(x.get("description") or x.get("statSets") for x in result["effects"]):
        result["status"] = "unavailable"
    else:
        result["status"] = (
            "partial"
            if issues or any(x["status"] != "available" for x in result["effects"])
            else "available"
        )
    result["issues"] = sorted(set(issues))
    if len(effect_ids) > 1:
        result["descriptionSelection"] = "multiple_granted_effects"
    return result
