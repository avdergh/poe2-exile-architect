"""Publish one verified final PoB artifact to the official poe.ninja PoB host."""

from __future__ import annotations

from datetime import datetime, timezone
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from server.compute.pob_code import encode_code

from . import artifacts


UPLOAD_URL = "https://poe.ninja/poe2/pob/api/upload"
PUBLIC_URL_ROOT = "https://poe.ninja/poe2/pob/"
UPLOAD_TIMEOUT_SECONDS = 20.0
MAX_RESPONSE_BYTES = 2048
_SHARE_PATH_RE = re.compile(r"^/(?:poe2/)?pob/([A-Za-z0-9_-]{1,64})/?$")
_ALLOWED_HOSTS = {"poe.ninja", "www.poe.ninja", "poe2.ninja", "www.poe2.ninja"}


def publish_final_pob_artifact(
    artifact_id: str,
    *,
    timeout_seconds: float = UPLOAD_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Upload a verified artifact's encoded PoB material and return only a safe public URL."""

    loaded = artifacts.read_final_build_artifact_for_export(artifact_id)
    if loaded is None:
        return _error(artifact_id, "final_artifact_not_found_or_corrupt")
    manifest, xml = loaded
    code = encode_code(xml)
    body = urllib.parse.urlencode({"code": code}).encode("ascii")
    request = urllib.request.Request(
        UPLOAD_URL,
        data=body,
        method="POST",
        headers={
            "Accept": "text/plain",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Path of Building/Exile-Architect",
        },
    )
    try:
        with urllib.request.urlopen(  # noqa: S310 - fixed HTTPS poe.ninja endpoint.
            request,
            timeout=float(timeout_seconds),
        ) as response:
            raw_response = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError:
        return _error(artifact_id, "poe_ninja_upload_http_error")
    except (OSError, TimeoutError, urllib.error.URLError, ValueError):
        return _error(artifact_id, "poe_ninja_upload_unavailable")
    if len(raw_response) > MAX_RESPONSE_BYTES:
        return _error(artifact_id, "poe_ninja_upload_response_invalid")
    try:
        returned_url = raw_response.decode("utf-8", "strict").strip()
    except UnicodeDecodeError:
        return _error(artifact_id, "poe_ninja_upload_response_invalid")
    public_url = _canonical_public_url(returned_url)
    if public_url is None:
        return _error(artifact_id, "poe_ninja_upload_response_invalid")
    return {
        "status": "published",
        "artifactId": manifest.artifact_id,
        "sourceHash": manifest.source_hash,
        "provider": "poe.ninja",
        "url": public_url,
        "uploadedAt": datetime.now(timezone.utc).isoformat(),
        "publicExternalUpload": True,
        "externalUploadContainsPobMaterial": True,
        "responseContainsRawPob": False,
    }


def _canonical_public_url(value: str) -> str | None:
    if not value or len(value) > 512:
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme.casefold() != "https" or (parsed.hostname or "").casefold() not in _ALLOWED_HOSTS:
        return None
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    match = _SHARE_PATH_RE.fullmatch(parsed.path)
    return f"{PUBLIC_URL_ROOT}{match.group(1)}" if match else None


def _error(artifact_id: str, error_code: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "artifactId": artifact_id,
        "provider": "poe.ninja",
        "errorCode": error_code,
        "publicExternalUpload": True,
        "responseContainsRawPob": False,
    }
