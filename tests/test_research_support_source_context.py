from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from scripts import run_phase4_deep_review_acceptance as acceptance
from server.knowledge import graph_tools as gt, physical_graph as pg


SUPPORTS = {
    "Damage": "support:Metadata/Items/Gem/SupportFixtureDamage",
    "Host": "support:Metadata/Items/Gem/SupportFixtureHost",
    "Minion": "support:Metadata/Items/Gem/SupportFixtureMinion",
}


def graph(*, payload_known=True):
    source = pg.GraphSource(source_id="fixture:source-context", kind="test_fixture", source_file="fixture")
    types = {
        "skill:MinionPlayer": ["Minion", "CreatesMinion"],
        "skill:HostPlayer": ["Meta"],
        "skill:PayloadAPlayer": ["Buff"],
        "skill:PayloadBPlayer": ["Damage", "Spell"],
    }
    nodes = [pg.GraphNode(key, "active_skill", key.removeprefix("skill:"), (source.source_id,))
             for key in types]
    edges, facts = [], []
    for name in {value for values in types.values() for value in values}:
        nodes.append(pg.GraphNode("skill_type:" + name.lower(), "skill_type", name, (source.source_id,)))
    for key, values in types.items():
        edges.extend(pg.GraphEdge("has_type", key, "skill_type:" + value.lower(), (source.source_id,))
                     for value in values)
    for name, key in SUPPORTS.items():
        effect = "skill:SupportFixture" + name
        nodes.extend([pg.GraphNode(key, "support_gem", name, (source.source_id,)),
                      pg.GraphNode(effect, "active_skill", effect, (source.source_id,))])
        edges.append(pg.GraphEdge("grants_skill", key, effect, (source.source_id,)))
        facts.append(pg.RequirementFact(component_key=effect, level_or_stage="support_contract",
            requirements={"allowed_types_expr": [{"Host": "Meta", "Minion": "CreatesMinion"}.get(name, name)],
                          "excluded_types_expr": [], "supports_gems_only": False, "added_types": []},
            source_refs=(source.source_id,)))
        facts.append(pg.RequirementFact(component_key=effect, level_or_stage="pob_support_flags",
            requirements={"ignore_minion_types": False}, source_refs=(source.source_id,)))
    if payload_known:
        facts.append(pg.RequirementFact(component_key="skill:MinionPlayer", level_or_stage="minion_payload_types",
            requirements={"endpoint_kind": "minion_payload", "skill_types": ["Damage", "Spell"]},
            source_refs=(source.source_id,)))
    return gt.GraphQueryService(pg.GraphSnapshot(snapshot_id="snapshot:source-context",
        created_at=datetime(2026, 9, 14, tzinfo=UTC), sources=(source,), nodes=tuple(nodes),
        edges=tuple(edges), requirement_facts=tuple(facts), aliases=()))


def group(ref, *, root="HostPlayer", payload=None, supports=("Damage",)):
    root_ref = ref + ":root:1"
    active = [{"name": root, "skillId": root, "enabled": True}]
    if payload:
        active.append({"name": payload, "skillId": payload, "enabled": True,
                       "socketedUnderSkillRef": root_ref})
    return {"groupRef": ref, "rootSkillRef": root_ref, "rootSkill": active[0], "activeSkills": active,
            "supports": [{"name": name, "gemId": SUPPORTS[name].removeprefix("support:"),
                "socketedItemRef": ref + ":socketed:" + str(index + 2),
                "enableGlobal1": True, "enableGlobal2": True,
                "socketedUnderSkillRef": root_ref} for index, name in enumerate(supports)]}


def package(source):
    return {"skillKey": "skill:" + source["rootSkill"]["skillId"],
            "supportKeys": ["support:" + item["gemId"] for item in source["supports"]],
            "sourceGroupRef": source["groupRef"], "rootSkillRef": source["rootSkillRef"],
            "socketedItemRefs": [item["socketedItemRef"] for item in source["supports"]],
            "deliveryRole": "direct"}


