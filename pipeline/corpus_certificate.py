"""仅为已认证静态内容的重新打包续接哈希；静态数据变化必须重新复核。"""

from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from typing import Any

from server.knowledge import corpus_certification as certificates

STATIC_TABLES = ("items", "gems", "ascendancies", "mods", "uniques")


def _static_content(path: Path) -> dict[str, Any]:
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        integrity = con.execute("PRAGMA quick_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise ValueError("corpus integrity check failed")
        tables = {
            row[0]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
            if not row[0].startswith("sqlite_")
            and "_fts" not in row[0]
            and row[0] not in {"meta", "mechanics"}
        }
        if tables != set(STATIC_TABLES):
            raise ValueError("corpus static schema changed; reviewed certificate required")
        result: dict[str, Any] = {
            "schema": con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        }
        for table in STATIC_TABLES:
            result[table] = {
                "columns": list(con.execute(f"PRAGMA table_info({table})")),
                "rows": sorted(
                    json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                    for row in con.execute(f"SELECT * FROM {table}")
                ),
            }
        return result


def rebind_certificate(
    *, corpus: Path, reviewed_corpus: Path, certificate: Path, output: Path
) -> dict[str, Any]:
    approved = json.loads(certificate.read_text(encoding="utf-8"))
    target_hash = certificates.file_sha256(corpus)
    if approved.get("sha256") == target_hash:
        result = certificates.validate(approved, corpus_sha256=target_hash)
    else:
        reviewed_hash = certificates.file_sha256(reviewed_corpus)
        certificates.validate(approved, corpus_sha256=reviewed_hash)
        if _static_content(corpus) != _static_content(reviewed_corpus):
            raise ValueError(
                "static corpus content changed; reviewed certificate required before publishing"
            )
        result = {
            **approved,
            "sha256": target_hash,
            "derivedFromCorpusSha256": reviewed_hash,
            "derivation": "identical_static_content; wiki_reference_only",
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(certificates.encode(result))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("data/corpus.sqlite"))
    parser.add_argument("--reviewed-corpus", type=Path, required=True)
    parser.add_argument("--certificate", type=Path, default=Path("data/compatibility/corpus.json"))
    parser.add_argument("--output", type=Path, default=Path("data/compatibility/corpus.json"))
    args = parser.parse_args()
    rebind_certificate(
        corpus=args.corpus,
        reviewed_corpus=args.reviewed_corpus,
        certificate=args.certificate,
        output=args.output,
    )
    print("CORPUS CERTIFICATE BOUND")


if __name__ == "__main__":
    main()
