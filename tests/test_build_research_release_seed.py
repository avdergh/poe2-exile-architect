from __future__ import annotations

import json
import sqlite3
import pytest
from contextlib import closing
from datetime import datetime, timezone

from scripts import build_research_release_seed as release_seed
from server.knowledge import mature_learning
from server.knowledge import research_runtime


@pytest.mark.parametrize("fail_validation", [False, True])
def test_v5_publication_leaves_no_private_snapshot_in_output_directory(tmp_path, monkeypatch, fail_validation):
    source = tmp_path / "private-source.sqlite"
    con = mature_learning.connect(source)
    con.executescript(mature_learning._SCHEMA_SQL)
    con.executescript(mature_learning._PHASE4_SCHEMA_SQL)
    mature_learning._migrate_phase4_additive_schema(con)
    mature_learning._migrate_research_memory_v5(con)
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('schema_version','5')")
    con.commit()
    con.close()
    _insert_family_and_record(source, scope="global_seed", suffix="public")
    _insert_family_and_record(source, scope="local_user", suffix="private")
    marker = "唯一私有正文不得进入发布目录"
    with sqlite3.connect(source) as con:
        con.execute("UPDATE deep_research_records SET content=? WHERE knowledge_scope='local_user'", (marker,))
    before = source.read_bytes()
    output = tmp_path / "publication" / "release.sqlite"
    if fail_validation:
        def reject(_path):
            raise ValueError("intentional validation failure")
        monkeypatch.setattr(release_seed, "_validate_seed", reject)
        with pytest.raises(ValueError, match="intentional"):
            release_seed.build_release_seed(source=source, output=output, release_version="test")
        assert list(output.parent.iterdir()) == []
    else:
        release_seed.build_release_seed(source=source, output=output, release_version="test")
        assert list(output.parent.iterdir()) == [output]
        assert marker.encode("utf-8") not in output.read_bytes()
        with sqlite3.connect(output) as con:
            assert con.execute("SELECT count(*) FROM research_content_revisions").fetchone()[0] == 1
    assert source.read_bytes() == before