def filter_package(service, manifest, value):
    record = {"component_keys": [value["skillKey"], *value["supportKeys"]],
              "typed_payload": {"supportPackages": [value]}}
    summary = {"titleZh": "来源包", "recordKind": "skill_package", "sampleId": "fixture",
               "componentKeys": record["component_keys"], "typedPayload": record["typed_payload"]}
    return acceptance._filter_records_with_unsupported_structured_support_packages(
        graph_service=service, source_skill_manifest=manifest,
        deep_payload={"schema_version": 6, "deep_research_records": [record]}, accepted_records=[summary])


def test_source_and_structured_share_minion_context():
    service = graph()
    source = group("group:1", root="MinionPlayer", supports=("Minion", "Damage"))
    manifest = {"activeSkillGroups": [source]}
    diagnostic = acceptance._source_support_compatibility_diagnostics(graph_service=service,
        source_skill_manifest=manifest, source_skill_resolutions={"minionplayer": {"componentKey": "skill:MinionPlayer"}})
    assert diagnostic["sourceSupportCompatibilityCheckedPairCount"] == 2
    assert diagnostic["unsupportedSourceSupportPairCount"] == diagnostic["unverifiedSourceSupportPairCount"] == 0
    _, summaries, deferred = filter_package(service, manifest, package(source))
    assert not deferred and len(summaries) == 1
    proof = acceptance._support_compatibility_summary(summaries, service)
    assert proof["contractVersion"] == pg.SUPPORT_COMPATIBILITY_VERSION
    assert proof["applicationVerified"] is False


def test_missing_minion_context_is_unknown_not_incompatibility():
    service = graph(payload_known=False)
    source = group("group:1", root="MinionPlayer")
    manifest = {"activeSkillGroups": [source]}
    diagnostic = acceptance._source_support_compatibility_diagnostics(graph_service=service,
        source_skill_manifest=manifest, source_skill_resolutions={"minionplayer": {"componentKey": "skill:MinionPlayer"}})
    assert diagnostic["unsupportedSourceSupportPairCount"] == 0
    assert diagnostic["unverifiedSourceSupportPairCount"] == 1
    _, _, deferred = filter_package(service, manifest, package(source))
    assert deferred[0]["reason"] == "unverified_structured_skill_support_pair"


def test_same_root_cannot_borrow_sibling_container_payload():
    first = group("group:A", payload="PayloadAPlayer")
    second = group("group:B", payload="PayloadBPlayer")
    manifest = {"activeSkillGroups": [first, second]}
    service = graph()
    _, _, rejected = filter_package(service, manifest, package(first))
    assert rejected[0]["reason"] == "unsupported_structured_skill_support_pair"
    assert all("skill:PayloadBPlayer" not in pair["evaluatedSkillKeys"] for pair in rejected[0]["unsupportedPairs"])
    _, kept, rejected = filter_package(service, manifest, package(second))
    assert not rejected and len(kept) == 1
    with pytest.raises(ValueError, match="ambiguous"):
        acceptance._source_socket_package_skill_keys(source_skill_manifest=manifest,
            root_skill_key="skill:HostPlayer", support_keys=[SUPPORTS["Damage"]])


@pytest.mark.parametrize("field,value", [("rootSkillRef", "other:root"),
    ("socketedItemRefs", ["other:socket"]), ("sourceGroupRef", "other:group")])
def test_stale_container_binding_fails_closed(field, value):
    source = group("group:1", payload="PayloadBPlayer")
    supplied = package(source)
    supplied[field] = value
    _, kept, deferred = filter_package(graph(), {"activeSkillGroups": [source]}, supplied)
    assert not kept and deferred[0]["reason"] == "invalid_source_support_binding"


def test_full_types_and_matched_subset_are_distinct():
    source = group("group:1", payload="PayloadAPlayer")
    _, _, deferred = filter_package(graph(), {"activeSkillGroups": [source]}, package(source))
    pair = next(pair for pair in deferred[0]["unsupportedPairs"] if pair["endpointKey"] == "skill:PayloadAPlayer")
    assert pair["endpointSkillTypes"] == ["buff"]
    assert pair["matchedSkillTypes"] == []


