from __future__ import annotations

import hashlib
import json

import pytest

from server.compute import pob_code
from server.knowledge import mature_learning
from scripts import run_phase4_real_research_extraction


RAW_MARKERS = (
    "eNrt",
    "rawXml",
    "rawImportCode",
    "PathOfBuilding",
    "<Build",
    "<Skills",
    "nameSpec",
    "transientPacketPath",
    "transientPromptPath",
)


def _safe_packet_report() -> dict[str, object]:
    return {
        "reportId": "phase4-researcher-e2e-user-pob-v1",
        "status": "ready_for_external_researcher",
        "sampleCount": 2,
        "readyCount": 2,
        "safeArtifactOnly": True,
        "samples": [
            {
                "sampleId": "phase4_user_pob_001",
                "status": "packet_ready",
                "sourceHash": "a" * 64,
                "packetId": "rp-safe-001",
                "packetSafeHash": "b" * 64,
                "safeMetadata": {
                    "case_id": "phase4_user_pob_001",
                    "class": "Monk",
                    "ascendancy": "Martial Artist",
                    "mainSkill": "Hollow Focus",
                    "gamePatch": "0.5.4",
                    "passiveTreeVersion": "0_5",
                    "visibility": "creator_visible",
                    "split": "train_context",
                    "knowledgeScope": "global_seed",
                    "pobModelability": "partial",
                    "lifecycleStage": "unknown_lifecycle",
                },
            },
            {
                "sampleId": "phase4_user_pob_003",
                "status": "packet_ready",
                "sourceHash": "c" * 64,
                "packetId": "rp-safe-003",
                "packetSafeHash": "d" * 64,
                "safeMetadata": {
                    "case_id": "phase4_user_pob_003",
                    "class": "Mercenary",
                    "ascendancy": "Tactician",
                    "mainSkill": "Crossbow Shot",
                    "gamePatch": "0.5.4",
                    "passiveTreeVersion": "0_5",
                    "visibility": "creator_visible",
                    "split": "train_context",
                    "knowledgeScope": "global_seed",
                    "pobModelability": "partial",
                    "lifecycleStage": "unknown_lifecycle",
                },
            },
        ],
    }


def _mapping_report() -> dict[str, object]:
    return {
        "reportId": "phase4-reviewed-endpoint-mapping-v1",
        "status": "partial_endpoint_mapping_accepted",
        "safeArtifactOnly": True,
        "snapshotId": "snapshot:test",
        "reviewItems": [
            {
                "sampleId": "phase4_user_pob_001",
                "candidateName": "Hollow Focus",
                "reviewStatus": "accepted",
                "acceptedStableKey": "skill:HollowFocusPlayer",
            },
            {
                "sampleId": "phase4_user_pob_003",
                "candidateName": "Crossbow Shot",
                "reviewStatus": "pending_manual_review",
                "acceptedStableKey": None,
            },
        ],
    }


def _mapping_report_with_crossbow_accepted() -> dict[str, object]:
    report = _mapping_report()
    report["status"] = "endpoint_mapping_accepted"
    report["reviewItems"][1]["reviewStatus"] = "accepted"  # type: ignore[index]
    report["reviewItems"][1]["acceptedStableKey"] = "skill:MeleeCrossbowPlayer"  # type: ignore[index]
    return report


def _xml_fixture(
    *,
    class_name: str,
    ascendancy: str,
    level: int,
    groups: list[list[tuple[str, str]]],
) -> str:
    skill_xml = []
    for group in groups:
        gem_xml = "".join(
            f'<Gem nameSpec="{name}" skillId="{skill_id}" enabled="true" level="20" />'
            for name, skill_id in group
        )
        skill_xml.append(f'<Skill enabled="true" mainActiveSkill="1">{gem_xml}</Skill>')
    return (
        "<PathOfBuilding2>"
        f'<Build level="{level}" className="{class_name}" ascendClassName="{ascendancy}" '
        'mainSocketGroup="1" />'
        "<Skills><SkillSet>" + "".join(skill_xml) + "</SkillSet></Skills>"
        '<Items><Item id="1" /></Items>'
        "</PathOfBuilding2>"
    )


