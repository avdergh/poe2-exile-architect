"""Cheap, raw-free checks before a generation snapshot consumes a Judge attempt."""

from __future__ import annotations

from collections import Counter
from typing import Any
import xml.etree.ElementTree as ET

from server.compute import completeness


def inspect_generation_preflight(engine: Any) -> dict[str, Any]:
    try:
        xml = engine.get_xml()
    except Exception:  # noqa: BLE001 - public diagnostics must not expose engine internals.
        return _error("active_build_snapshot_failed")
    return inspect_generation_snapshot(engine, xml)


def inspect_generation_snapshot(engine: Any, xml: str) -> dict[str, Any]:
    """Inspect the exact XML that will be sent to the dedicated Judge engine."""
    parsed = _parse_skill_groups(xml)
    if parsed.get("errorCode"):
        return _error(str(parsed["errorCode"]))

    blocking: list[str] = []
    group_diagnostics: list[dict[str, Any]] = []
    signatures: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    for group in parsed["groups"]:
        issues: list[str] = []
        active_ids = list(group["activeIds"])
        support_ids = list(group["supportIds"])
        if len(active_ids) != 1:
            issues.append("invalid_socket_setup")
            blocking.append("invalid_socket_setup")
        if len(support_ids) != len(set(support_ids)):
            issues.append("duplicate_support_gem")
            blocking.append("duplicate_support_gem")
        signatures.append((tuple(sorted(active_ids)), tuple(sorted(support_ids))))
        group_diagnostics.append(
            {
                "groupIndex": group["groupIndex"],
                "role": group["role"],
                "activeSkills": group["activeNames"],
                "supports": group["supportNames"],
                "issues": issues,
            }
        )

    signature_counts = Counter(signatures)
    duplicate_indices = [
        group_diagnostics[index]["groupIndex"]
        for index, signature in enumerate(signatures)
        if signature_counts[signature] > 1
    ]
    if duplicate_indices:
        blocking.append("duplicate_enabled_skill_group")

    complete = completeness.inspect_build_completeness(engine, snapshot_xml=xml)
    blocking.extend(str(value) for value in complete.get("hardFailures") or [])
    advisories = [str(value) for value in complete.get("advisories") or []]
    blocking = _dedupe(blocking)
    return {
        "status": "blocked" if blocking else ("needs_attention" if advisories else "ready"),
        "readyForJudge": not blocking,
        "blockingIssues": blocking,
        "advisories": advisories,
        "duplicateGroupIndices": duplicate_indices,
        "skillGroups": group_diagnostics,
        "completeness": {
            "status": complete.get("status"),
            "hardFailures": complete.get("hardFailures") or [],
            "advisories": advisories,
        },
        "noRawMaterial": True,
    }


def _parse_skill_groups(xml: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(xml)
    except (ET.ParseError, TypeError, ValueError):
        return {"errorCode": "active_build_snapshot_invalid"}
    build = root.find("Build")
    skills = root.find("Skills")
    if build is None or skills is None:
        return {"errorCode": "active_build_snapshot_invalid"}
    main_group = str(build.get("mainSocketGroup") or "1")
    active_set_id = str(skills.get("activeSkillSet") or "1")
    skill_set = next(
        (node for node in skills.findall("SkillSet") if str(node.get("id")) == active_set_id),
        None,
    )
    if skill_set is None:
        return {"errorCode": "missing_active_skill_group"}

    groups: list[dict[str, Any]] = []
    for index, group in enumerate(skill_set.findall("Skill"), start=1):
        if not _xml_bool(group.get("enabled"), default=True):
            continue
        gems = [gem for gem in group.findall("Gem") if _xml_bool(gem.get("enabled"), default=True)]
        active = [gem for gem in gems if not _is_support(gem)]
        supports = [gem for gem in gems if _is_support(gem)]
        if not active:
            continue
        groups.append(
            {
                "groupIndex": index,
                "role": "pob_main_group" if str(index) == main_group else "additional_skill_group",
                "activeIds": [_gem_identity(gem) for gem in active],
                "activeNames": [_gem_name(gem) for gem in active],
                "supportIds": [_gem_identity(gem) for gem in supports],
                "supportNames": [_gem_name(gem) for gem in supports],
            }
        )
    if not groups or not any(group["role"] == "pob_main_group" for group in groups):
        return {"errorCode": "missing_active_skill_group"}
    return {"groups": groups}


def _gem_identity(gem: ET.Element) -> str:
    return str(gem.get("gemId") or gem.get("skillId") or gem.get("nameSpec") or "unknown-gem")


def _gem_name(gem: ET.Element) -> str:
    return str(gem.get("nameSpec") or gem.get("skillId") or gem.get("gemId") or "unknown")


def _is_support(gem: ET.Element) -> bool:
    gem_id = str(gem.get("gemId") or "")
    skill_id = str(gem.get("skillId") or "")
    return "SupportGem" in gem_id or skill_id.startswith("Support")


def _xml_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.casefold() in {"1", "true"}


def _dedupe(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        if value not in output:
            output.append(value)
    return output


def _error(error_code: str) -> dict[str, Any]:
    return {
        "status": "error",
        "readyForJudge": False,
        "blockingIssues": [error_code],
        "advisories": [],
        "skillGroups": [],
        "noRawMaterial": True,
    }
