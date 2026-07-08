from __future__ import annotations

from datetime import UTC, datetime
import json

from scripts import run_phase4_deep_review_acceptance
from server.knowledge import graph_tools as gt
from server.knowledge import mature_learning
from server.knowledge import physical_graph as pg


def test_deep_review_acceptance_writes_only_resolved_case_observations(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    review_file = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
    )
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=db_path,
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["status"] == "accepted"
    assert report["acceptedPatternCount"] == 1
    assert isinstance(report["deferredCandidateCount"], int)
    assert all(item["confidenceTier"] == "case_observation" for item in report["acceptedPatterns"])
    assert all("common" not in item["summaryZh"].casefold() for item in report["acceptedPatterns"])
    assert report["acceptedPatterns"][0]["componentResolutions"][0]["resolutionSource"] == (
        "direct_resolver"
    )

    serialized = json.dumps(report, ensure_ascii=False)
    assert "rawXml" not in serialized
    assert "rawImportCode" not in serialized
    assert "PathOfBuilding" not in serialized
    assert "eNrt" not in serialized
    assert "full support" not in serialized.casefold()

    con = mature_learning.connect(db_path)
    try:
        assert (
            con.execute("SELECT count(*) FROM research_build_patterns").fetchone()[0]
            == report["acceptedPatternCount"]
        )
        rows = con.execute(
            "SELECT confidence_tier, sample_count FROM research_build_patterns"
        ).fetchall()
        assert {row["confidence_tier"] for row in rows} == {"case_observation"}
        assert {row["sample_count"] for row in rows} == {1}
    finally:
        con.close()

    json_text = (tmp_path / "report.json").read_text(encoding="utf-8")
    md_text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "单例：fixture pattern" in json_text
    assert "单例：fixture pattern" in md_text
    assert "Subagent text was not trusted directly" in md_text


def test_deep_review_acceptance_normalizes_worker_enum_canonical_variants(tmp_path):
    variants = [
        ("BuildArchetypePattern", "build_archetype"),
        ("build-archetype observation", "build_archetype"),
        ("CoOccurrence Pattern", "cooccurrence"),
        ("plannerHintCandidate", "planner_hint"),
        ("TransitionGatePattern", "transition_gate"),
        ("failure-pattern candidate", "failure_pattern"),
    ]
    for index, (pattern_type, expected) in enumerate(variants):
        db_path = tmp_path / f"memory-{index}.sqlite"
        review_file = _write_review(
            tmp_path,
            filename=f"review-{index}.json",
            components=[
                {
                    "candidateName": "Resolved Only",
                    "componentKey": "skill:ResolvedOnlyPlayer",
                    "role": "primary_damage",
                    "resolverQuery": "Resolved Only",
                }
            ],
            candidate_overrides={
                "patternType": pattern_type,
                "axes": ["primary_skill_package", "variant_relation", "modelability_caveat"],
            },
        )
        report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
            db_path=db_path,
            json_output=tmp_path / f"report-{index}.json",
            md_output=tmp_path / f"report-{index}.md",
            review_file=review_file,
            graph_service=_graph_service(),
        )

        assert report["status"] == "accepted"
        assert report["acceptedPatternCount"] == 1
        con = mature_learning.connect(db_path)
        try:
            observation = con.execute(
                "SELECT observation_type, axes FROM research_build_design_observations"
            ).fetchone()
            pattern = con.execute("SELECT pattern_type FROM research_build_patterns").fetchone()
            assert observation["observation_type"] == expected
            assert pattern["pattern_type"] == expected
            axes = json.loads(observation["axes"])
            assert "variant_relations" in axes
            assert "modelability_caveats" in axes
        finally:
            con.close()


def test_deep_review_acceptance_defers_design_axis_as_pattern_type(tmp_path):
    review_file = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        candidate_overrides={
            "patternType": "mechanic_engine",
            "axes": ["mechanic_engine", "itemization"],
        },
    )
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["status"] == "accepted"
    assert report["acceptedPatternCount"] == 0
    assert report["deferredCandidateCount"] == 1
    assert report["deferredCandidates"][0]["reason"] == "invalid_schema"


