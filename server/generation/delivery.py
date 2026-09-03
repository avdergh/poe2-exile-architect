"""Stable final-delivery orchestration for one verified build artifact."""

from __future__ import annotations

from typing import Any

from server.build_planner import exporter as build_planner_exporter

from . import artifacts, pob_exports, pob_sharing


def export_final_build_package(
    artifact_id: str,
    *,
    name: str = "",
    author: str = "",
    description: str = "",
    link: str = "",
) -> dict[str, Any]:
    """Export every user-facing file and return a complete, non-optional artifact inventory."""
    pob_result = pob_exports.export_final_pob_artifact(
        artifact_id,
        format="both",
        name=name,
    )
    build_result = build_planner_exporter.export_final_build_artifact(
        artifact_id,
        name=name,
        author=author,
        description=description,
        link=link,
    )
    share_result = pob_sharing.publish_final_pob_artifact(artifact_id)
    inventory: list[dict[str, Any]] = []
    pob_outputs = {
        output.get("format"): output.get("outputPath")
        for output in pob_result.get("outputs") or []
        if isinstance(output, dict)
    }
    for artifact_type in ("pob_xml", "pob_import_code"):
        output_format = "xml" if artifact_type == "pob_xml" else "import_code"
        output_path = pob_outputs.get(output_format)
        inventory.append(
            {
                "artifactType": artifact_type,
                "status": "exported" if output_path else "failed",
                "outputPath": output_path,
                "errorCode": None
                if output_path
                else pob_result.get("errorCode", "pob_export_failed"),
            }
        )
    build_exported = build_result.get("status") == "exported"
    build_inventory = {
        "artifactType": "official_build",
        "status": "exported" if build_exported else "failed",
        "outputPath": build_result.get("outputPath") if build_exported else None,
        "errorCode": None
        if build_exported
        else build_result.get("errorCode", "build_export_failed"),
        "warnings": build_result.get("warnings") or [],
    }
    if build_result.get("guidanceOnly") is not None:
        build_inventory["guidanceOnly"] = build_result["guidanceOnly"]
    inventory.append(build_inventory)
    share_published = share_result.get("status") == "published"
    inventory.append(
        {
            "artifactType": "poe_ninja_pob",
            "status": "published" if share_published else "failed",
            "url": share_result.get("url") if share_published else None,
            "errorCode": (
                None
                if share_published
                else share_result.get("errorCode", "poe_ninja_upload_failed")
            ),
            "provider": "poe.ninja",
            "publicExternalUpload": True,
        }
    )
    exported_count = sum(
        item["status"] in {"exported", "published"} for item in inventory
    )
    status = "exported" if exported_count == len(inventory) else "partial"
    cleanup_ready = (
        artifacts.mark_final_build_delivery_complete(artifact_id) if status == "exported" else False
    )
    return {
        "status": status,
        "artifactId": artifact_id,
        "deliveryStatus": pob_result.get("deliveryStatus")
        or build_result.get("deliveryStatus")
        or "candidate",
        "artifacts": inventory,
        "exportedCount": exported_count,
        "expectedCount": len(inventory),
        "runtimeCleanupReady": cleanup_ready,
        "responseContainsRawPob": False,
        "publicExternalUpload": True,
        "externalUploadContainsPobMaterial": True,
    }
