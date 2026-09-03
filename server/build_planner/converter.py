"""Isolated adapter for a pinned PoB-to-Build-Planner provider."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any
from uuid import uuid4

from server import paths
from server.compute import completeness
from server.runtime.node import resolve_node_executable


PROVIDER_ID = "praedythxiv-poe2-build-converter"
PROVIDER_COMMIT = "27f5dad0d0979aa23a604defd11fcf7ae4668444"
PROVIDER_VERSION = "0.3.0"
MINIMUM_NODE_MAJOR = 20
NODE_PROBE_TIMEOUT_SECONDS = 15
_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")
_GEM_RE = re.compile(r"^Metadata/Items/Gems?/")
_SOCKET_GUIDANCE_RE = re.compile(
    r"^\s*(?:<gold>\{)?Sockets:\s*(\d+)\}?\s*$",
    re.IGNORECASE,
)
_INVENTORY_IDS = {
    "Weapon1",
    "Offhand1",
    "Weapon2",
    "Offhand2",
    "Helm1",
    "BodyArmour1",
    "Gloves1",
    "Boots1",
    "Amulet1",
    "Ring1",
    "Ring2",
    "Belt1",
    "Flask1",
}
_SLOT_MAP = {
    "Weapon 1": ("Weapon1", 0),
    "Weapon 2": ("Offhand1", 0),
    "Weapon 1 Swap": ("Weapon2", 0),
    "Weapon 2 Swap": ("Offhand2", 0),
    "Helmet": ("Helm1", 0),
    "Body Armour": ("BodyArmour1", 0),
    "Gloves": ("Gloves1", 0),
    "Boots": ("Boots1", 0),
    "Amulet": ("Amulet1", 0),
    "Ring 1": ("Ring1", 0),
    "Ring 2": ("Ring2", 0),
    "Belt": ("Belt1", 0),
    "Flask 1": ("Flask1", 0),
    "Flask 2": ("Flask1", 1),
    "Charm 1": ("Flask1", 2),
    "Charm 2": ("Flask1", 3),
    "Charm 3": ("Flask1", 4),
}


def provider_dir() -> Path:
    override = os.environ.get("POE_BD_BUILD_CONVERTER_DIR")
    if override:
        return Path(override).resolve()
    installed = paths.user_data_dir() / "providers" / "poe2-build-converter"
    if (installed / "provider.json").is_file():
        return installed.resolve()
    return (paths.BUNDLE_ROOT / "providers" / "poe2-build-converter").resolve()


def converter_status() -> dict[str, Any]:
    root = provider_dir()
    marker = _read_json(root / "provider.json")
    issues: list[str] = []
    if marker is None:
        issues.append("provider_marker_missing")
    else:
        if marker.get("providerId") != PROVIDER_ID:
            issues.append("provider_identity_mismatch")
        if marker.get("providerVersion") != PROVIDER_VERSION:
            issues.append("provider_version_mismatch")
        if marker.get("providerCommit") != PROVIDER_COMMIT:
            issues.append("provider_commit_mismatch")
    runner_rel = marker.get("runnerPath") if marker else None
    runner = root / runner_rel if isinstance(runner_rel, str) else root / "dist" / "runner.cjs"
    if not runner.is_file():
        issues.append("provider_runner_missing")
    license_path = root / str(marker.get("licensePath", "")) if marker else root / "missing"
    if not license_path.is_file():
        issues.append("provider_license_missing")
    node, node_version = _node_runtime()
    if node is None:
        issues.append("node_runtime_missing")
    elif node_version is None or node_version[0] < MINIMUM_NODE_MAJOR:
        issues.append("node_runtime_unsupported")
    return {
        "status": "ready" if not issues else "unavailable",
        "provider": _safe_provider(marker),
        "providerDirectory": str(root),
        "runnerReady": runner.is_file(),
        "licenseReady": license_path.is_file(),
        "nodeVersion": ".".join(map(str, node_version)) if node_version else None,
        "issues": issues,
        "installCommand": (
            ".\\.tools\\uv\\uv.exe run python scripts/install_build_converter_provider.py"
        ),
    }


def convert_pob_xml(
    xml: str,
    *,
    source_hash: str,
    metadata: dict[str, str] | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    status = converter_status()
    if status["status"] != "ready":
        return {**status, "status": "error", "errorCode": "converter_provider_unavailable"}
    root = provider_dir()
    marker = _read_json(root / "provider.json") or {}
    runner = root / str(marker["runnerPath"])
    node, _ = _node_runtime()
    request_id = f"build-conversion:{uuid4()}"
    request = {
        "requestId": request_id,
        "sourceHash": source_hash,
        "pobXml": xml,
        "metadata": metadata or {},
        "singleStage": True,
    }
    try:
        completed = subprocess.run(
            [str(node), str(runner)],
            input=json.dumps(request, ensure_ascii=False) + "\n",
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            cwd=root,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _conversion_error("converter_timeout", marker)
    except (OSError, UnicodeError):
        return _conversion_error("converter_process_failed", marker)
    if completed.returncode != 0:
        return _conversion_error("converter_process_failed", marker)
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        return _conversion_error("converter_protocol_error", marker)
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError:
        return _conversion_error("converter_protocol_error", marker)
    if not isinstance(payload, dict):
        return _conversion_error("converter_protocol_error", marker)
    if payload.get("requestId") != request_id or payload.get("sourceHash") != source_hash:
        return _conversion_error("converter_response_mismatch", marker)
    if payload.get("status") != "ok":
        return _conversion_error(
            str(payload.get("errorCode") or "provider_conversion_failed"), marker
        )
    build = payload.get("build")
    warnings = payload.get("warnings")
    stats = payload.get("stats")
    if not isinstance(build, dict) or not isinstance(warnings, list) or not isinstance(stats, dict):
        return _conversion_error("converter_protocol_error", marker)
    _prepend_socket_guidance(xml, build)
    if not any(
        isinstance(warning, dict) and warning.get("code") == "build-planner-guidance-only"
        for warning in warnings
    ):
        warnings = [
            *warnings,
            {
                "level": "info",
                "code": "build-planner-guidance-only",
                "message": (
                    "Rare/Magic gear, equipment sockets, Rune/Soul Core choices, and passive-tree "
                    "jewels are shown as Build Planner guidance text; the exported PoB XML/import "
                    "code remains authoritative."
                ),
            },
        ]
    normalized_warnings = _normalize_warnings(warnings)
    if normalized_warnings is None:
        return _conversion_error("converter_protocol_error", marker)
    validation_errors = validate_single_stage_build(build)
    serialized_build = json.dumps(build, ensure_ascii=False, indent=4) + "\n"
    return {
        "status": "ok",
        "provider": _safe_provider(marker),
        "sourceHash": source_hash,
        "build": build,
        "serializedBuild": serialized_build,
        "warnings": normalized_warnings,
        "stats": stats,
        "schemaValidation": {
            "status": "passed" if not validation_errors else "failed",
            "errors": validation_errors,
        },
    }


def _prepend_socket_guidance(xml: str, build: dict[str, Any]) -> int:
    """Make source PoB socket counts visible without inventing unsupported `.build` fields."""

    gear = completeness.equipped_item_metadata(xml)
    inventory = build.get("inventory_slots")
    if not isinstance(inventory, list):
        return 0
    by_slot: dict[tuple[str, int], dict[str, Any]] = {}
    for entry in inventory:
        if not isinstance(entry, dict):
            continue
        inventory_id = entry.get("inventory_id")
        slot_x = entry.get("slot_x", 0)
        if slot_x is None:
            slot_x = 0
        if (
            isinstance(inventory_id, str)
            and isinstance(slot_x, int)
            and not isinstance(slot_x, bool)
            and slot_x >= 0
        ):
            by_slot[(inventory_id, slot_x)] = entry
    changed = 0
    for slot, item in gear.items():
        if not isinstance(item, dict) or int(item.get("runeSockets") or 0) <= 0:
            continue
        target = _SLOT_MAP.get(str(slot))
        entry = by_slot.get(target) if target is not None else None
        if entry is None:
            continue
        existing = str(entry.get("additional_text") or "")
        count = int(item.get("runeSockets") or 0)
        desired = f"<gold>{{Sockets: {count}}}"
        lines = existing.splitlines()
        if lines and lines[0].strip() == desired:
            continue
        remaining = [line for line in lines if _SOCKET_GUIDANCE_RE.fullmatch(line) is None]
        remaining_text = "\n".join(remaining)
        entry["additional_text"] = desired + (f"\n{remaining_text}" if remaining_text else "")
        changed += 1
    return changed


def validate_single_stage_build(build: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed_root = {
        "name",
        "author",
        "link",
        "description",
        "ascendancy",
        "passives",
        "skills",
        "inventory_slots",
    }
    if set(build) - allowed_root:
        errors.append("unsupported_root_field")
    if not isinstance(build.get("name"), str) or not build["name"].strip():
        errors.append("missing_name")
    if _contains_key(build, "level_interval"):
        errors.append("single_stage_level_interval_present")
    passives = build.get("passives", [])
    if not isinstance(passives, list):
        errors.append("invalid_passives_shape")
        passives = []
    for passive in passives:
        passive_id = (
            passive
            if isinstance(passive, str)
            else passive.get("id")
            if isinstance(passive, dict)
            else None
        )
        if not isinstance(passive_id, str) or not _ID_RE.fullmatch(passive_id):
            errors.append("invalid_passive_id")
            break
    skills = build.get("skills", [])
    if not isinstance(skills, list):
        errors.append("invalid_skills_shape")
        skills = []
    for skill in skills:
        if isinstance(skill, str):
            skill_id, supports = skill, []
        elif isinstance(skill, dict):
            skill_id, supports = skill.get("id"), skill.get("support_skills", [])
        else:
            skill_id, supports = None, []
        if not isinstance(skill_id, str) or not _GEM_RE.match(skill_id):
            errors.append("invalid_skill_id")
            break
        for support in supports if isinstance(supports, list) else [None]:
            support_id = (
                support
                if isinstance(support, str)
                else support.get("id")
                if isinstance(support, dict)
                else None
            )
            if not isinstance(support_id, str) or not _GEM_RE.match(support_id):
                errors.append("invalid_support_id")
                break
    items = build.get("inventory_slots", [])
    if not isinstance(items, list):
        errors.append("invalid_inventory_shape")
        items = []
    for item in items:
        if not isinstance(item, dict) or item.get("inventory_id") not in _INVENTORY_IDS:
            errors.append("invalid_inventory_id")
            break
        for key in ("slot_x", "slot_y"):
            coordinate = item.get(key)
            if coordinate is not None and (
                not isinstance(coordinate, int)
                or isinstance(coordinate, bool)
                or coordinate < 0
            ):
                errors.append(f"invalid_inventory_{key}")
    return sorted(set(errors))


def _node_runtime() -> tuple[Path | None, tuple[int, int, int] | None]:
    executable = resolve_node_executable()
    if executable is None:
        return None, None
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=NODE_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    match = re.search(r"v?(\d+)\.(\d+)\.(\d+)", result.stdout)
    version = tuple(map(int, match.groups())) if result.returncode == 0 and match else None
    return executable, version


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _safe_provider(marker: dict[str, Any] | None) -> dict[str, Any]:
    marker = marker or {}
    return {
        "providerId": marker.get("providerId"),
        "providerVersion": marker.get("providerVersion"),
        "providerCommit": marker.get("providerCommit"),
        "license": marker.get("license"),
        "upstream": marker.get("upstream"),
        "officialFormat": marker.get("officialFormat"),
        "gameDataPatch": marker.get("gameDataPatch"),
    }


def _normalize_warnings(warnings: list[Any]) -> list[dict[str, str]] | None:
    normalized: list[dict[str, str]] = []
    for warning in warnings:
        if not isinstance(warning, dict):
            return None
        level, code, message = warning.get("level"), warning.get("code"), warning.get("message")
        if level not in {"info", "warn", "error"} or not all(
            isinstance(value, str) and value for value in (code, message)
        ):
            return None
        normalized.append({"level": level, "code": code, "message": message})
    return normalized


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(child, key) for child in value.values())
    if isinstance(value, list):
        return any(_contains_key(child, key) for child in value)
    return False


def _conversion_error(error_code: str, marker: dict[str, Any]) -> dict[str, Any]:
    return {"status": "error", "errorCode": error_code, "provider": _safe_provider(marker)}
