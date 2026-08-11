from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from scripts import build_research_release_seed as release_seed
from server.knowledge import mature_learning


def _insert_family_and_record(db_path, *, scope: str, suffix: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    family_key = f"family:{suffix}"
    with closing(sqlite3.connect(db_path)) as con:
        con.execute(
            """
            INSERT OR IGNORE INTO research_build_families(
                build_family_key, ascendancy_key, primary_skill_key, secondary_skill_keys,
                evidence_count, created_at, last_seen_at
            ) VALUES (?, 'ascendancy:test', 'skill:test', '[]', 1, ?, ?)
            """,
            (family_key, now, now),
        )
        con.execute(
            """
            INSERT INTO deep_research_records(
                record_id, research_group_id, build_family_key, knowledge_key, evidence_count,
                record_kind, title, summary, content, content_language,
                component_keys, component_mentions, source_case_refs, safe_evidence_refs,
                conditions, failure_conditions, typed_payload, extraction_method_version,
                record_schema_version, game_patch, passive_tree_version, pob_version_or_commit,
                visibility, split, knowledge_scope, status, copy_safety_state,
                current_version_context, created_at, last_seen_at
            ) VALUES (
                ?, ?, ?, ?, 1, 'mechanic_chain', '安全标题', '安全摘要', '安全机制正文', 'zh-CN',
                '["skill:test"]', '[]', '["case-ref:test"]', '["evidence-ref:test"]',
                '[]', '[]', '{}', 'test-v1', 1, '0.5.4', '0_5', '0.22.0',
                'creator_visible', 'train_context', ?, 'valid', 'passed', '{}', ?, ?
            )
            """,
            (
                f"record:{suffix}",
                f"group:{suffix}",
                family_key,
                f"knowledge:{suffix}",
                scope,
                now,
                now,
            ),
        )
        con.commit()


def test_build_release_seed_is_copy_safe_and_does_not_mutate_source(tmp_path):
    source = tmp_path / "mutable.sqlite"
    output = tmp_path / "release.sqlite"
    mature_learning.initialize_store(source)
    _insert_family_and_record(source, scope="global_seed", suffix="public")
    _insert_family_and_record(source, scope="local_user", suffix="private")

    report = release_seed.build_release_seed(
        source=source,
        output=output,
        release_version="test-v1",
    )

    assert report["status"] == "built"
    assert report["recordCount"] == 2
    assert report["familyCount"] == 2
    assert report["scopeCounts"] == {"global_seed": 1, "local_user": 1}
    assert output.is_file()
    with closing(sqlite3.connect(source)) as con:
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 2
    with closing(sqlite3.connect(output)) as con:
        assert con.execute(
            "SELECT knowledge_scope FROM deep_research_records ORDER BY knowledge_scope"
        ).fetchall() == [("global_seed",), ("local_user",)]
        assert con.execute("SELECT build_family_key FROM research_build_families").fetchall() == [
            ("family:private",),
            ("family:public",),
        ]
        assert con.execute("SELECT count(*) FROM research_dedupe_queries").fetchone()[0] == 0
    mature_learning.validate_release_seed(output)


def test_default_store_installs_release_seed_once_without_overwriting_local_state(
    tmp_path, monkeypatch
):
    source = tmp_path / "mutable.sqlite"
    seed = tmp_path / "release.sqlite"
    target = tmp_path / "user-data" / "mature_build_learning.sqlite"
    mature_learning.initialize_store(source)
    _insert_family_and_record(source, scope="global_seed", suffix="public")
    release_seed.build_release_seed(source=source, output=seed, release_version="test-v1")
    monkeypatch.setattr(mature_learning, "mature_learning_path", lambda: target)
    monkeypatch.setattr(
        mature_learning.paths,
        "mature_learning_release_seed_path",
        lambda: seed,
    )

    mature_learning.initialize_store()
    _insert_family_and_record(target, scope="local_user", suffix="local")
    mature_learning.initialize_store()

    with closing(sqlite3.connect(target)) as con:
        scopes = con.execute(
            "SELECT knowledge_scope FROM deep_research_records ORDER BY knowledge_scope"
        ).fetchall()
    assert scopes == [("global_seed",), ("local_user",)]
