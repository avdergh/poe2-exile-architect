"""Build a copy-safe Phase 7 Learning Memory JSONL seed for release packaging."""

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


def build_release_seed(
    *,
    source: str | Path = DEFAULT_SOURCE,
    output: str | Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    source_path = Path(source).resolve()
    output_path = Path(output).resolve()
    if source_path == output_path:
        raise ValueError("Learning Memory seed output must differ from the mutable source")
    report = learning_memory.validate_release_seed(source_path)
    events = learning_memory._read_events_strict(source_path)
    for event in events:
        models.ensure_safe_durable_payload(event)
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
    return {
        "status": "built",
        "output": str(output_path),
        "sha256": _sha256(output_path),
        "sizeBytes": output_path.stat().st_size,
        **report,
    }


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
    args = parser.parse_args(argv)
    print(
        json.dumps(
            build_release_seed(source=args.source, output=args.output), ensure_ascii=False, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
