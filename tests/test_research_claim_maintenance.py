"""来源声明拆分后，维护、合并与发布不能覆盖同主题的其他结论。"""

from contextlib import closing
from copy import deepcopy
import json

import pytest

from scripts import build_research_release_seed
from server.knowledge import mature_learning, research_claims, research_known_repairs
from server.knowledge import research_maintenance, research_merge, research_runtime
from test_research_merge import _plan, _seed


def _branch(db_path, original_id, *, visibility="creator_visible"):
    with closing(mature_learning.connect(db_path)) as con:
        row = dict(con.execute(
            "SELECT * FROM deep_research_records WHERE record_id = ?", (original_id,)
        ).fetchone())
        row.update(
            record_id="drr-conditional-branch", content="同机制只有另一条件满足时才成立。",
            conditions='["另一条件已确认"]', source_case_refs='["case:branch"]',
            safe_evidence_refs='["evidence:branch"]', visibility=visibility,
            split="train_context" if visibility == "creator_visible" else "quarantine",
        )
        row["projection_hash"] = research_runtime.projection_hash(row)
        con.execute(
            f"INSERT INTO deep_research_records({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
            tuple(row.values()),
        )
        claim = dict(con.execute(
            "SELECT * FROM deep_research_record_evidence WHERE record_id = ?", (original_id,)
        ).fetchone())
        claim.update(
            source_case_ref="case:branch", record_id=row["record_id"], binding_issue=None,
            conditions=row["conditions"], safe_evidence_refs=row["safe_evidence_refs"],
            accepted_projection_hash=row["projection_hash"],
        )
        con.execute(
            f"INSERT INTO deep_research_record_evidence({','.join(claim)}) "
            f"VALUES ({','.join('?' for _ in claim)})", tuple(claim.values()),
        )
        con.execute(
            "INSERT INTO research_source_provenance VALUES (?, ?, 'test', ?, ?)",
            ("case:branch", row["knowledge_scope"], row["created_at"], row["last_seen_at"]),
        )
        con.execute(
            "INSERT INTO research_build_family_evidence VALUES (?, ?, ?, ?, ?)",
            (row["knowledge_scope"], row["build_family_key"], "case:branch",
             row["created_at"], row["last_seen_at"]),
        )
        con.commit()
    return row


def test_reviewed_merge_leaves_other_conditional_conclusion_and_claim_unchanged(tmp_path):
    path = tmp_path / "memory.sqlite"
    legacy, current, payload = _seed(path)
    branch = _branch(path, current)
    service = research_merge.ResearchMergeService(path)
    plan = _plan(legacy, current, payload)
    preview = service.preview(plan)
    assert preview["status"] == "preview_ready", preview
    result = service.apply(
        plan, expected_memory_revision=preview["expectedMemoryRevision"],
        merge_plan_hash=preview["mergePlanHash"], user_approved=True,
    )
    assert result["status"] == "applied", result
    with closing(mature_learning.connect(path)) as con:
        actual = dict(con.execute(
            "SELECT * FROM deep_research_records WHERE record_id = ?", (branch["record_id"],)
        ).fetchone())
        assert actual == branch
        assert con.execute(
            "SELECT record_id FROM deep_research_record_evidence WHERE source_case_ref = 'case:branch'"
        ).fetchone()[0] == branch["record_id"]
        target = con.execute("SELECT * FROM deep_research_records WHERE record_id = ?", (current,)).fetchone()
        assert json.loads(target["source_case_refs"]) == ["case:current"]
        assert target["evidence_count"] == 1
        research_claims.validate_storage(con)


def test_id_reconcile_and_support_calibration_protect_condition_variants(tmp_path):
    path = tmp_path / "memory.sqlite"
    _, current, _ = _seed(path)
    branch = _branch(path, current)
    result = research_maintenance.reconcile_deep_record_ids(db_path=path, apply=True)
    assert result["status"] == "blocked_unsafe_targets", result
    assert branch["record_id"] in {row["recordId"] for row in result["protectedRecords"]}
    with closing(mature_learning.connect(path)) as con:
        row = con.execute("SELECT * FROM deep_research_records WHERE record_id = ?", (current,)).fetchone()
        with pytest.raises(ValueError, match="support_calibration_unsafe_target"):
            research_maintenance._apply_support_calibration(
                con, row=row, source_ref="case:current", spec={}, now=row["last_seen_at"]
            )
        assert dict(con.execute(
            "SELECT * FROM deep_research_records WHERE record_id = ?", (branch["record_id"],)
        ).fetchone()) == branch


def test_merge_witness_requires_explicit_record_binding(tmp_path):
    path = tmp_path / "memory.sqlite"
    _, current, _ = _seed(path)
    branch = _branch(path, current)
    with closing(mature_learning.connect(path)) as con:
        row = con.execute("SELECT * FROM deep_research_records WHERE record_id = ?", (current,)).fetchone()
        con.execute(
            "UPDATE deep_research_record_evidence SET record_id = ? WHERE record_id = ?",
            (branch["record_id"], current),
        )
        assert research_merge._projection_witness_rows(con, [row], row["projection_hash"]) == []
        con.rollback()


