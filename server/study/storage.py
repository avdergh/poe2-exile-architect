"""Opaque user-data runs with atomic writes and one cross-process lock per run."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
from typing import Any, Iterator

from server import paths
from server.runtime.file_lock import interprocess_file_lock

SCHEMA = "study_run_v3"
RUN_PATTERN = re.compile(r"^study-run:([a-f0-9]{32})$")


class StudyError(ValueError):
    """Only stable, raw-free codes leave the study boundary."""


def root() -> Path:
    return paths.user_data_dir() / "study"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fingerprint(value: Any) -> str:
    raw = (
        value
        if isinstance(value, bytes)
        else json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )
    return hashlib.sha256(raw).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
    try:
        with staging.open("xb") as handle:
            handle.write(data)
            handle.flush()
        staging.replace(path)
    finally:
        staging.unlink(missing_ok=True)


def read_json(path: Path) -> dict[str, Any]:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (OSError, ValueError) as exc:
        raise StudyError("study_state_unavailable") from exc


def directory(run_ref: str) -> Path:
    match = RUN_PATTERN.fullmatch(run_ref)
    if not match:
        raise StudyError("invalid_study_run_ref")
    base = root().resolve()
    selected = (base / "runs" / match[1]).resolve()
    if not selected.is_relative_to(base / "runs") or selected.is_symlink():
        raise StudyError("invalid_study_run_path")
    return selected


@contextmanager
def locked(run_ref: str, *, allow_expired: bool = False) -> Iterator[tuple[Path, dict]]:
    path = directory(run_ref)
    if not path.is_dir():
        raise StudyError("study_run_not_found")
    # Cleanup removes only raw payloads, never the run or its lock.
    with interprocess_file_lock(path / ".lock"):
        meta = read_json(path / "run.json")
        if meta.get("schemaVersion") != SCHEMA or meta.get("runRef") != run_ref:
            raise StudyError("study_run_binding_invalid")
        if not allow_expired:
            if meta.get("status") == "cleaned":
                raise StudyError("study_source_cleaned")
            if datetime.fromisoformat(meta["expiresAt"]) <= datetime.now(timezone.utc):
                raise StudyError("study_source_expired")
        yield path, meta


def record_evidence(
    meta: dict, *, kind: str, payload: Any, subjects: list[str] | None = None
) -> str:
    digest = fingerprint(
        {
            "runRef": meta["runRef"],
            "sourceHash": meta["sourceHash"],
            "kind": kind,
            "payload": payload,
        }
    )
    ref = f"study-evidence:{digest}"
    meta.setdefault("evidence", {})[ref] = {
        "kind": kind,
        "sourceHash": meta["sourceHash"],
        "fingerprint": fingerprint(payload),
        "subjectRefs": subjects or [],
        "purpose": "educational_only",
    }
    return ref