def test_deep_review_acceptance_uses_reviewed_mapping_for_ambiguous_endpoint(tmp_path):
    review_file = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Spark",
                "componentKey": "skill:SparkPlayer",
                "role": "primary_damage",
                "resolverQuery": "Spark",
            }
        ],
    )
    primary_mapping = _write_mapping(
        tmp_path,
        accepted_stable_key="skill:SparkPlayer",
        candidate_name="Spark",
        candidates=[
            {
                "stableKey": "gem:Spark",
                "nodeType": "skill_gem",
                "sourceRefs": ["fixture:mapping_report_only"],
            },
            {
                "stableKey": "skill:SparkPlayer",
                "nodeType": "active_skill",
                "sourceRefs": ["fixture:mapping_report_only"],
            },
        ],
    )
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        primary_mapping_report=primary_mapping,
        graph_service=_graph_service(),
    )

    assert report["safeArtifactOnly"] is True
    assert report["patternWrite"]["status"] == "accepted"
    assert report["acceptedPatternCount"] == 1
    assert report["deferredCandidateCount"] == 0
    assert report["acceptedPatterns"][0]["componentResolutions"][0]["resolutionSource"] == (
        "reviewed_mapping"
    )
    observations = report["patternWrite"]["observationIds"]
    con = mature_learning.connect(tmp_path / "memory.sqlite")
    try:
        row = con.execute(
            "SELECT components FROM research_build_design_observations WHERE observation_id = ?",
            (observations[0],),
        ).fetchone()
        components = json.loads(row["components"])
        assert components[0]["resolution"]["source_refs"] == ["fixture:deep_review"]
    finally:
        con.close()
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "report.md").exists()


def test_deep_review_acceptance_defers_ambiguous_endpoint_without_reviewed_mapping(tmp_path):
    review_file = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Spark",
                "componentKey": "skill:SparkPlayer",
                "role": "primary_damage",
                "resolverQuery": "Spark",
            }
        ],
    )

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["acceptedPatternCount"] == 0
    assert report["deferredCandidateCount"] == 1
    assert (
        report["deferredCandidates"][0]["reason"] == "ambiguous_endpoint_requires_reviewed_mapping"
    )


def test_deep_review_acceptance_defers_stale_ambiguous_mapping_not_in_resolver(tmp_path):
    review_file = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Spark",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Spark",
            }
        ],
    )
    stale_mapping = _write_mapping(
        tmp_path,
        accepted_stable_key="skill:ResolvedOnlyPlayer",
        candidate_name="Spark",
        candidates=[
            {
                "stableKey": "skill:ResolvedOnlyPlayer",
                "nodeType": "active_skill",
                "sourceRefs": ["fixture:stale_mapping_only"],
            }
        ],
    )
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        primary_mapping_report=stale_mapping,
        graph_service=_graph_service(),
    )

    assert report["acceptedPatternCount"] == 0
    assert report["deferredCandidateCount"] == 1
    assert report["deferredCandidates"][0]["reason"] == (
        "ambiguous_endpoint_not_in_current_resolver_candidates"
    )


def test_deep_review_acceptance_ignores_mapping_without_accepted_candidate(tmp_path):
    review_file = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Spark",
                "componentKey": "skill:SparkPlayer",
                "role": "primary_damage",
                "resolverQuery": "Spark",
            }
        ],
    )
    stale_mapping = _write_mapping(
        tmp_path,
        accepted_stable_key="skill:SparkPlayer",
        candidate_name="Spark",
        candidates=[
            {
                "stableKey": "gem:Spark",
                "nodeType": "skill_gem",
                "sourceRefs": ["fixture:deep_review"],
            }
        ],
    )
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        primary_mapping_report=stale_mapping,
        graph_service=_graph_service(),
    )

    assert report["acceptedPatternCount"] == 0
    assert report["deferredCandidateCount"] == 1
    assert (
        report["deferredCandidates"][0]["reason"] == "ambiguous_endpoint_requires_reviewed_mapping"
    )


def test_deep_review_acceptance_defers_missing_endpoint_and_empty_review(tmp_path):
    missing_review = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Missing Skill",
                "componentKey": "skill:MissingSkillPlayer",
                "role": "primary_damage",
                "resolverQuery": "Missing Skill",
            }
        ],
    )
    missing = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "missing.sqlite",
        json_output=tmp_path / "missing.json",
        md_output=tmp_path / "missing.md",
        review_file=missing_review,
        graph_service=_graph_service(),
    )
    empty_review = _write_review(tmp_path, components=[], filename="empty-review.json")
    empty = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "empty.sqlite",
        json_output=tmp_path / "empty.json",
        md_output=tmp_path / "empty.md",
        review_file=empty_review,
        graph_service=_graph_service(),
    )

    assert missing["acceptedPatternCount"] == 0
    assert missing["deferredCandidates"][0]["reason"] == "source_coverage_gap"
    assert empty["acceptedPatternCount"] == 0
    assert empty["deferredCandidateCount"] == 0