def _xml_by_sample() -> dict[str, str]:
    return {
        "phase4_user_pob_001": _xml_fixture(
            class_name="Monk",
            ascendancy="Martial Artist",
            level=100,
            groups=[
                [
                    ("Hollow Focus", "HollowFocusPlayer"),
                    ("Cooldown Recovery II", "SupportCooldownRecoveryPlayerTwo"),
                    ("Heightened Charges", "SupportHeightenedChargesPlayer"),
                ],
                [("Barrage", "BarragePlayer"), ("Combat Frenzy", "CombatFrenzyPlayer")],
                [("Herald of Ice", "HeraldOfIcePlayer"), ("Ghost Dance", "GhostDancePlayer")],
            ],
        ),
        "phase4_user_pob_003": _xml_fixture(
            class_name="Mercenary",
            ascendancy="Tactician",
            level=97,
            groups=[
                [
                    ("Crossbow Shot", "MeleeCrossbowPlayer"),
                    ("Cold Attunement", "SupportAddedColdDamagePlayer"),
                ],
                [("Escape Shot", "EscapeShotPlayer"), ("Freeze", "SupportFreezePlayer")],
                [("Herald of Thunder", "HeraldOfThunderPlayer")],
                [("Combat Frenzy", "CombatFrenzyPlayer"), ("Berserk", "BerserkPlayer")],
            ],
        ),
    }


def _proposal_payload(sample_ids: list[str] | None = None) -> dict[str, object]:
    selected = set(sample_ids or ["phase4_user_pob_001", "phase4_user_pob_003"])
    fragments: list[dict[str, object]] = []
    if "phase4_user_pob_001" in selected:
        fragments.append(
            {
                "fragment_type": "mechanism_pattern",
                "title": "外部研究：Hollow Focus 需要冷却和充能节奏",
                "summary": "外部 Researcher 认为该样本的可复用点是冷却窗口、充能来源和防御保留层共同支撑主技能。",
                "reusable_principle": "把 Hollow Focus 放进 planner 前，先验证充能生成、冷却恢复和资源保留是否同时成立。",
                "source_case_refs": ["case:phase4_user_pob_001"],
                "safe_evidence_refs": ["external-proposal:phase4-user-pob-001"],
                "confidence": "medium",
                "copyability_risk": "low",
                "lifecycle_stages": ["endgame_final"],
                "modelability": "partial",
                "verification_tasks": ["用 Judge 复核 selected skill 和冷却窗口。"],
                "component_keys": ["skill:HollowFocusPlayer"],
                "conditions": ["Hollow Focus endpoint 已由人工 mapping 接受。"],
                "risks": ["不要把成熟样本当成 starter 证明。"],
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
            }
        )
    if "phase4_user_pob_003" in selected:
        fragments.append(
            {
                "fragment_type": "mechanism_pattern",
                "title": "外部研究：Crossbow Shot 暂作弹药轮换线索",
                "summary": "外部 Researcher 只把该样本保存为多弹药与 Herald/charge/rage 组合线索，不猜 endpoint。",
                "reusable_principle": "Crossbow Shot endpoint 待审时只能保存 clean fragment，不能写 semantic edge。",
                "source_case_refs": ["case:phase4_user_pob_003"],
                "safe_evidence_refs": ["external-proposal:phase4-user-pob-003"],
                "confidence": "low",
                "copyability_risk": "low",
                "lifecycle_stages": ["endgame_final"],
                "modelability": "partial",
                "verification_tasks": ["先完成人工 endpoint mapping，再考虑 edge。"],
                "component_keys": [],
                "conditions": ["Crossbow Shot endpoint 仍 pending manual review。"],
                "risks": ["猜 stable key 会污染 semantic graph。"],
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
            }
        )
    return {"schema_version": 4, "fragments": fragments, "semantic_edges": []}


