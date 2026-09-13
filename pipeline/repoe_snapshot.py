"""Fetch and verify one immutable RePoE export, independently of PoB model certification."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import Any, Iterator
from urllib.request import Request, urlopen

from server.runtime.file_lock import interprocess_file_lock

REPOSITORY = "https://raw.githubusercontent.com/repoe-fork/poe2"
HEAD_URL = "https://api.github.com/repos/repoe-fork/poe2/commits/master"
SOURCE_FILES = (
    "base_items.min.json", "skill_gems.min.json", "skills.min.json",
    "ascendancies.min.json", "mods.min.json",
)
MANIFEST_NAME = "source-manifest.json"
PENDING_NAME = ".repoe-publication-pending.json"


@contextmanager
def snapshot_guard(raw_dir: Path) -> Iterator[None]:
    """Readers and publication share a cross-process lock for this managed input directory."""
    with interprocess_file_lock(raw_dir / ".repoe-input.lock"):
        yield


def _read_url(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "poe2-build-mcp/0.1"})
    with urlopen(request, timeout=120) as response:
        return response.read()


def _commit(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{40}", value) is None:
        raise ValueError("RePoE source commit must be a full immutable SHA")
    return value


def _source_url(commit: str, name: str) -> str:
    return f"{REPOSITORY}/{commit}/data/{name.replace('.min.json', '.json')}"


def fetch_snapshot(raw_dir: Path, *, commit: str | None = None) -> dict[str, Any]:
    """Stage the whole export before replacing inputs; the manifest is published last.

    A failed download preserves previous inputs. If publication itself is interrupted, subsequent
    verification rejects mixed bytes instead of authorizing the old or new snapshot accidentally.
    """
    commit = _commit(commit if commit is not None else json.loads(_read_url(HEAD_URL))["sha"])
    version_url = f"{REPOSITORY}/{commit}/exported-version.txt"
    version_bytes = _read_url(version_url)
    version = version_bytes.decode("utf-8").strip()
    if re.fullmatch(r"\d+(?:\.\d+){2,}", version) is None:
        raise ValueError("Invalid RePoE exported version")
    raw_dir = raw_dir.resolve()
    raw_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    with TemporaryDirectory(prefix=".repoe-", dir=raw_dir) as temporary:
        staged = Path(temporary).resolve()
        if not staged.is_relative_to(raw_dir):
            raise ValueError("RePoE staging escaped its input directory")
        for name in SOURCE_FILES:
            url = _source_url(commit, name)
            data = _read_url(url)
            if not isinstance(json.loads(data), dict):
                raise ValueError(f"RePoE {name} must be an object")
            (staged / name).write_bytes(data)
            entries.append({"localFile": name, "sourceUrl": url,
                            "sha256": hashlib.sha256(data).hexdigest()})
        manifest = {
            "schemaVersion": 2, "sourceCommit": commit, "exportedVersion": version,
            "versionSource": version_url,
            "versionFileSha256": hashlib.sha256(version_bytes).hexdigest(), "files": entries,
        }
        (staged / "exported-version.txt").write_bytes(version_bytes)
        (staged / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        with snapshot_guard(raw_dir):
            # A durable marker also protects the first publication over legacy/no-manifest data.
            pending = raw_dir / PENDING_NAME
            pending.write_text(json.dumps({"sourceCommit": commit}), encoding="utf-8")
            for name in (*SOURCE_FILES, "exported-version.txt", MANIFEST_NAME):
                (staged / name).replace(raw_dir / name)
            _verify_snapshot(raw_dir, publication_in_progress=True)
            pending.unlink()
    return manifest


def verify_snapshot(raw_dir: Path) -> dict[str, Any] | None:
    """Return immutable source evidence, or None for legacy unbound inputs. Never upgrade legacy."""
    return _verify_snapshot(raw_dir)


def _verify_snapshot(raw_dir: Path, *, publication_in_progress: bool = False) -> dict[str, Any] | None:
    if not publication_in_progress and (raw_dir / PENDING_NAME).exists():
        raise ValueError("RePoE publication interrupted; refresh the complete snapshot before use")
    manifest_path = raw_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Invalid RePoE source manifest")
    if manifest.get("schemaVersion") in (None, 1):
        return None
    if manifest.get("schemaVersion") != 2:
        raise ValueError("Unsupported RePoE source manifest schema")
    commit = _commit(manifest.get("sourceCommit"))
    if manifest.get("versionSource") != f"{REPOSITORY}/{commit}/exported-version.txt":
        raise ValueError("RePoE version source is not bound to the commit")
    version_bytes = (raw_dir / "exported-version.txt").read_bytes()
    if (hashlib.sha256(version_bytes).hexdigest() != manifest.get("versionFileSha256")
            or version_bytes.decode("utf-8").strip() != manifest.get("exportedVersion")):
        raise ValueError("RePoE exported version binding changed")
    rows = manifest.get("files")
    if not isinstance(rows, list) or len(rows) != len(SOURCE_FILES):
        raise ValueError("Incomplete RePoE input manifest")
    names = [row.get("localFile") for row in rows if isinstance(row, dict)]
    if len(names) != len(rows) or set(names) != set(SOURCE_FILES):
        raise ValueError("RePoE manifest has missing or duplicate inputs")
    for row in rows:
        name = row["localFile"]
        if (row.get("sourceUrl") != _source_url(commit, name)
                or hashlib.sha256((raw_dir / name).read_bytes()).hexdigest() != row.get("sha256")):
            raise ValueError(f"RePoE source binding changed: {name}")
    return manifest