def test_deep_review_acceptance_defers_invalid_candidate_but_accepts_valid_one(tmp_path):
    bad_candidate = {
        "sampleId": "fixture_sample_001",
        "caseRef": "case:fixture-sample-001",
        "safeEvidenceRef": "safe:fixture-sample-001",
        "patternType": "cooccurrence",
        "title": "过强候选",
        "summary": "这是常见组合。",
        "axes": ["primary_skill_package"],
        "components": [
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        "plannerHint": "Treat as advisory only.",
        "verificationGate": "Verify before planner use.",
        "verificationTasks": ["Verify before planner use."],
    }
    good_candidate = {
        **bad_candidate,
        "title": "安全候选",
        "summary": "这是单样本观察。",
    }
    review = {
        "reportId": "phase4-deep-researcher-candidate-review-v1",
        "safeArtifactOnly": True,
        "candidateReviews": [bad_candidate, good_candidate],
    }
    review_file = tmp_path / "mixed-review.json"
    review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["status"] == "accepted"
    assert report["acceptedPatternCount"] == 1
    assert report["deferredCandidateCount"] == 1
    assert report["deferredCandidates"][0]["reason"] == "overclaimed_pattern_confidence"
    assert report["acceptedPatterns"][0]["titleZh"] == "安全候选"


def test_deep_review_acceptance_rejects_mojibake_or_surrogate_text(tmp_path):
    review_file = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        candidate_overrides={
            "title": "Oracle \u6fb6\u6c2d\u59a7\u9473\udcaf damaged text",
        },
    )

    try:
        run_phase4_deep_review_acceptance.accept_deep_review_candidates(
            db_path=tmp_path / "memory.sqlite",
            json_output=tmp_path / "acceptance.json",
            md_output=tmp_path / "acceptance.md",
            review_file=review_file,
            graph_service=_graph_service(),
        )
    except ValueError as exc:
        assert "invalid unicode" in str(exc)
    else:  # pragma: no cover - assertion clarity.
        raise AssertionError("mojibake/surrogate safe review was accepted")


def _write_review(
    tmp_path,
    *,
    components: list[dict[str, str]],
    filename: str = "review.json",
    candidate_overrides: dict[str, object] | None = None,
):
    candidate = {
        "sampleId": "fixture_sample_001",
        "caseRef": "case:fixture-sample-001",
        "safeEvidenceRef": "safe:fixture-sample-001",
        "patternType": "cooccurrence",
        "title": "单例：fixture pattern",
        "summary": "单样本 fixture observation for acceptance gate.",
        "axes": ["primary_skill_package", "modelability_caveats"],
        "components": components,
        "plannerHint": "Treat fixture pattern as advisory only.",
        "verificationGate": "Verify fixture selected skill before planner use.",
        "verificationTasks": ["Verify fixture selected skill before planner use."],
    }
    if candidate_overrides:
        candidate.update(candidate_overrides)
    review = {
        "reportId": "phase4-deep-researcher-candidate-review-v1",
        "safeArtifactOnly": True,
        "candidateReviews": [] if not components else [candidate],
    }
    path = tmp_path / filename
    path.write_text(json.dumps(review, ensure_ascii=True, indent=2), encoding="utf-8")
    return path


def _write_mapping(
    tmp_path,
    *,
    accepted_stable_key: str,
    candidate_name: str,
    candidates: list[dict[str, str]] | None = None,
):
    mapping = {
        "reportId": "phase4-reviewed-endpoint-mapping-v1",
        "safeArtifactOnly": True,
        "snapshotId": "snapshot:deep-review-fixture",
        "reviewItems": [
            {
                "sampleId": "fixture_sample_001",
                "candidateName": candidate_name,
                "acceptedStableKey": accepted_stable_key,
                "reviewStatus": "accepted",
                "resolverStatus": "ambiguous",
                "candidates": candidates
                or [
                    {
                        "stableKey": "gem:Spark",
                        "nodeType": "skill_gem",
                        "sourceRefs": ["fixture:deep_review"],
                    },
                    {
                        "stableKey": "skill:SparkPlayer",
                        "nodeType": "active_skill",
                        "sourceRefs": ["fixture:deep_review"],
                    },
                ],
            }
        ],
    }
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _graph_service() -> gt.GraphQueryService:
    source = pg.GraphSource(
        source_id="fixture:deep_review",
        kind="test_fixture",
        source_file="tests/test_phase4_deep_review_acceptance.py",
    )
    nodes = (
        pg.GraphNode(
            "skill:ResolvedOnlyPlayer", "active_skill", "Resolved Only", (source.source_id,)
        ),
        pg.GraphNode("gem:Spark", "skill_gem", "Spark", (source.source_id,)),
        pg.GraphNode("skill:SparkPlayer", "active_skill", "Spark", (source.source_id,)),
    )
    snapshot = pg.GraphSnapshot(
        snapshot_id="snapshot:deep-review-fixture",
        created_at=datetime(2026, 7, 6, tzinfo=UTC),
        sources=(source,),
        nodes=nodes,
        edges=(),
        aliases=(
            pg.GraphAlias("Resolved Only", "skill:ResolvedOnlyPlayer", (source.source_id,)),
            pg.GraphAlias("Spark", "gem:Spark", (source.source_id,)),
            pg.GraphAlias("Spark", "skill:SparkPlayer", (source.source_id,)),
        ),
    )
    return gt.GraphQueryService.from_snapshot(snapshot)