def test_payload_core_coverage_uses_exact_host_package_without_fake_child_package():
    source = group("group:1", payload="PayloadBPlayer", supports=("Host", "Damage"))
    manifest = {"activeSkillGroups": [source]}
    record = {"researchGroupId": "research:fixture", "recordKind": "skill_package",
        "components": [{"componentKey": "skill:HostPlayer", "role": "trigger_host"},
                       {"componentKey": "skill:PayloadBPlayer", "role": "triggered_payload"}],
        "typedPayload": {"supportPackages": [package(source)]}}
    assert acceptance._support_packages_cover_core_skill_groups([record], source_skill_manifest=manifest)
    wrong = deepcopy(manifest)
    wrong["activeSkillGroups"][0]["activeSkills"][1]["socketedUnderSkillRef"] = "other:root"
    assert acceptance._core_skill_group_support_gaps([record], source_skill_manifest=wrong) == ["skill:PayloadBPlayer"]


def test_v3_same_skill_groups_cannot_borrow_support_instances_for_coverage():
    first = group("group:A", root="MinionPlayer", supports=("Minion", "Damage"))
    second = group("group:B", root="MinionPlayer", supports=("Minion", "Damage"))
    manifest = {"activeSkillGroups": [first, second]}
    record = {"title": "来源包", "recordKind": "skill_package", "researchGroupId": "research:fixture",
        "sampleId": "fixture", "caseRef": "source:fixture", "safeEvidenceRefs": ["evidence:fixture"],
        "summary": "物理实例覆盖", "content": "同名技能容器需要各自的辅助实例。",
        "components": [{"candidateName": "MinionPlayer", "componentKey": "skill:MinionPlayer", "role": "primary_damage"}],
        "typedPayload": {"supportPackages": [package(first)]}}
    review = {"safeArtifactOnly": True, "reviewContractVersion": "phase4-safe-review-v3", "deepResearchRecords": [record],
        "sourceSkillGroupReviews": [{"groupRef": item["groupRef"], "researchDisposition": "represented",
            "supportDisposition": "packaged", "affectedRecords": [record["title"]], "reason": "observed"}
            for item in (first, second)]}
    result = acceptance._source_skill_evidence_diagnostics(review=review, accepted_records=[record],
        source_skill_manifest=manifest, graph_service=graph(),
        source_skill_resolutions={"minionplayer": {"componentKey": "skill:MinionPlayer"}})
    states = {row["groupRef"]: row["disposition"] for row in result["skillGroupDispositions"]}
    assert states == {"group:A": "packaged", "group:B": "partially_packaged"}


def test_bindings_survive_validation_then_are_removed_from_durable_projection():
    source = group("group:1", root="MinionPlayer", supports=("Minion", "Damage"))
    original = {"supportPackages": [package(source)]}
    canonical, issues = acceptance._canonicalize_typed_payload_references(typed_payload=original,
        component_mentions=[], source_skill_manifest={"activeSkillGroups": [source]},
        require_source_bindings=True, preserve_source_bindings=True)
    assert not issues and canonical["supportPackages"][0]["socketedItemRefs"] == original["supportPackages"][0]["socketedItemRefs"]
    payload = {"deep_research_records": [{"typed_payload": canonical}]}
    clean = acceptance._without_source_support_bindings(payload)
    assert set(clean["deep_research_records"][0]["typed_payload"]["supportPackages"][0]) == {"skillKey", "supportKeys", "deliveryRole"}
    assert payload["deep_research_records"][0]["typed_payload"] == canonical


