from __future__ import annotations

import gzip
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from scripts.build_research_release_seed import build_release_seed
from scripts.package_physical_graph_seed import package_graph_seed
from server import paths
from server.knowledge import graph_seed
from server.knowledge import mature_learning
from server.knowledge import research_runtime
from server.knowledge import physical_graph as pg


def _insert_safe_family_record(database: Path) -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC).isoformat()
    family_key = "family:ascendancy:martial_artist|primary:skill:flicker|secondary:skill:bell"
    with sqlite3.connect(database) as con:
        con.execute(
            """
            INSERT INTO research_build_families(
                knowledge_scope, build_family_key, ascendancy_key, primary_skill_key, secondary_skill_keys,
                evidence_count, created_at, last_seen_at
            ) VALUES ('global_seed', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                family_key,
                "ascendancy:martial_artist",
                "skill:flicker",
                json.dumps(["skill:bell"]),
                2,
                now,
                now,
            ),
        )
        con.execute(
            """
            INSERT INTO deep_research_records(
                record_id, research_group_id, build_family_key, knowledge_key,
                evidence_count, record_kind, title, summary, content, content_language,
                length_exception_reason, component_keys, component_mentions, source_case_refs,
                safe_evidence_refs, conditions, failure_conditions, typed_payload, class_key,
                ascendancy_key, extraction_method_version, record_schema_version, game_patch,
                passive_tree_version, pob_version_or_commit, visibility, split, knowledge_scope,
                status, copy_safety_state, current_version_context, created_at, last_seen_at,
                last_validated_at, superseded_by_id
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                "record:release-fixture",
                "research-group:release-fixture",
                family_key,
                "knowledge:release-fixture",
                2,
                "mechanic_chain",
                "测试机制链",
                "用于验证插件发布种子。",
                "主技能与单体技能形成可验证的职责组合。",
                "zh-CN",
                None,
                json.dumps(["skill:flicker", "skill:bell"]),
                "[]",
                json.dumps(["case:public-safe"]),
                json.dumps(["evidence:public-safe"]),
                json.dumps(["技能可用"]),
                json.dumps(["资源不闭环时不可采用"]),
                json.dumps({"schemaVersion": 1}),
                "class:monk",
                "ascendancy:martial_artist",
                "test-v1",
                2,
                "0.5.4",
                "0_5",
                "0.5.4",
                "creator_visible",
                "train_context",
                "global_seed",
                "valid",
                "passed",
                json.dumps({"gamePatch": "0.5.4", "passiveTreeVersion": "0_5"}),
                now,
                now,
                now,
                None,
            ),
        )
        con.execute(
            "INSERT INTO research_source_provenance VALUES (?, 'global_seed', 'test', ?, ?)",
            ("case:public-safe", now, now),
        )
        con.execute(
            "INSERT INTO research_build_family_evidence VALUES (?, ?, ?, ?, ?)",
            ("global_seed", family_key, "case:public-safe", now, now),
        )
        con.execute(
            """
            INSERT INTO deep_research_record_evidence(
                knowledge_scope, knowledge_key, source_case_ref, safe_evidence_refs,
                observed_component_keys, observed_component_mentions, conditions,
                failure_conditions, game_patch, passive_tree_version, pob_version_or_commit,
                accepted_projection_hash, source_state_scope, first_seen_at, last_seen_at
            ) VALUES ('global_seed', 'knowledge:release-fixture', 'case:public-safe',
                      '["evidence:public-safe"]', '["skill:flicker","skill:bell"]', '[]',
                      '[]', '[]', '0.5.4', '0_5', '0.5.4', NULL, 'unknown', ?, ?)
            """,
            (now, now),
        )
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM deep_research_records WHERE record_id = 'record:release-fixture'"
        ).fetchone()
        projection = research_runtime.projection_hash(
            {**dict(row), "source_state_scope": "state_agnostic"}
        )
        con.execute(
            "UPDATE deep_research_records SET source_state_scope = 'state_agnostic', "
            "projection_hash = ? WHERE record_id = 'record:release-fixture'",
            (projection,),
        )
        con.execute(
            "UPDATE deep_research_record_evidence SET source_state_scope = 'state_agnostic', "
            "accepted_projection_hash = ? WHERE knowledge_key = 'knowledge:release-fixture'",
            (projection,),
        )
        con.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            ("local_backup_path", "C:\\Users\\private\\research.sqlite"),
        )
        con.execute(
            """
            INSERT INTO research_dedupe_queries(
                dedupe_query_ref, query_hash, query_text_preview, component_keys,
                request_contract, result_contract, visibility, split, knowledge_scope,
                created_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "receipt:local",
                "hash",
                "local query",
                "[]",
                "{}",
                "{}",
                "creator_visible",
                "train_context",
                "global_seed",
                now,
                now,
            ),
        )
        con.commit()


def test_research_release_seed_is_sanitized_and_installed_once(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "mutable.sqlite"
    mature_learning.initialize_store(source)
    _insert_safe_family_record(source)
    bundle_root = tmp_path / "bundle"
    release_seed = bundle_root / "data" / "mature_build_learning" / "release.sqlite"

    report = build_release_seed(
        source=source,
        output=release_seed,
        release_version="0.1.test",
    )
    assert report["recordCount"] == 1
    mature_learning.validate_release_seed(release_seed)
    with sqlite3.connect(release_seed) as con:
        assert con.execute("SELECT count(*) FROM research_dedupe_queries").fetchone()[0] == 0
        assert (
            con.execute("SELECT value FROM meta WHERE key = 'local_backup_path'").fetchone() is None
        )

    target = tmp_path / "user-data" / "mature_build_learning.sqlite"
    monkeypatch.setattr(paths, "BUNDLE_ROOT", bundle_root)
    monkeypatch.setattr(mature_learning, "mature_learning_path", lambda: target)
    assert mature_learning.initialize_store() == target
    with sqlite3.connect(target) as con:
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 1
        con.execute("INSERT INTO meta(key, value) VALUES ('local_marker', 'keep-me')")
        con.commit()

    assert mature_learning.initialize_store() == target
    with sqlite3.connect(target) as con:
        assert con.execute("SELECT value FROM meta WHERE key = 'local_marker'").fetchone()[0] == (
            "keep-me"
        )


def _graph_snapshot(snapshot_id: str) -> pg.GraphSnapshot:
    source = pg.GraphSource(
        source_id=f"source:{snapshot_id}",
        kind="test_fixture",
        source_file="tests/test_release_seed_packaging.py",
        claims=(pg.SourceClaim("passive_tree_version", "0_5"),),
    )
    node = pg.GraphNode(
        stable_key="skill:ReleaseSeed",
        node_type="active_skill",
        display_name="Release Seed",
        source_refs=(source.source_id,),
    )
    return pg.GraphSnapshot(
        snapshot_id=snapshot_id,
        created_at=datetime(2026, 8, 5, tzinfo=UTC),
        sources=(source,),
        nodes=(node,),
        edges=(),
    )


def test_physical_graph_release_seed_is_portable_and_installed_once(
    tmp_path: Path, monkeypatch
) -> None:
    source_root = tmp_path / "graph-source"
    source_root.mkdir()
    snapshot = _graph_snapshot("physical-graph-release-test")
    source_snapshot = source_root / "snapshot.json"
    pg.save_snapshot(snapshot, source_snapshot)
    pg.register_snapshot(source_root / "snapshot_index.sqlite", snapshot, source_snapshot)

    bundle_root = tmp_path / "bundle"
    output = bundle_root / "data" / "physical_graph"
    report = package_graph_seed(source_dir=source_root, output_dir=output)
    assert report["snapshotId"] == snapshot.snapshot_id
    seed_manifest = json.loads((output / "seed.json").read_text(encoding="utf-8"))
    assert not Path(seed_manifest["snapshotFile"]).is_absolute()
    assert b"\r\n" not in (output / "seed.json").read_bytes()
    snapshot_seed = output / seed_manifest["snapshotFile"]
    assert snapshot_seed.name.endswith(".json.gz")
    assert seed_manifest.get("compressed") is True

    decompressed = gzip.decompress(snapshot_seed.read_bytes()).decode("utf-8")
    assert json.loads(decompressed)["snapshot_id"] == snapshot.snapshot_id
    assert b"\r\n" not in decompressed.encode("utf-8")

    user_data = tmp_path / "user-data"
    monkeypatch.setattr(paths, "BUNDLE_ROOT", bundle_root)
    monkeypatch.setattr(paths, "user_data_dir", lambda: user_data)
    index = graph_seed.ensure_installed()
    assert pg.load_latest_snapshot(index).snapshot_id == snapshot.snapshot_id
    assert graph_seed.ensure_installed() == index
