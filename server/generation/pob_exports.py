"""User-requested local exports of verified final Path of Building artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import Any, Literal
from uuid import uuid4

from server import paths
from server.compute.pob_code import encode_code

from . import artifacts


PobExportFormat = Literal["xml", "import_code", "both"]


def exports_dir() -> Path:
    override = os.environ.get("POE_BD_POB_EXPORTS_DIR")
    return (
        Path(override).resolve() if override else (paths.user_data_dir() / "pob-exports").resolve()
    )


def export_final_pob_artifact(
    artifact_id: str,
    *,
    format: PobExportFormat = "both",
    name: str = "",
) -> dict[str, Any]:
    """Write a verified artifact to local PoB files without returning their raw contents."""
    loaded = artifacts.read_final_build_artifact_for_export(artifact_id)
    if loaded is None:
        return {"status": "rejected", "errorCode": "final_artifact_not_found_or_corrupt"}
    manifest, xml = loaded
    root = exports_dir()
    root.mkdir(parents=True, exist_ok=True)
    stem = _safe_filename(name) if name.strip() else _artifact_stem(manifest)
    suffix = uuid4().hex[:8]
    requested = ("xml", "import_code") if format == "both" else (format,)
    outputs: list[dict[str, str]] = []
    written: list[Path] = []
    try:
        for output_format in requested:
            if output_format == "xml":
                output = root / f"{stem}-{suffix}.xml"
                content = xml
            else:
                output = root / f"{stem}-{suffix}.pobcode.txt"
                content = encode_code(xml) + "\n"
            _atomic_write(output, content)
            written.append(output)
            outputs.append({"format": output_format, "outputPath": str(output)})
    except OSError:
        for output in written:
            output.unlink(missing_ok=True)
        return {"status": "rejected", "errorCode": "pob_export_write_failed"}
    return {
        "status": "exported",
        "artifactId": manifest.artifact_id,
        "sourceHash": manifest.source_hash,
        "outputs": outputs,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "responseContainsRawPob": False,
        "localFilesContainPobMaterial": True,
    }


def _atomic_write(output: Path, content: str) -> None:
    temp = output.parent / f".{output.name}.{uuid4().hex}.tmp"
    try:
        temp.write_text(content, encoding="utf-8")
        temp.replace(output)
    except OSError:
        temp.unlink(missing_ok=True)
        raise


def _artifact_stem(manifest: artifacts.FinalBuildArtifactManifest) -> str:
    summary = manifest.safe_summary
    for key in ("name", "buildName", "mainSkill", "class", "ascendancy"):
        value = summary.get(key)
        if isinstance(value, str) and value.strip():
            return _safe_filename(value)
    return f"poe2-build-{manifest.run_id[:8]}"


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return cleaned[:80] or "poe2-build"
