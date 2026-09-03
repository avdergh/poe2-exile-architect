"""Export verified final PoB artifacts to official single-stage `.build` JSON."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from server import paths
from server.generation import artifacts

from . import converter


_GUIDANCE_DISCLOSURE = (
    "Guidance only: Rare/Magic gear details, equipment sockets, Rune/Soul Core choices, and "
    "passive-tree jewels must be verified in the accompanying PoB XML/import code, which is the "
    "authoritative build."
)


def exports_dir() -> Path:
    override = os.environ.get("POE_BD_BUILD_EXPORTS_DIR")
    return (
        Path(override).resolve()
        if override
        else (paths.user_data_dir() / "build-planner-exports").resolve()
    )


def export_final_build_artifact(
    artifact_id: str,
    *,
    name: str = "",
    author: str = "",
    description: str = "",
    link: str = "",
    _destination_path: Path | None = None,
) -> dict[str, Any]:
    loaded = artifacts.read_final_build_artifact_for_export(artifact_id)
    if loaded is None:
        return {"status": "rejected", "errorCode": "final_artifact_not_found_or_corrupt"}
    manifest, xml = loaded
    disclosed_description = (
        f"{description.strip()}\n\n{_GUIDANCE_DISCLOSURE}"
        if isinstance(description, str) and description.strip()
        else _GUIDANCE_DISCLOSURE
    )
    metadata = {
        key: value.strip()
        for key, value in {
            "name": name,
            "author": author,
            "description": disclosed_description,
            "link": link,
        }.items()
        if isinstance(value, str) and value.strip()
    }
    converted = converter.convert_pob_xml(
        xml,
        source_hash=manifest.source_hash,
        metadata=metadata,
    )
    if converted.get("status") != "ok":
        return converted
    warnings = converted["warnings"]
    if any(warning["level"] == "error" for warning in warnings):
        return {
            "status": "rejected",
            "errorCode": "converter_error_warning",
            "provider": converted["provider"],
            "warnings": warnings,
        }
    validation = converted["schemaValidation"]
    if validation["status"] != "passed":
        return {
            "status": "rejected",
            "errorCode": "build_schema_validation_failed",
            "provider": converted["provider"],
            "schemaValidation": validation,
            "warnings": warnings,
        }
    build = converted["build"]
    if _destination_path is not None and _destination_path.suffix.casefold() != ".build":
        return {"status": "rejected", "errorCode": "build_export_destination_invalid"}
    output = (
        _destination_path.resolve()
        if _destination_path is not None
        else exports_dir() / f"{_safe_filename(str(build['name']))}-{uuid4().hex[:8]}.build"
    )
    root = output.parent
    temp = root / f".{output.name}.{uuid4().hex}.tmp"
    try:
        root.mkdir(parents=True, exist_ok=True)
        temp.write_text(converted["serializedBuild"], encoding="utf-8")
        temp.replace(output)
    except OSError:
        temp.unlink(missing_ok=True)
        return {"status": "rejected", "errorCode": "build_export_write_failed"}
    return {
        "status": "exported",
        "artifactId": manifest.artifact_id,
        "sourceHash": manifest.source_hash,
        "deliveryStatus": manifest.delivery_status,
        "outputPath": str(output),
        "format": "GGG Build Planner v1 experimental",
        "singleStage": True,
        "provider": converted["provider"],
        "warnings": warnings,
        "conversionStats": converted["stats"],
        "schemaValidation": validation,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "containsRawPob": False,
        "guidanceOnly": {
            "authoritativeFormat": "pob_xml_or_import_code",
            "limitedFields": [
                "rare_magic_gear_details",
                "equipment_sockets",
                "runes_and_soul_cores",
                "passive_tree_jewels",
            ],
            "descriptionDisclosureWritten": True,
        },
    }


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return cleaned[:80] or "poe2-build"
