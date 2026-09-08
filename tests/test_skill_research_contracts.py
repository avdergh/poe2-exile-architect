"""Client guidance must cover the actual Research acceptance boundaries."""

from __future__ import annotations

import ast
import asyncio
from copy import deepcopy
from pathlib import Path
import re

import pytest

from skill_document_helpers import read_skill_documents
from test_patch_reviews import seeded
from test_research_execution_contract import _decision

from server import main
from server.generation import models
from server.knowledge import research_execution
from server.mcp import knowledge_server


SKILLS = Path(__file__).resolve().parents[1] / "poe-bd-creator-plugin" / "skills"


@pytest.mark.parametrize("decision", ["not_applicable", "tested_and_rejected"])
def test_authoritative_read_contract_includes_optional_records(tmp_path, decision):
    service, source, baseline = seeded(tmp_path)
    optional = deepcopy(source)
    record = optional["deep_research_records"][0]
    record.update(
        record_kind="gear_synergy",
        title="普通胸甲职责备选",
        summary="普通胸甲的可选职责不改变既有核心机制。",
        content="隔离测试记录，用来核对Family必读集合与全部授权包的边界。",
        failure_conditions=[],
        component_keys=["skill:LightningArrowPlayer"],
        component_mentions=record["component_mentions"][:1],
        typed_payload={"gearResponsibilities": [], "gearSubjects": ["body_armour"]},
    )
    added = service.propose_deep_research_records(optional)
    assert added["status"] == "accepted"
    family = baseline["buildFamilyKeys"][0]

    def read(**kwargs):
        result = service.query_research_memory(
            "",
            build_family_keys=[family],
            game_patch="0.5.4",
            passive_tree_version="0_5",
            knowledge_scope="global_seed",
            source_case_ref="case:la-safe",
            response_profile="create_compact",
            **kwargs,
        )
        page = service.start_retrieval_session(
            main._compact_create_research_response(result),
            response_profile="create_compact",
            run_ref=None,
            claim_ref=None,
        )
        assert page["retrieval"]["complete"] is True
        return result, page["dedupeQueryRef"]

    def contract(refs):
        result = research_execution.construct_research_execution_contract(
            authoritative_dedupe_query_refs=refs,
            comparison_dedupe_query_refs=[],
            build_family_key=family,
            selected_knowledge_scope="global_seed",
            selected_source_case_ref="case:la-safe",
            game_patch="0.5.4",
            passive_tree_version="0_5",
            db_path=service.db_path,
        )
        assert result["status"] == "ready"
        return result

    summary, summary_ref = read(detail_level="summary")
    required = sorted(
        {
            record_id
            for coverage in summary["familyRecordCoverage"]
            for record_id in coverage["requiredDeepReadRecordIds"]
        }
    )
    assert set(added["recordIds"]).isdisjoint(required)
    _, required_ref = read(detail_level="record", record_ids=required)
    before = contract([summary_ref, required_ref])
    assert before["contractRules"]["authoritativePackagesRequireDeepRead"] is True
    assert set(added["recordIds"]) <= {package["recordId"] for package in before["packages"]}

    decisions = []
    for package in before["packages"]:
        item = _decision(package["packageId"], adopted=True)
        item["decision"] = (
            decision if package["recordId"] in added["recordIds"] else "not_applicable"
        )
        decisions.append(item)
    plan = models.ResearchExecutionPlan.model_validate(
        {
            "contractRef": before["contractRef"],
            "selectedDesignCaseRef": "case:la-safe",
            "selectedVariantRationale": "This isolated case covers the selected target and preserves one coherent source lane.",
            "coherenceSummary": "Every package receives an explicit decision; the optional equipment duty is rejected without changing the core mechanism.",
            "packageDecisions": decisions,
            "crossCaseMechanismPlans": [],
        }
    ).model_dump(mode="json", by_alias=True)
    rejected, _, _ = research_execution.validate_research_execution_plan(plan, before)
    assert rejected == "research_execution_authoritative_package_not_deep_read"

    _, optional_ref = read(detail_level="record", record_ids=added["recordIds"])
    after = contract([summary_ref, required_ref, optional_ref])
    assert after["contractRef"] == before["contractRef"]
    assert research_execution.validate_research_execution_plan(plan, after)[0] is None
    documents = read_skill_documents(SKILLS / "poe-bd-create")
    assert "authoritativePackagesRequireDeepRead" in documents["references/research-use.md"]


def test_worker_graph_examples_call_registered_mcp_entrypoint():
    worker = (SKILLS / "poe-bd-research-worker" / "SKILL.md").read_text(encoding="utf-8")
    registered = {tool.name for tool in asyncio.run(knowledge_server.mcp.list_tools())}
    operations = set()
    for example in re.findall(r"`(graph_tool_query\([^`]+\))`", worker):
        call = ast.parse(example, mode="eval").body
        assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        assert call.func.id in registered
        arguments = {argument.arg: argument.value for argument in call.keywords}
        assert "payload" in arguments
        operations.add(ast.literal_eval(arguments["tool_name"]))
    assert operations == {"search_graph_components", "resolve_graph_component"}
    assert operations.isdisjoint(registered)


def test_create_entry_and_jewel_stage_retain_call_safety_guards():
    documents = read_skill_documents(SKILLS / "poe-bd-create")
    # Small guardrails complement the executable contracts; they are not a prose-quality score.
    assert "必须串行调用" in documents["SKILL.md"]
    build = documents["references/build-and-refine.md"]
    assert build.index("protected_node_ids") < build.index("evaluate_next_jewel_socket")
