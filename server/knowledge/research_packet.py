"""Transient Phase 4 research packet construction."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PACKET_PREFIX = "poe-bd-creator-research-packet-"
MAX_TTL_SECONDS = 24 * 60 * 60


def build_research_packet(
    case: dict[str, Any],
    *,
    persist_for_transport: bool = False,
    ttl_seconds: int = 60 * 60,
    temp_root: Path | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    ttl = max(1, min(int(ttl_seconds), MAX_TTL_SECONDS))
    expires = now + timedelta(seconds=ttl)
    safe_metadata = dict(case.get("safeMetadata") or {})
    raw_context = dict(case.get("rawContext") or {})
    packet_core = {
        "safeMetadata": safe_metadata,
        "rawContext": raw_context,
        "copySafetyRules": [
            "Final output must not contain raw PoB code, raw XML, full gear, full passive path, or full gem links.",
            "Durable artifacts may contain only safe hashes and safe evidence refs.",
        ],
        "requestedOutputSchema": "ResearcherOutput schema_version=4",
    }
    safe_hash = _safe_hash(packet_core)
    packet = {
        "packetId": f"rp-{safe_hash[:16]}",
        "createdAt": now.isoformat(timespec="seconds"),
        "expiresAt": expires.isoformat(timespec="seconds"),
        "safeHash": safe_hash,
        **packet_core,
    }
    result: dict[str, Any] = {"ok": True, "packet": packet}
    if persist_for_transport:
        root = Path(temp_root) if temp_root is not None else Path(tempfile.gettempdir())
        directory = Path(tempfile.mkdtemp(prefix=PACKET_PREFIX, dir=root))
        path = directory / "packet.json"
        path.write_text(json.dumps(packet, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        result["packetPath"] = str(path)
    return result


def cleanup_expired_packets(
    *,
    temp_root: Path | None = None,
    now: str | datetime | None = None,
) -> dict[str, Any]:
    root = Path(temp_root) if temp_root is not None else Path(tempfile.gettempdir())
    current = _parse_time(now) if now is not None else datetime.now(timezone.utc)
    removed = 0
    if not root.exists():
        return {"removed": 0}
    for child in root.iterdir():
        if not child.is_dir() or not child.name.startswith(PACKET_PREFIX):
            continue
        packet_path = child / "packet.json"
        expired = True
        if packet_path.exists():
            try:
                payload = json.loads(packet_path.read_text(encoding="utf-8"))
                expired = _parse_time(payload.get("expiresAt")) <= current
            except (OSError, ValueError, TypeError):
                expired = True
        if expired:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return {"removed": removed}


def _safe_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_time(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value or "")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)