def test_record_builder_retains_only_validated_source_bindings_until_final_projection():
    source = group("group:1", root="MinionPlayer", supports=("Minion", "Damage"))
    service = graph()
    value = package(source)
    mentions = [{"candidateName": "MinionPlayer", "componentKey": "skill:MinionPlayer",
                 "resolverQuery": "skill:MinionPlayer", "role": "primary_damage"}]
    mentions.extend({"candidateName": name, "componentKey": key, "resolverQuery": key,
                     "role": "support_modifier"} for name, key in SUPPORTS.items() if key in value["supportKeys"])
    review = {"safeArtifactOnly": True, "reviewContractVersion": "phase4-safe-review-v3",
        "deepResearchRecords": [{"sampleId": "fixture", "researchGroupId": "research:fixture",
            "caseRef": "case:fixture", "safeEvidenceRefs": ["evidence:fixture"],
            "recordKind": "skill_package", "title": "实际容器", "summary": "辅助作用于根与负载。",
            "content": "根技能的辅助须保留实际物理归属。", "components": mentions,
            "typedPayload": {"supportPackages": [value], "supportCompatibility": {"contractVersion": "forged"}}}]}
    payload, summaries, deferred = acceptance._build_deep_record_payload(graph_service=service,
        review=review, reviewed_mappings={}, confirmed_review_components={}, source_skill_resolutions={},
        source_skill_manifest={"activeSkillGroups": [source]},
        version_context={"gamePatch": "0.5.5", "passiveTreeVersion": "0_5", "pobVersionOrCommit": "fixture"})
    assert not deferred and len(summaries) == 1
    actual = payload["deep_research_records"][0]["typed_payload"]
    assert actual["supportPackages"][0]["sourceGroupRef"] == source["groupRef"]
    assert "supportCompatibility" not in actual
    clean = acceptance._without_source_support_bindings(payload)
    assert "sourceGroupRef" not in clean["deep_research_records"][0]["typed_payload"]["supportPackages"][0]


@pytest.mark.parametrize("lineage", [True, False, None])
def test_lineage_identity_uses_exact_corpus_fact_independent_of_prose(monkeypatch, lineage):
    from server.knowledge import db
    gem_id = "Metadata/Items/Gem/SupportFixtureIdentity"
    monkeypatch.setattr(db, "get_gem", lambda query: {"id": gem_id, "name": "同名辅助", "is_lineage": lineage}
                        if query == gem_id else None)
    manifest = {"activeSkillGroups": [{"supports": [{"name": "同名辅助", "gemId": gem_id}]}]}
    results = [acceptance._unique_gem_diagnostics({"deepResearchRecords": [{"content": text}]}, manifest)
               for text in ("普通说明", "unique lineage", "并非暗金辅助")]
    assert results[0] == results[1] == results[2]
    assert results[0]["gemIdentityResolutions"][0]["isLineage"] is lineage
    assert results[0]["unlabeledUniqueGemNames"] == []


def test_missing_unique_looking_id_cannot_borrow_same_name_identity(monkeypatch):
    from server.knowledge import db
    monkeypatch.setattr(db, "get_gem", lambda query: {"id": "other-id", "name": "同名", "is_lineage": True})
    result = acceptance._unique_gem_diagnostics({}, {"activeSkillGroups": [{"supports": [
        {"name": "同名", "gemId": "Metadata/Items/Gem/SkillGemUniqueMissing"}]}]})
    assert not result["uniqueGemCandidates"]
    assert result["gemIdentityResolutions"][0]["identityStatus"] == "unknown"