def _write_proposal(path, sample_ids: list[str] | None = None) -> None:
    path.write_text(json.dumps(_proposal_payload(sample_ids), ensure_ascii=False), encoding="utf-8")


def _write_payload(path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_real_research_extraction_writes_safe_chinese_fragments(tmp_path):
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    mapping_report = tmp_path / "phase4_reviewed_endpoint_mapping_report.json"
    proposal_file = tmp_path / "external_proposal.json"
    input_report.write_text(json.dumps(_safe_packet_report()), encoding="utf-8")
    mapping_report.write_text(json.dumps(_mapping_report()), encoding="utf-8")
    _write_proposal(proposal_file)

    report = run_phase4_real_research_extraction.build_real_research_extraction_report(
        input_report=input_report,
        endpoint_mapping_report=mapping_report,
        external_proposal_file=proposal_file,
        db_path=tmp_path / "mature.sqlite",
        _source_xml_by_sample_id_for_tests=_xml_by_sample(),
    )

    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert report["safeArtifactOnly"] is True
    assert report["status"] == "real_research_extraction_completed"
    assert report["acceptedFragmentCount"] == 2
    assert report["duplicateFragmentCount"] == 0
    assert report["appendedEvidenceCount"] == 0
    assert report["proposalOrigin"] == "external_clean_proposal"
    assert report["semanticEdgeWrite"]["attempted"] is False
    assert "中文审阅" in report["reviewLanguage"]
    assert report["samples"][0]["extractedFragments"][0]["titleZh"] == (
        "外部研究：Hollow Focus 需要冷却和充能节奏"
    )
    assert report["samples"][1]["semanticEdgeAction"] == "blocked_pending_endpoint_mapping"
    assert not any(marker in serialized for marker in RAW_MARKERS)

    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        rows = con.execute("SELECT fragment_id, component_keys FROM research_fragments").fetchall()
        assert len(rows) == 2
        component_sets = [json.loads(row["component_keys"]) for row in rows]
        assert ["skill:HollowFocusPlayer"] in component_sets
        assert [] in component_sets
    finally:
        con.close()


def test_real_research_extraction_repeated_run_appends_evidence_instead_of_duplication(tmp_path):
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    mapping_report = tmp_path / "phase4_reviewed_endpoint_mapping_report.json"
    proposal_file = tmp_path / "external_proposal.json"
    input_report.write_text(json.dumps(_safe_packet_report()), encoding="utf-8")
    mapping_report.write_text(json.dumps(_mapping_report()), encoding="utf-8")
    _write_proposal(proposal_file)
    kwargs = {
        "input_report": input_report,
        "endpoint_mapping_report": mapping_report,
        "external_proposal_file": proposal_file,
        "db_path": tmp_path / "mature.sqlite",
        "_source_xml_by_sample_id_for_tests": _xml_by_sample(),
    }

    first = run_phase4_real_research_extraction.build_real_research_extraction_report(**kwargs)
    second = run_phase4_real_research_extraction.build_real_research_extraction_report(**kwargs)

    assert first["acceptedFragmentCount"] == 2
    assert second["acceptedFragmentCount"] == 0
    assert second["duplicateFragmentCount"] == 2
    assert second["appendedEvidenceCount"] == 2
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        count = con.execute("SELECT count(*) FROM research_fragments").fetchone()[0]
        assert count == 2
    finally:
        con.close()


def test_real_research_extraction_decodes_pob_code_and_checks_source_hash(tmp_path):
    xml = _xml_fixture(
        class_name="Monk",
        ascendancy="Martial Artist",
        level=100,
        groups=[[("Hollow Focus", "HollowFocusPlayer"), ("Barrage", "BarragePlayer")]],
    )
    code = pob_code.encode_code(xml)
    source_file = tmp_path / "sample.txt"
    source_file.write_text(code, encoding="utf-8")
    proposal_file = tmp_path / "external_proposal.json"
    _write_proposal(proposal_file, ["phase4_user_pob_001"])
    report_payload = _safe_packet_report()
    report_payload["samples"] = [report_payload["samples"][0]]
    report_payload["sampleCount"] = 1
    report_payload["readyCount"] = 1
    report_payload["samples"][0]["sourceHash"] = hashlib.sha256(code.encode()).hexdigest()
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    mapping_report = tmp_path / "phase4_reviewed_endpoint_mapping_report.json"
    input_report.write_text(json.dumps(report_payload), encoding="utf-8")
    mapping_report.write_text(json.dumps(_mapping_report()), encoding="utf-8")

    accepted = run_phase4_real_research_extraction.build_real_research_extraction_report(
        input_report=input_report,
        endpoint_mapping_report=mapping_report,
        external_proposal_file=proposal_file,
        db_path=tmp_path / "mature.sqlite",
        source_files=[source_file],
    )
    report_payload["samples"][0]["sourceHash"] = "f" * 64
    input_report.write_text(json.dumps(report_payload), encoding="utf-8")

    assert accepted["acceptedFragmentCount"] == 1
    try:
        run_phase4_real_research_extraction.build_real_research_extraction_report(
            input_report=input_report,
            endpoint_mapping_report=mapping_report,
            external_proposal_file=proposal_file,
            db_path=tmp_path / "bad.sqlite",
            source_files=[source_file],
        )
    except ValueError as exc:
        assert "source hash mismatch" in str(exc)
    else:
        raise AssertionError("source hash mismatch was accepted")


def test_real_research_extraction_writes_safe_json_and_markdown(tmp_path):
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    mapping_report = tmp_path / "phase4_reviewed_endpoint_mapping_report.json"
    proposal_file = tmp_path / "external_proposal.json"
    output_json = tmp_path / "real_extraction.json"
    output_md = tmp_path / "real_extraction.md"
    input_report.write_text(json.dumps(_safe_packet_report()), encoding="utf-8")
    mapping_report.write_text(json.dumps(_mapping_report()), encoding="utf-8")
    _write_proposal(proposal_file)

    report = run_phase4_real_research_extraction.write_real_research_extraction_report(
        input_report=input_report,
        endpoint_mapping_report=mapping_report,
        external_proposal_file=proposal_file,
        db_path=tmp_path / "mature.sqlite",
        _source_xml_by_sample_id_for_tests=_xml_by_sample(),
        json_output=output_json,
        md_output=output_md,
    )

    markdown = output_md.read_text(encoding="utf-8")
    assert json.loads(output_json.read_text(encoding="utf-8")) == report
    assert "Phase 4 Real Research Extraction" in markdown
    assert "中文机制摘录" in markdown
    assert "Hollow Focus" in markdown
    assert "Crossbow Shot" in markdown
    assert not any(marker in markdown for marker in RAW_MARKERS)


def test_real_research_extraction_rejects_unaccepted_component_key(tmp_path):
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    mapping_report = tmp_path / "phase4_reviewed_endpoint_mapping_report.json"
    proposal_file = tmp_path / "external_proposal.json"
    input_report.write_text(json.dumps(_safe_packet_report()), encoding="utf-8")
    mapping_report.write_text(json.dumps(_mapping_report()), encoding="utf-8")
    payload = _proposal_payload(["phase4_user_pob_003"])
    payload["fragments"][0]["component_keys"] = ["skill:MeleeCrossbowPlayer"]  # type: ignore[index]
    _write_payload(proposal_file, payload)

    with pytest.raises(ValueError, match="outside accepted mapping"):
        run_phase4_real_research_extraction.build_real_research_extraction_report(
            input_report=input_report,
            endpoint_mapping_report=mapping_report,
            external_proposal_file=proposal_file,
            db_path=tmp_path / "mature.sqlite",
            _source_xml_by_sample_id_for_tests=_xml_by_sample(),
        )


def test_real_research_extraction_requires_component_key_for_accepted_endpoint(tmp_path):
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    mapping_report = tmp_path / "phase4_reviewed_endpoint_mapping_report.json"
    proposal_file = tmp_path / "external_proposal.json"
    input_report.write_text(json.dumps(_safe_packet_report()), encoding="utf-8")
    mapping_report.write_text(
        json.dumps(_mapping_report_with_crossbow_accepted()),
        encoding="utf-8",
    )
    _write_proposal(proposal_file, ["phase4_user_pob_003"])

    with pytest.raises(ValueError, match="accepted endpoint mapping"):
        run_phase4_real_research_extraction.build_real_research_extraction_report(
            input_report=input_report,
            endpoint_mapping_report=mapping_report,
            external_proposal_file=proposal_file,
            db_path=tmp_path / "mature.sqlite",
            _source_xml_by_sample_id_for_tests=_xml_by_sample(),
        )


def test_real_research_extraction_accepts_crossbow_after_endpoint_backfill(tmp_path):
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    mapping_report = tmp_path / "phase4_reviewed_endpoint_mapping_report.json"
    proposal_file = tmp_path / "external_proposal.json"
    input_report.write_text(json.dumps(_safe_packet_report()), encoding="utf-8")
    mapping_report.write_text(
        json.dumps(_mapping_report_with_crossbow_accepted()),
        encoding="utf-8",
    )
    payload = _proposal_payload(["phase4_user_pob_003"])
    payload["fragments"][0]["component_keys"] = ["skill:MeleeCrossbowPlayer"]  # type: ignore[index]
    payload["fragments"][0]["conditions"] = ["Crossbow Shot endpoint 已确认。"]  # type: ignore[index]
    payload["fragments"][0]["reusable_principle"] = (  # type: ignore[index]
        "Crossbow Shot 可以作为已确认 endpoint 的弹药轮换线索进入 semantic gate。"
    )
    _write_payload(proposal_file, payload)

    report = run_phase4_real_research_extraction.build_real_research_extraction_report(
        input_report=input_report,
        endpoint_mapping_report=mapping_report,
        external_proposal_file=proposal_file,
        db_path=tmp_path / "mature.sqlite",
        _source_xml_by_sample_id_for_tests=_xml_by_sample(),
    )

    assert report["acceptedFragmentCount"] == 1
    sample = next(item for item in report["samples"] if item["sampleId"] == "phase4_user_pob_003")
    assert sample["acceptedStableKey"] == "skill:MeleeCrossbowPlayer"
    assert sample["semanticEdgeAction"] == "ready_for_future_semantic_proposal_gate"
    assert sample["extractedFragments"][0]["componentKeys"] == ["skill:MeleeCrossbowPlayer"]


def test_real_research_extraction_rejects_semantic_edges_in_fragment_harness(tmp_path):
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    mapping_report = tmp_path / "phase4_reviewed_endpoint_mapping_report.json"
    proposal_file = tmp_path / "external_proposal.json"
    input_report.write_text(json.dumps(_safe_packet_report()), encoding="utf-8")
    mapping_report.write_text(json.dumps(_mapping_report()), encoding="utf-8")
    payload = _proposal_payload(["phase4_user_pob_001"])
    payload["semantic_edges"] = [
        {
            "source_key": "skill:HollowFocusPlayer",
            "target_key": "skill:HollowFocusPlayer",
            "source_resolution": {
                "tool_name": "resolve_graph_component",
                "status": "resolved",
                "stable_key": "skill:HollowFocusPlayer",
                "snapshot_id": "snapshot:test",
                "evidence_path_nodes": ["skill:HollowFocusPlayer"],
                "source_refs": ["repoe:skills"],
            },
            "target_resolution": {
                "tool_name": "resolve_graph_component",
                "status": "resolved",
                "stable_key": "skill:HollowFocusPlayer",
                "snapshot_id": "snapshot:test",
                "evidence_path_nodes": ["skill:HollowFocusPlayer"],
                "source_refs": ["repoe:skills"],
            },
            "edge_type": "has_modelability_caveat",
            "rationale": "Safe edge fixture that must use the semantic gate, not this fragment harness.",
            "source_case_refs": ["case:phase4_user_pob_001"],
            "safe_evidence_refs": ["external-proposal:phase4-user-pob-001-edge"],
            "game_patch": "0.5.4",
            "passive_tree_version": "0_5",
            "pob_version_or_commit": "unknown",
            "status": "valid",
            "confidence": "medium",
            "modelability": "partial",
            "copy_safety_state": "passed",
            "context_requirements": [
                {"context_type": "lifecycle_stage_requirement", "stages": ["endgame_final"]}
            ],
            "affected_component_keys": ["skill:HollowFocusPlayer"],
            "visibility": "creator_visible",
            "split": "train_context",
            "knowledge_scope": "global_seed",
            "directionality": "directional",
        }
    ]
    _write_payload(proposal_file, payload)

    with pytest.raises(ValueError, match="fragments only"):
        run_phase4_real_research_extraction.build_real_research_extraction_report(
            input_report=input_report,
            endpoint_mapping_report=mapping_report,
            external_proposal_file=proposal_file,
            db_path=tmp_path / "mature.sqlite",
            _source_xml_by_sample_id_for_tests=_xml_by_sample(),
        )


def test_real_research_extraction_rejects_full_gem_link_like_proposal_text(tmp_path):
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    mapping_report = tmp_path / "phase4_reviewed_endpoint_mapping_report.json"
    proposal_file = tmp_path / "external_proposal.json"
    input_report.write_text(json.dumps(_safe_packet_report()), encoding="utf-8")
    mapping_report.write_text(json.dumps(_mapping_report()), encoding="utf-8")
    payload = _proposal_payload(["phase4_user_pob_001"])
    payload["fragments"][0]["summary"] = (  # type: ignore[index]
        "Spark -> Fork -> Pierce -> Cold Attunement -> Scattershot is a full link."
    )
    _write_payload(proposal_file, payload)

    with pytest.raises(ValueError, match="copy-safety"):
        run_phase4_real_research_extraction.build_real_research_extraction_report(
            input_report=input_report,
            endpoint_mapping_report=mapping_report,
            external_proposal_file=proposal_file,
            db_path=tmp_path / "mature.sqlite",
            _source_xml_by_sample_id_for_tests=_xml_by_sample(),
        )


def test_real_research_extraction_rejects_full_gem_link_like_safe_evidence_ref(tmp_path):
    input_report = tmp_path / "phase4_researcher_e2e_report.json"
    mapping_report = tmp_path / "phase4_reviewed_endpoint_mapping_report.json"
    proposal_file = tmp_path / "external_proposal.json"
    input_report.write_text(json.dumps(_safe_packet_report()), encoding="utf-8")
    mapping_report.write_text(json.dumps(_mapping_report()), encoding="utf-8")
    payload = _proposal_payload(["phase4_user_pob_001"])
    payload["fragments"][0]["safe_evidence_refs"] = [  # type: ignore[index]
        "Spark -> Fork -> Pierce -> Cold Attunement -> Scattershot"
    ]
    _write_payload(proposal_file, payload)

    with pytest.raises(ValueError, match="safe ref token"):
        run_phase4_real_research_extraction.build_real_research_extraction_report(
            input_report=input_report,
            endpoint_mapping_report=mapping_report,
            external_proposal_file=proposal_file,
            db_path=tmp_path / "mature.sqlite",
            _source_xml_by_sample_id_for_tests=_xml_by_sample(),
        )