def _insert_family_and_record(db_path, *, scope: str, suffix: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    family_key = f"family:{suffix}"
    with closing(sqlite3.connect(db_path)) as con:
        con.execute(
            """
            INSERT OR IGNORE INTO research_build_families(
                knowledge_scope, build_family_key, ascendancy_key, primary_skill_key, secondary_skill_keys,
                evidence_count, created_at, last_seen_at
            ) VALUES (?, ?, 'ascendancy:test', 'skill:test', '[]', 1, ?, ?)
            """,
            (scope, family_key, now, now),
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
                '[]', '[]', '{}', 'test-v1', 2, '0.5.4', '0_5', '0.22.0',
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
        source_ref = f"case-ref:{suffix}"
        con.execute(
            "UPDATE deep_research_records SET source_case_refs = ? WHERE record_id = ?",
            (json.dumps([source_ref]), f"record:{suffix}"),
        )
        con.execute(
            "INSERT INTO research_source_provenance VALUES (?, ?, 'test', ?, ?)",
            (source_ref, scope, now, now),
        )
        con.execute(
            "INSERT INTO research_build_family_evidence VALUES (?, ?, ?, ?, ?)",
            (scope, family_key, source_ref, now, now),
        )
        con.execute(
            """
            INSERT INTO deep_research_record_evidence(
                knowledge_scope, knowledge_key, source_case_ref, safe_evidence_refs,
                observed_component_keys, observed_component_mentions, conditions,
                failure_conditions, game_patch, passive_tree_version, pob_version_or_commit,
                accepted_projection_hash, source_state_scope, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, '["evidence-ref:test"]', '["skill:test"]', '[]', '[]', '[]',
                      '0.5.4', '0_5', '0.22.0', NULL, 'unknown', ?, ?)
            """,
            (scope, f"knowledge:{suffix}", source_ref, now, now),
        )
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM deep_research_records WHERE record_id = ?", (f"record:{suffix}",)
        ).fetchone()
        projection = research_runtime.projection_hash(
            {**dict(row), "source_state_scope": "state_agnostic"}
        )
        con.execute(
            "UPDATE deep_research_records SET source_state_scope = 'state_agnostic', "
            "projection_hash = ? WHERE record_id = ?",
            (projection, f"record:{suffix}"),
        )
        con.execute(
            "UPDATE deep_research_record_evidence SET source_state_scope = 'state_agnostic', "
            "accepted_projection_hash = ? WHERE knowledge_scope = ? AND knowledge_key = ?",
            (projection, scope, f"knowledge:{suffix}"),
        )
        if "record_id" in {row[1] for row in con.execute("PRAGMA table_info(deep_research_record_evidence)")}:
            con.execute(
                "UPDATE deep_research_record_evidence SET record_id = ?, binding_issue = NULL "
                "WHERE knowledge_scope = ? AND knowledge_key = ?",
                (f"record:{suffix}", scope, f"knowledge:{suffix}"),
            )
        con.commit()


def _insert_edge(db_path, *, scope: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(db_path)) as con:
        con.execute(
            """
            INSERT INTO research_semantic_edges(
                edge_id, source_key, target_key, canonical_source_key, canonical_target_key,
                edge_type, rationale, source_case_refs, safe_evidence_refs, game_patch,
                passive_tree_version, pob_version_or_commit, status, confidence,
                modelability, copy_safety_state, context_requirements,
                affected_component_keys, visibility, split, knowledge_scope,
                directionality, planner_visible, current_version_context,
                created_at, last_seen_at, last_validated_at, superseded_by_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                f"edge:{scope}",
                "skill:test",
                "unique:test",
                "skill:test",
                "unique:test",
                "enables_mechanic",
                "安全关系摘要",
                '["case-ref:test"]',
                '["evidence-ref:test"]',
                "0.5.4",
                "0_5",
                "0.22.0",
                "valid",
                "low",
                "partial",
                "passed",
                json.dumps(
                    [{"context_type": "verification_gate_requirement", "task": "安全验证"}],
                    ensure_ascii=False,
                ),
                '["skill:test", "unique:test"]',
                "creator_visible",
                "train_context",
                scope,
                "directional",
                1,
                "{}",
                now,
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
    _insert_edge(source, scope="global_seed")

    # Packaging is not a new source observation or revalidation of old knowledge.
    provenance_fields = (
        "record_id,created_at,last_seen_at,last_validated_at,game_patch,projection_hash"
    )
    with closing(sqlite3.connect(source)) as con:
        con.execute(
            "UPDATE deep_research_records SET last_seen_at=? WHERE knowledge_scope='global_seed'",
            ("2026-08-01T00:00:00+00:00",),
        )
        con.commit()
        original_provenance = con.execute(
            f"SELECT {provenance_fields} FROM deep_research_records "
            "WHERE knowledge_scope='global_seed'"
        ).fetchall()

    report = release_seed.build_release_seed(
        source=source,
        output=output,
        release_version="test-v1",
    )

    assert report["status"] == "built"
    assert report["recordCount"] == 1
    assert report["familyCount"] == 1
    assert report["edgeCount"] == 1
    assert report["scopeCounts"] == {"global_seed": 1}
    assert output.is_file()
    with closing(sqlite3.connect(source)) as con:
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 2
    with closing(sqlite3.connect(output)) as con:
        assert con.execute(
            f"SELECT {provenance_fields} FROM deep_research_records"
        ).fetchall() == original_provenance
        assert con.execute(
            "SELECT knowledge_scope FROM deep_research_records ORDER BY knowledge_scope"
        ).fetchall() == [("global_seed",)]
        assert con.execute("SELECT build_family_key FROM research_build_families").fetchall() == [
            ("family:public",),
        ]
        assert con.execute("SELECT count(*) FROM research_dedupe_queries").fetchone()[0] == 0
        assert {key for (key,) in con.execute("SELECT key FROM meta")} == {
            "schema_version",
            "release_seed_kind",
            "release_seed_version",
            "release_seed_created_at",
        }
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