@pytest.mark.parametrize("on_payload", [False, True])
def test_expansion_is_bound_to_exact_gem_instance_not_every_granting_gem(on_payload):
    service = graph()
    snapshot = service.snapshot
    observed = "PayloadAPlayer" if on_payload else "HostPlayer"
    gem_a = "gem:Metadata/Items/Gem/FixtureA"
    gem_b = "gem:Metadata/Items/Gem/FixtureB"
    service = gt.GraphQueryService(replace(snapshot,
        nodes=(*snapshot.nodes,
            pg.GraphNode(gem_a, "skill_gem", "同名", ("fixture:source-context",)),
            pg.GraphNode(gem_b, "skill_gem", "同名", ("fixture:source-context",))),
        edges=(*snapshot.edges, *[edge for gem, effect in (
            (gem_a, "skill:" + observed), (gem_b, "skill:" + observed),
            (gem_b, "skill:PayloadBPlayer")) for edge in (
                pg.GraphEdge("grants_skill", gem, effect, ("fixture:source-context",)),
                pg.GraphEdge("granted_by", effect, gem, ("fixture:source-context",)))])))
    source = group("group:A", payload=observed if on_payload else None)
    instance = source["activeSkills"][-1]
    instance.update(enableGlobal1=True, enableGlobal2=True)
    instance["gemId"] = gem_a.removeprefix("gem:")
    manifest = {"activeSkillGroups": [source]}
    _, kept, deferred = filter_package(service, manifest, package(source))
    assert not kept and deferred[0]["reason"] == "unsupported_structured_skill_support_pair"
    assert all("skill:PayloadBPlayer" not in pair["evaluatedSkillKeys"] for pair in deferred[0]["unsupportedPairs"])
    diagnostic = acceptance._source_support_compatibility_diagnostics(graph_service=service,
        source_skill_manifest=manifest, source_skill_resolutions={"hostplayer": {"componentKey": "skill:HostPlayer"}})
    assert diagnostic["unsupportedSourceSupportPairCount"] == 1
    instance["gemId"] = gem_b.removeprefix("gem:")
    _, kept, deferred = filter_package(service, manifest, package(source))
    assert len(kept) == 1 and not deferred
    assert "skill:PayloadBPlayer" in kept[0]["_supportCompatibility"][0]["matchedEndpointKeys"]
    instance.pop("gemId")
    _, kept, deferred = filter_package(service, manifest, package(source))
    assert not kept and deferred[0]["reason"] == "unsupported_structured_skill_support_pair"
    instance["gemId"] = "Metadata/Items/Gem/MissingSameName"
    _, kept, deferred = filter_package(service, manifest, package(source))
    assert not kept and deferred[0]["reason"] == "invalid_source_support_binding"


def test_item_effect_without_gem_id_does_not_infer_even_one_granting_gem():
    service = graph()
    snapshot = service.snapshot
    gem = "gem:Metadata/Items/Gem/OnlyGem"
    service = gt.GraphQueryService(replace(snapshot,
        nodes=(*snapshot.nodes, pg.GraphNode(gem, "skill_gem", "Only", ("fixture:source-context",))),
        edges=(*snapshot.edges, *[edge for effect in ("skill:HostPlayer", "skill:PayloadBPlayer")
            for edge in (pg.GraphEdge("grants_skill", gem, effect, ("fixture:source-context",)),
                         pg.GraphEdge("granted_by", effect, gem, ("fixture:source-context",)))])))
    source = group("group:A")
    source["rootSkill"]["nameSource"] = "internal_id"
    _, kept, deferred = filter_package(service, {"activeSkillGroups": [source]}, package(source))
    assert not kept and deferred[0]["reason"] == "unsupported_structured_skill_support_pair"
    assert acceptance._active_gem_endpoint_keys(snapshot=service.snapshot, skill_key="skill:HostPlayer") == ["skill:HostPlayer"]