def test_merge_counts_one_source_once_when_multiple_claim_keys_support_the_same_content(tmp_path):
    path = tmp_path / "memory.sqlite"
    legacy, current, payload = _seed(path)
    with closing(mature_learning.connect(path)) as con:
        claim = dict(con.execute(
            "SELECT * FROM deep_research_record_evidence WHERE record_id = ?", (current,)
        ).fetchone())
        claim["source_claim_key"] = "second-confirmation"
        con.execute(
            f"INSERT INTO deep_research_record_evidence({','.join(claim)}) "
            f"VALUES ({','.join('?' for _ in claim)})", tuple(claim.values()),
        )
        con.commit()
    service = research_merge.ResearchMergeService(path)
    plan = _plan(legacy, current, payload)
    preview = service.preview(plan)
    assert preview["status"] == "preview_ready", preview
    assert preview["items"][0]["projectionWitnessSourceCaseRefs"] == ["case:current"]
    result = service.apply(
        plan, expected_memory_revision=preview["expectedMemoryRevision"],
        merge_plan_hash=preview["mergePlanHash"], user_approved=True,
    )
    assert result["items"][0]["projectionWitnessCount"] == 1
    with closing(mature_learning.connect(path)) as con:
        row = con.execute("SELECT * FROM deep_research_records WHERE record_id = ?", (current,)).fetchone()
        assert row["evidence_count"] == 1
        assert json.loads(row["source_case_refs"]) == ["case:current"]
        assert con.execute(
            "SELECT count(*) FROM deep_research_record_evidence WHERE record_id = ?", (current,)
        ).fetchone()[0] == 2
        research_claims.validate_storage(con)


def test_reviewed_new_content_without_witness_keeps_revalidation_without_inherited_sources(tmp_path):
    path = tmp_path / "memory.sqlite"
    legacy, current, payload = _seed(path)
    service = research_merge.ResearchMergeService(path)
    plan = _plan(legacy, current, payload)
    plan["items"][0]["mergedRecord"]["content"] = (
        "The revised mechanism requires a newly verified source condition before adoption."
    )
    preview = service.preview(plan)
    assert preview["status"] == "preview_ready", preview
    assert preview["items"][0]["wouldRemainCreateAuthorizing"] is False
    result = service.apply(
        plan, expected_memory_revision=preview["expectedMemoryRevision"],
        merge_plan_hash=preview["mergePlanHash"], user_approved=True,
    )
    assert result["items"][0]["status"] == "needs_revalidation"
    with closing(mature_learning.connect(path)) as con:
        row = con.execute("SELECT * FROM deep_research_records WHERE record_id = ?", (current,)).fetchone()
        assert row["status"] == "needs_revalidation"
        assert json.loads(row["source_case_refs"]) == []
        assert row["evidence_count"] == 0
        assert con.execute(
            "SELECT count(*) FROM deep_research_record_evidence WHERE record_id IS NOT NULL"
        ).fetchone()[0] == 0
        research_claims.validate_storage(con)


def test_merge_cannot_relabel_target_source_patch(tmp_path):
    path = tmp_path / "memory.sqlite"
    legacy, current, payload = _seed(path)
    plan = _plan(legacy, current, payload)
    plan["items"][0]["mergedRecord"]["game_patch"] = "0.5.5"
    result = research_merge.ResearchMergeService(path).preview(plan)
    assert result["errorCode"] == "research_merge_plan_invalid", result
    assert "merge_cannot_relabel_source_versions" in result["caveats"][0]


def test_release_export_prunes_private_variant_claim_without_losing_public_conclusion(tmp_path):
    path = tmp_path / "memory.sqlite"
    _, current, _ = _seed(path)
    _branch(path, current, visibility="quarantined")
    output = tmp_path / "release.sqlite"
    report = build_research_release_seed.build_release_seed(
        source=path, output=output, release_version="claim-test"
    )
    assert report["status"] == "built", report
    with closing(mature_learning.connect(output)) as con:
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 1
        assert con.execute(
            "SELECT record_id FROM deep_research_record_evidence"
        ).fetchone()[0] == current
        assert con.execute(
            "SELECT count(*) FROM research_build_family_evidence WHERE source_case_ref = 'case:branch'"
        ).fetchone()[0] == 0
        research_claims.validate_storage(con)


def test_known_repair_sources_exclude_sibling_claims(tmp_path, monkeypatch):
    path = tmp_path / "memory.sqlite"
    _, current, _ = _seed(path)
    branch = _branch(path, current)
    with closing(mature_learning.connect(path)) as con:
        row = con.execute("SELECT * FROM deep_research_records WHERE record_id = ?", (current,)).fetchone()
        known = {
            "recordId": current, "knowledgeKey": row["knowledge_key"],
            "recordKind": row["record_kind"], "projectionHash": row["projection_hash"],
            "sourceCaseRefs": ["case:current"],
        }
    monkeypatch.setattr(research_known_repairs, "KNOWN_BAD_RECORDS", (deepcopy(known),))
    plan = research_known_repairs.inspect_known_repair(path)
    assert plan["mismatchCount"] == 0, plan
    result = research_known_repairs.apply_known_repair(path)
    assert result["status"] == "applied", result
    with closing(mature_learning.connect(path)) as con:
        assert con.execute(
            "SELECT record_id FROM deep_research_record_evidence WHERE source_case_ref = 'case:branch'"
        ).fetchone()[0] == branch["record_id"]
        research_claims.validate_storage(con)
