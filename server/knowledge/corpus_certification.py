"""Hash-bound corpus certificates, independent of executable PoB compatibility."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import threading
from typing import Any, Iterator

from server import paths
from server.runtime.file_lock import interprocess_file_lock

CERTIFICATE_FILENAME = "corpus.compatibility.json"
_lock = threading.RLock()
_held = threading.local()


@contextmanager
def corpus_guard() -> Iterator[None]:
    """Serialize certificate reads and whole-pair replacements across MCP domains."""
    lock_path = (paths.user_data_dir() / ".corpus-update.lock").resolve()
    with _lock:
        if getattr(_held, "path", None) == lock_path:
            yield
            return
        previous = getattr(_held, "path", None)
        with interprocess_file_lock(lock_path):
            _held.path = lock_path
            try:
                yield
            finally:
                _held.path = previous


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate(payload: Any, *, corpus_sha256: str) -> dict[str, Any]:
    if (
        not isinstance(payload, dict)
        or type(payload.get("schemaVersion")) is not int
        or payload["schemaVersion"] != 1
    ):
        raise ValueError("corpus certificate schema missing or invalid")
    if (
        not re.fullmatch(r"[a-f0-9]{64}", str(payload.get("sha256") or ""))
        or payload["sha256"] != corpus_sha256
    ):
        raise ValueError("corpus certificate checksum mismatched")
    if not re.fullmatch(r"\d+\.\d+\.\d+[a-z]*", str(payload.get("game_patch") or "")):
        raise ValueError("corpus certificate game patch missing or invalid")
    if not re.fullmatch(r"\d+_\d+", str(payload.get("passive_tree") or "")):
        raise ValueError("corpus certificate passive tree missing or invalid")
    return dict(payload)


def encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def certificate_for_hash(corpus_sha256: str) -> dict[str, Any] | None:
    """Use a previously installed release certificate or an identical certified bundle."""
    user_root = paths.user_data_dir()
    try:
        metadata = json.loads((user_root / "installed.json").read_text(encoding="utf-8"))
        raw = (user_root / CERTIFICATE_FILENAME).read_bytes()
        if (
            metadata.get("corpus_sha256") == corpus_sha256
            and metadata.get("corpus_certificate_sha256") == hashlib.sha256(raw).hexdigest()
        ):
            return validate(json.loads(raw), corpus_sha256=corpus_sha256)
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    try:
        certificate = paths.BUNDLE_ROOT / "data" / "compatibility" / "corpus.json"
        return validate(
            json.loads(certificate.read_text(encoding="utf-8")), corpus_sha256=corpus_sha256
        )
    except (OSError, ValueError, TypeError):
        return None


def active_certificate() -> dict[str, Any] | None:
    try:
        return certificate_for_hash(file_sha256(paths.corpus_path()))
    except OSError:
        return None