def test_single_support_exception_cannot_waive_other_container_with_same_root():
    first = group("group:A", root="MinionPlayer", supports=("Minion",))
    second = group("group:B", root="MinionPlayer", supports=("Minion", "Damage"))
    record = {"sampleId": "fixture", "caseRef": "case:fixture", "safeEvidenceRefs": ["evidence:fixture"],
        "researchGroupId": "research:fixture", "recordKind": "skill_package", "title": "来源例外",
        "summary": "A仅一颗来源辅助。", "content": "单辅助例外不授权其他容器。",
        "components": [{"candidateName": "MinionPlayer", "componentKey": "skill:MinionPlayer", "role": "primary_damage"}],
        "typedPayload": {"supportPackages": [package(first)], "supportCoverageExceptions": [
            {"skillKey": "skill:MinionPlayer", "reason": "not_applicable", "detail": "A has one support."}]}}
    declared = [{"groupRef": source["groupRef"], "researchDisposition": "represented",
        "supportDisposition": "packaged" if source is first else "not_applicable",
        "affectedRecords": [record["title"]], "reason": "Observed."} for source in (first, second)]
    review = {"safeArtifactOnly": True, "reviewContractVersion": "phase4-safe-review-v3",
        "deepResearchRecords": [record], "sourceSkillGroupReviews": declared}
    manifest = {"activeSkillGroups": [first, second]}
    diagnostics = acceptance._source_skill_evidence_diagnostics(review=review, accepted_records=[record],
        source_skill_manifest=manifest, graph_service=graph(), source_skill_resolutions={})
    states = {row["groupRef"]: row["disposition"] for row in diagnostics["skillGroupDispositions"]}
    assert states == {"group:A": "packaged", "group:B": "support_exception_missing"}
    coverage, _ = acceptance._evaluate_case_coverage(review=review, accepted_records=[record],
        graph_service=graph(), source_evidence_diagnostics=diagnostics, source_skill_manifest=manifest)
    assert coverage["supports"] == "evidence_missing"
    # The original single-container exception remains usable.
    assert acceptance._support_packages_cover_core_skill_groups([record],
        source_skill_manifest={"activeSkillGroups": [first]}, source_group_reviews=declared, graph_service=graph())
    ambiguous = deepcopy(record)
    ambiguous["typedPayload"].pop("supportPackages")
    assert acceptance._source_exception_group_refs(exception=ambiguous["typedPayload"]["supportCoverageExceptions"][0],
        record=ambiguous, source_skill_manifest=manifest, source_group_reviews=declared, graph_service=graph()) == set()


def test_reverse_order_packages_keep_source_evidence_and_dedupe_only_for_storage():
    first = group("group:A", root="MinionPlayer", supports=("Minion", "Damage"))
    second = group("group:B", root="MinionPlayer", supports=("Damage", "Minion"))
    manifest = {"activeSkillGroups": [first, second]}
    canonical, issues = acceptance._canonicalize_typed_payload_references(
        typed_payload={"supportPackages": [package(first), package(second)]}, component_mentions=[],
        source_skill_manifest=manifest, require_source_bindings=True, preserve_source_bindings=True)
    assert not issues and len(canonical["supportPackages"]) == 2
    record = {"component_keys": ["skill:MinionPlayer", SUPPORTS["Minion"], SUPPORTS["Damage"]], "typed_payload": canonical}
    summary = {"titleZh": "两组证据", "recordKind": "skill_package", "sampleId": "fixture",
               "componentKeys": record["component_keys"]}
    payload, summaries, deferred = acceptance._filter_records_with_unsupported_structured_support_packages(
        graph_service=graph(), source_skill_manifest=manifest,
        deep_payload={"deep_research_records": [record]}, accepted_records=[summary])
    assert not deferred and len(summaries[0]["_supportCompatibility"]) == 2
    clean = acceptance._without_source_support_bindings(payload)
    assert len(clean["deep_research_records"][0]["typed_payload"]["supportPackages"]) == 1
    assert len(payload["deep_research_records"][0]["typed_payload"]["supportPackages"]) == 2


def grant_graph(*, chained=False, cyclic=False, shared_child=False):
    snapshot = graph().snapshot
    source = ("fixture:source-context",)
    grants = [(SUPPORTS["Host"], "skill:PayloadBPlayer")]
    if chained or cyclic:
        grants.append((SUPPORTS["Damage"], "skill:MinionPlayer"))
    if shared_child:
        grants.append((SUPPORTS["Minion"], "skill:PayloadBPlayer"))
    children = {child for _, child in grants}
    facts = list(snapshot.requirement_facts)
    if cyclic or shared_child:
        changed_key = "skill:SupportFixtureHost" if cyclic else "skill:SupportFixtureMinion"
        changed_type = "CreatesMinion" if cyclic else "Meta"
        facts = [replace(fact, requirements={**fact.requirements, "allowed_types_expr": [changed_type]})
                 if fact.component_key == changed_key and fact.level_or_stage == "support_contract"
                 else fact for fact in facts]
    return gt.GraphQueryService(replace(snapshot,
        nodes=(*snapshot.nodes, pg.GraphNode("skill_type:skillgrantedbysupport", "skill_type",
                                            "SkillGrantedBySupport", source)),
        edges=(*snapshot.edges,
               *(pg.GraphEdge("grants_skill", owner, child, source) for owner, child in grants),
               *(pg.GraphEdge("has_type", child, "skill_type:skillgrantedbysupport", source)
                 for child in children)),
        requirement_facts=tuple(facts)))


