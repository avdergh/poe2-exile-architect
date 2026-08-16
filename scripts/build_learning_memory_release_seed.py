"""Build a copy-safe Phase 7 Learning Memory JSONL seed for release packaging.

Active/narrowed family-scoped lessons are validated against the local mature Research
family table: a lesson bound to a family key that no longer exists would silently never
recall, so the build fails unless --skip-family-key-check is passed. Non-active lessons
(history) only produce a warning; deprecating a dead-key lesson is the supported way to
keep its history while stopping recall.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.learning import memory as learning_memory  # noqa: E402
from server.learning import models  # noqa: E402


DEFAULT_SOURCE = learning_memory.memory_path()
DEFAULT_OUTPUT = ROOT / "data" / "comparative_learning" / "learning-memory.seed.jsonl"


def _check_family_keys(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify family-scoped lessons point at live Research family keys.

    Lessons in an active/narrowed state must resolve, otherwise they silently never
    recall; those are hard failures. Deprecated/superseded history is reported as
    warnings (keep-history handling is supported).
    """
    from server.knowledge import mature_learning

    db_path = Path(mature_learning.mature_learning_path())
    if not db_path.exists():
        # A fresh build machine may never have run Research; fall back to the bundled
        # release family table so the dead-key guard still protects the published seed.
        fallback = ROOT / "data" / "mature_build_learning" / "release.sqlite"
        if fallback.exists():
            db_path = fallback
        else:
            return {
                "familyKeyCheck": "skipped",
                "reason": "mature_learning_db_missing",
                "errors": [],
                "warnings": [],
            }
    import sqlite3

    con = sqlite3.connect(db_path)
    try:
        live = {
            str(row[0])
            for row in con.execute(
                "SELECT build_family_key FROM research_build_families"
            ).fetchall()
        }
    finally:
        con.close()
    errors: list[str] = []
    warnings: list[str] = []
    state = learning_memory._materialize(events)
    for entry in state.values():
        if entry.get("scope") != "family":
            continue
        family_key = str(entry.get("familyKey") or "")
        if not family_key or family_key in live:
            continue
        lesson_id = str(entry.get("lessonId") or "?")
        status = str(entry.get("status") or "?")
        message = f"lesson {lesson_id} (status={status}) references unknown family key {family_key}"
        if status in {"active", "narrowed"}:
            errors.append(message)
        else:
            warnings.append(message)
    return {
        "familyKeyCheck": "failed" if errors else "passed",
        "errors": errors,
        "warnings": warnings,
    }


def build_release_seed(
    *,
    source: str | Path = DEFAULT_SOURCE,
    output: str | Path = DEFAULT_OUTPUT,
    check_family_keys: bool = True,
) -> dict[str, Any]:
    source_path = Path(source).resolve()
    output_path = Path(output).resolve()
    if source_path == output_path:
        raise ValueError("Learning Memory seed output must differ from the mutable source")
    report = learning_memory.validate_release_seed(source_path)
    events = learning_memory._read_events_strict(source_path)
    for event in events:
        models.ensure_safe_durable_payload(event)
    family_key_check: dict[str, Any] | None = None
    if check_family_keys:
        family_key_check = _check_family_keys(events)
        if family_key_check.get("errors"):
            raise ValueError(
                "release seed contains active lessons bound to unknown family keys: "
                + "; ".join(family_key_check["errors"])
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        learning_memory.validate_release_seed(temp)
        temp.replace(output_path)
    finally:
        temp.unlink(missing_ok=True)
    result: dict[str, Any] = {
        "status": "built",
        "output": str(output_path),
        "sha256": _sha256(output_path),
        "sizeBytes": output_path.stat().st_size,
        **report,
    }
    if family_key_check is not None:
        result["familyKeyCheck"] = family_key_check
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--skip-family-key-check",
        action="store_true",
        help="do not fail on active lessons bound to unknown family keys",
    )
    args = parser.parse_args(argv)
    try:
        report = build_release_seed(
            source=args.source,
            output=args.output,
            check_family_keys=not args.skip_family_key_check,
        )
    except ValueError as exc:
        print(
            json.dumps(
                {"status": "error", "errorCode": "family_key_check_failed", "detail": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
