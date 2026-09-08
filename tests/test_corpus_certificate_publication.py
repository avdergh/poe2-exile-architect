import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from pipeline.corpus_certificate import STATIC_TABLES, rebind_certificate
from server.knowledge.corpus_certification import file_sha256


def prepare(tmp_path):
    reviewed = tmp_path / "reviewed.sqlite"
    with sqlite3.connect(reviewed) as con:
        for table in STATIC_TABLES:
            con.execute(f"CREATE TABLE {table}(id TEXT PRIMARY KEY, content TEXT)")
            con.execute(f"INSERT INTO {table} VALUES ('id','reviewed static content')")
        con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)")
        con.execute("INSERT INTO meta VALUES ('schema_version','4')")
        con.execute("CREATE TABLE mechanics(id TEXT PRIMARY KEY,content TEXT)")
        con.execute("INSERT INTO mechanics VALUES ('wiki','reference only')")
    certificate = tmp_path / "corpus.json"
    certificate.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "sha256": file_sha256(reviewed),
                "game_patch": "0.5.4",
                "passive_tree": "0_5",
                "verifiedAt": "2026-09-05T00:00:00Z",
            }
        )
    )
    rebuilt = tmp_path / "rebuilt.sqlite"
    shutil.copy2(reviewed, rebuilt)
    return reviewed, certificate, rebuilt


def test_repack_and_reference_only_refresh_preserve_original_certification(tmp_path):
    reviewed, certificate, rebuilt = prepare(tmp_path)
    with sqlite3.connect(rebuilt) as con:
        con.execute("INSERT INTO meta VALUES ('built_at','new build time')")
        con.execute("UPDATE mechanics SET content='updated reference text'")
    result = rebind_certificate(
        corpus=rebuilt,
        reviewed_corpus=reviewed,
        certificate=certificate,
        output=tmp_path / "out.json",
    )
    assert result["sha256"] == file_sha256(rebuilt)
    assert result["derivedFromCorpusSha256"] == file_sha256(reviewed)
    assert result["game_patch"] == "0.5.4"
    assert result["verifiedAt"] == "2026-09-05T00:00:00Z"


@pytest.mark.parametrize("change", ["fact", "schema", "untrusted_baseline"])
def test_changed_static_content_requires_review_and_does_not_overwrite_certificate(
    tmp_path, change
):
    reviewed, certificate, rebuilt = prepare(tmp_path)
    original = certificate.read_bytes()
    with sqlite3.connect(rebuilt) as con:
        con.execute("INSERT INTO meta VALUES ('built_at','new time')")
        if change == "fact":
            con.execute("UPDATE gems SET content='changed game rule'")
        elif change == "schema":
            con.execute("UPDATE meta SET value='5' WHERE key='schema_version'")
    if change == "untrusted_baseline":
        with sqlite3.connect(reviewed) as con:
            con.execute("UPDATE gems SET content='unreviewed input'")
    with pytest.raises(ValueError):
        rebind_certificate(
            corpus=rebuilt, reviewed_corpus=reviewed, certificate=certificate, output=certificate
        )
    assert certificate.read_bytes() == original


def test_both_publication_workflows_ship_the_validated_certificate():
    root = Path(__file__).resolve().parents[1]
    for name in ("release.yml", "refresh-data.yml"):
        text = (root / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert '"certificate": corpus_certificate' in text
        assert "pipeline.corpus_certificate --reviewed-corpus" in text