def test_support_child_requires_a_selected_independently_usable_grantor():
    service = grant_graph()
    source = group("group:grant", supports=("Host", "Damage"))
    manifest = {"activeSkillGroups": [source]}
    _, kept, deferred = filter_package(service, manifest, package(source))
    assert len(kept) == 1 and not deferred
    assert "skill:PayloadBPlayer" in kept[0]["_supportCompatibility"][0]["matchedEndpointKeys"]
    diagnostic = acceptance._source_support_compatibility_diagnostics(graph_service=service,
        source_skill_manifest=manifest, source_skill_resolutions={"hostplayer": {"componentKey": "skill:HostPlayer"}})
    assert diagnostic["unsupportedSourceSupportPairCount"] == diagnostic["unverifiedSourceSupportPairCount"] == 0
    # A grantor elsewhere in the source group cannot make a reduced package self-sufficient.
    without_owner = package(source)
    without_owner["supportKeys"] = [SUPPORTS["Damage"]]
    without_owner["socketedItemRefs"] = [source["supports"][1]["socketedItemRef"]]
    _, kept, deferred = filter_package(service, manifest, without_owner)
    assert not kept and deferred[0]["reason"] == "unsupported_structured_skill_support_pair"
    wrong_root = group("group:wrong", root="PayloadAPlayer", supports=("Host", "Damage"))
    _, kept, deferred = filter_package(service, {"activeSkillGroups": [wrong_root]}, package(wrong_root))
    assert not kept and deferred[0]["reason"] == "unsupported_structured_skill_support_pair"


def test_support_grants_follow_rooted_multilevel_chain_but_not_a_cycle():
    source = group("group:chain", supports=("Host", "Damage", "Minion"))
    _, kept, deferred = filter_package(grant_graph(chained=True), {"activeSkillGroups": [source]}, package(source))
    assert len(kept) == 1 and not deferred
    _, kept, deferred = filter_package(grant_graph(cyclic=True), {"activeSkillGroups": [source]}, package(source))
    assert not kept and deferred[0]["reason"] == "unsupported_structured_skill_support_pair"


def test_support_child_cannot_be_declared_as_an_independent_source_root():
    source = group("group:unrooted", root="PayloadBPlayer", supports=("Damage",))
    _, kept, deferred = filter_package(grant_graph(), {"activeSkillGroups": [source]}, package(source))
    assert not kept and deferred[0]["reason"] == "unverified_structured_skill_support_pair"


@pytest.mark.parametrize("bad_id", [None, "Metadata/Items/Gem/UnobservedGrantor"])
def test_support_grant_cannot_borrow_a_same_name_gem_identity(bad_id):
    source = group("group:identity", supports=("Host", "Damage"))
    source["supports"][0]["gemId"] = bad_id
    value = {"skillKey": "skill:HostPlayer", "supportKeys": [SUPPORTS["Host"], SUPPORTS["Damage"]],
             "sourceGroupRef": source["groupRef"], "rootSkillRef": source["rootSkillRef"],
             "socketedItemRefs": [item["socketedItemRef"] for item in source["supports"]]}
    _, kept, deferred = filter_package(grant_graph(), {"activeSkillGroups": [source]}, value)
    assert not kept and deferred[0]["reason"] == "invalid_source_support_binding"


def test_disabled_additional_effect_remains_unknown_until_another_rooted_owner_proves_it():
    source = group("group:toggle", supports=("Host", "Damage", "Minion"))
    source["supports"][0]["enableGlobal2"] = False
    _, kept, deferred = filter_package(grant_graph(), {"activeSkillGroups": [source]}, package(source))
    assert not kept and any(item["reason"] == "unverified_structured_skill_support_pair" for item in deferred)
    # The uncertain owner must not mask a separate, exact enabled owner of the same effect.
    _, kept, deferred = filter_package(grant_graph(shared_child=True), {"activeSkillGroups": [source]}, package(source))
    assert len(kept) == 1 and not deferred


@pytest.mark.parametrize("toggle", [False, None, "missing"])
def test_unobserved_support_child_enablement_never_defaults_to_true(toggle):
    source = group("group:missing-toggle", supports=("Host", "Damage"))
    if toggle == "missing":
        source["supports"][0].pop("enableGlobal2")
    else:
        source["supports"][0]["enableGlobal2"] = toggle
    _, kept, deferred = filter_package(grant_graph(), {"activeSkillGroups": [source]}, package(source))
    assert not kept and deferred[0]["reason"] == "unverified_structured_skill_support_pair"


@pytest.mark.parametrize("toggle", [False, None, "missing"])
def test_unobserved_active_gem_extra_effect_uses_the_same_enablement_boundary(toggle):
    snapshot = graph().snapshot
    gem = "gem:Metadata/Items/Gem/FixtureExtra"
    source_ref = ("fixture:source-context",)
    service = gt.GraphQueryService(replace(snapshot,
        nodes=(*snapshot.nodes, pg.GraphNode(gem, "skill_gem", "HostPlayer", source_ref)),
        edges=(*snapshot.edges, *(pg.GraphEdge("grants_skill", gem, key, source_ref)
                                  for key in ("skill:HostPlayer", "skill:PayloadBPlayer")))))
    source = group("group:extra", supports=("Damage",))
    source["rootSkill"].update(gemId=gem.removeprefix("gem:"), enableGlobal1=True)
    if toggle != "missing":
        source["rootSkill"]["enableGlobal2"] = toggle
    _, kept, deferred = filter_package(service, {"activeSkillGroups": [source]}, package(source))
    assert not kept and deferred[0]["reason"] == "unverified_structured_skill_support_pair"
    source["rootSkill"]["enableGlobal2"] = True
    _, kept, deferred = filter_package(service, {"activeSkillGroups": [source]}, package(source))
    assert len(kept) == 1 and not deferred
    source["rootSkill"].pop("enableGlobal2")
    source["activeSkills"].append({"name": "PayloadBPlayer", "skillId": "PayloadBPlayer",
        "enabled": True, "socketedUnderSkillRef": source["rootSkillRef"]})
    _, kept, deferred = filter_package(service, {"activeSkillGroups": [source]}, package(source))
    assert len(kept) == 1 and not deferred


def test_internal_support_effect_is_not_an_active_target_or_a_fake_unknown():
    snapshot = graph().snapshot
    gem = "gem:Metadata/Items/Gem/FixtureInternalSupport"
    source_ref = ("fixture:source-context",)
    service = gt.GraphQueryService(replace(snapshot,
        nodes=(*snapshot.nodes, pg.GraphNode(gem, "skill_gem", "HostPlayer", source_ref)),
        edges=(*snapshot.edges,
               pg.GraphEdge("grants_skill", gem, "skill:HostPlayer", source_ref),
               pg.GraphEdge("grants_skill", gem, "skill:SupportFixtureDamage", source_ref))))
    source = group("group:internal", supports=("Damage",))
    source["rootSkill"]["gemId"] = gem.removeprefix("gem:")
    assert acceptance._active_gem_endpoint_keys(snapshot=service.snapshot,
        skill_key="skill:HostPlayer", gem_id=source["rootSkill"]["gemId"]) == ["skill:HostPlayer"]
    _, kept, deferred = filter_package(service, {"activeSkillGroups": [source]}, package(source))
    assert not kept and deferred[0]["reason"] == "unsupported_structured_skill_support_pair"
    assert all(pair["evaluatedSkillKeys"] == ["skill:HostPlayer"] for pair in deferred[0]["unsupportedPairs"])
