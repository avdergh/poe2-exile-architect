"""同名主题、显式来源修订和写入回执的精确绑定回归。"""

from copy import deepcopy

import pytest

from server.knowledge import mature_learning, research_content, research_models, research_runtime
from test_patch_reviews import seeded
from test_research_acceptance_diagnostics import _clean, _unit_kwargs
from test_research_claim_review import _claim_revision
from test_research_source_claims import SOURCE_A, SOURCE_B, _accept, _lane, _variant


def _resource(payload, mechanism="on_hit_recovery", **updates):
    return _variant(
        payload,
        record_kind="resource_engine",
        title="魔力续航",
        content=f"这一来源的{mechanism}收益依赖对应条件，恢复量需单独验证。",
        typed_payload={
            **payload["deep_research_records"][0]["typed_payload"],
            "resourceMechanisms": [mechanism],
        },
        **updates,
    )


def _revision_fixture(tmp_path):
    service, payload, _first = seeded(tmp_path)
    original = _resource(payload)
    accepted = _accept(service, original)
    revision = _resource(payload, "flask_recovery")
    revision["deep_research_records"][0]["source_claim_revision"] = _claim_revision(accepted)
    return service, original, accepted, revision


def _claims(service):
    with mature_learning.connect(service.db_path) as con:
        return [tuple(row) for row in con.execute(
            "SELECT knowledge_scope,knowledge_key,source_case_ref,source_claim_key,game_patch,"
            "passive_tree_version,record_id,accepted_projection_hash,binding_issue "
            "FROM deep_research_record_evidence ORDER BY 1,2,3,4,5,6"
        )]


@pytest.mark.parametrize("same_submission", [False, True])
def test_distinct_resource_topics_can_share_display_title(tmp_path, same_submission):
    service, payload, first = seeded(tmp_path)
    topics = [_resource(payload, mechanism) for mechanism in ("on_hit_recovery", "flask_recovery")]
    if same_submission:
        combined = deepcopy(topics[0])
        combined["deep_research_records"].extend(topics[1]["deep_research_records"])
        accepted = _accept(service, combined)
        assert len(accepted["knowledgeKeys"]) == len(accepted["recordWrites"]) == 2
    else:
        accepted = [_accept(service, topic) for topic in topics]
        assert accepted[0]["knowledgeKeys"] != accepted[1]["knowledgeKeys"]
    rows = _lane(service, first["buildFamilyKeys"][0], SOURCE_A)["deepResearchRecords"]
    assert {topic["deep_research_records"][0]["content"] for topic in topics} <= {
        row["content"] for row in rows
    }


@pytest.mark.parametrize("changed", [
    "record_id", "projection_hash", "knowledge_key", "source", "claim_key", "scope", "patch",
    "tree", "unbound", "binding_issue", "source_state", "legacy_schema",
])
def test_explicit_topic_revision_rejects_inexact_or_unattested_old_binding(tmp_path, changed):
    service, _original, accepted, revision = _revision_fixture(tmp_path)
    record = revision["deep_research_records"][0]
    if changed in {"record_id", "projection_hash", "knowledge_key"}:
        record["source_claim_revision"][changed] = (
            "0" * 64 if changed == "projection_hash" else "missing-binding"
        )
    elif changed in {"source", "claim_key", "scope", "patch", "tree", "source_state"}:
        field, value = {
            "source": ("source_case_refs", [SOURCE_B]),
            "claim_key": ("source_claim_key", "another-condition"),
            "scope": ("knowledge_scope", "local_user"),
            "patch": ("game_patch", "0.5.5"),
            "tree": ("passive_tree_version", "other-tree"),
            "source_state": ("source_state_scope", "unknown"),
        }[changed]
        record[field] = value
    else:
        with mature_learning.connect(service.db_path) as con:
            if changed == "legacy_schema":
                con.execute(
                    "UPDATE deep_research_records SET record_schema_version=1 WHERE record_id=?",
                    (accepted["recordIds"][0],),
                )
            else:
                field, value = (
                    ("record_id", None) if changed == "unbound"
                    else ("binding_issue", "legacy_record_schema")
                )
                con.execute(
                    f"UPDATE deep_research_record_evidence SET {field}=? WHERE record_id=?",
                    (value, accepted["recordIds"][0]),
                )
            con.commit()
    before = _claims(service)
    assert service.validate_deep_research_records(revision)["status"] == "rejected"
    assert service.propose_deep_research_records(revision)["status"] == "rejected"
    assert _claims(service) == before


@pytest.mark.parametrize("batch_kind", ["old_and_revision", "revision_and_old", "two_retractions"])
def test_revision_cannot_retract_another_claim_in_the_same_batch(tmp_path, batch_kind):
    service, original, _accepted, revision = _revision_fixture(tmp_path)
    if batch_kind == "two_retractions":
        other = deepcopy(revision)
        other["deep_research_records"][0]["typed_payload"]["resourceMechanisms"] = ["mana_leech"]
    else:
        other = original
    records = revision["deep_research_records"] + other["deep_research_records"]
    if batch_kind == "old_and_revision":
        records.reverse()
    batch = {**revision, "deep_research_records": records}
    before = _claims(service)
    preview = service.validate_deep_research_records(batch)
    result = service.propose_deep_research_records(batch)
    assert preview["errorCode"] == result["errorCode"] == "source_claim_revision_batch_conflict"
    assert _claims(service) == before


def test_revision_cannot_target_a_claim_created_earlier_in_same_batch(tmp_path):
    service, payload, _accepted = seeded(tmp_path)
    first = _resource(payload)
    proposal = research_models.DeepResearchRecordProposal.model_validate(first["deep_research_records"][0])
    from server.knowledge import research_identity

    key = research_identity.knowledge_key(proposal, research_identity.infer_build_family([proposal]))
    revision = _resource(payload, "flask_recovery")
    revision["deep_research_records"][0]["source_claim_revision"] = {
        "knowledge_key": key,
        "record_id": research_runtime.canonical_record_id(proposal.knowledge_scope, key),
        "projection_hash": research_runtime.projection_hash(proposal.model_dump(mode="json")),
    }
    first["deep_research_records"].extend(revision["deep_research_records"])
    before = _claims(service)
    assert service.propose_deep_research_records(first)["errorCode"] == "source_claim_revision_batch_conflict"
    assert _claims(service) == before


def test_revision_refuses_to_overwrite_another_existing_topic_claim(tmp_path):
    service, _original, _accepted, revision = _revision_fixture(tmp_path)
    another = deepcopy(revision)
    del another["deep_research_records"][0]["source_claim_revision"]
    _accept(service, another)
    before = _claims(service)
    assert service.propose_deep_research_records(revision)["errorCode"] == "source_claim_revision_target_already_claimed"
    assert _claims(service) == before


def test_stale_revision_hash_fails_after_source_revises_same_topic(tmp_path):
    service, original, _accepted, revision = _revision_fixture(tmp_path)
    _accept(service, _variant(original, content="该来源刚完成新的前提复核，旧投影不再是当前证据。"))
    before = _claims(service)
    assert service.propose_deep_research_records(revision)["errorCode"] == "source_claim_revision_binding_mismatch"
    assert _claims(service) == before


def test_revision_metadata_does_not_change_shared_content_or_projection(tmp_path):
    _service, _original, _accepted, revision = _revision_fixture(tmp_path)
    with_revision = research_models.DeepResearchRecordProposal.model_validate(revision["deep_research_records"][0])
    plain = with_revision.model_copy(update={"source_claim_revision": None})
    values = [item.model_dump(mode="json") for item in (plain, with_revision)]
    assert research_runtime.projection_hash(values[0]) == research_runtime.projection_hash(values[1])
    assert {key: values[0][key] for key in research_content.CONTENT_FIELDS} == {
        key: values[1][key] for key in research_content.CONTENT_FIELDS
    }


@pytest.mark.parametrize("binding_change", ["retracted", "unbound", "issue", "hash", "state"])
def test_receipt_does_not_borrow_sibling_claim_but_retains_legitimate_lane(tmp_path, binding_change):
    service, payload, _first = seeded(tmp_path)
    resource = _resource(payload)
    receipt = service.accept_research_unit(
        **{**_unit_kwargs(), "deep_payload": resource}, acceptance_diagnostics=_clean()
    )
    assert receipt["status"] == "accepted", receipt
    old = receipt["deepRecordWrite"]
    old_id = old["recordIds"][0]
    _accept(service, _variant(resource, source_claim_key="parallel-confirmation"))
    if binding_change == "retracted":
        revision = _resource(payload, "flask_recovery")
        revision["deep_research_records"][0]["source_claim_revision"] = _claim_revision(old)
        _accept(service, revision)
    else:
        field, value = {
            "unbound": ("record_id", None),
            "issue": ("binding_issue", "legacy_record_schema"),
            "hash": ("accepted_projection_hash", "0" * 64),
            "state": ("source_state_scope", "unknown"),
        }[binding_change]
        with mature_learning.connect(service.db_path) as con:
            con.execute(
                f"UPDATE deep_research_record_evidence SET {field}=? "
                "WHERE record_id=? AND source_claim_key='default'", (value, old_id),
            )
            con.commit()
    current = service.get_research_write_receipt(receipt["writeReceiptRef"])["currentProjection"][0]
    assert current["currentEligibility"] is False
    assert current["claimBindingStatus"] == {
        "retracted": "missing", "unbound": "unbound",
        "issue": "diagnostic_only",
    }.get(binding_change, "invalid")
    if binding_change == "issue":
        assert current["bindingIssue"] == "legacy_record_schema"
        assert "source_claim_binding_mismatch" not in current["currentExclusionReasons"]
    assert current["recordLaneEligibility"] is True
    assert current["recordLaneRecordId"] == old_id
    lane = _lane(service, old["buildFamilyKeys"][0], SOURCE_A)["deepResearchRecords"]
    assert old_id in {row["recordId"] for row in lane}


def test_receipt_follows_an_actual_same_topic_revision(tmp_path):
    service, payload, _first = seeded(tmp_path)
    receipt = service.accept_research_unit(
        **{**_unit_kwargs(), "deep_payload": payload}, acceptance_diagnostics=_clean()
    )
    current = service.get_research_write_receipt(receipt["writeReceiptRef"])["currentProjection"][0]
    assert current["currentEligibility"] is True
    assert current["claimBindingStatus"] == "current"
    _accept(service, _variant(payload, content="同主题来源声明的条件已复核，当前回执可追踪到其新投影。"))
    current = service.get_research_write_receipt(receipt["writeReceiptRef"])["currentProjection"][0]
    assert current["currentEligibility"] is True
    assert current["claimBindingStatus"] == "revised"


def test_unknown_source_binding_is_diagnostic_but_bad_hash_still_fails(tmp_path):
    service, payload, _first = seeded(tmp_path)
    unknown = _variant(payload, source_state_scope="unknown")
    accepted = service.accept_research_unit(
        **{**_unit_kwargs(), "deep_payload": unknown}, acceptance_diagnostics=_clean()
    )
    assert accepted["status"] == "accepted", accepted
    ref = accepted["writeReceiptRef"]
    current = service.get_research_write_receipt(ref)["currentProjection"][0]
    assert current["claimBindingStatus"] == "diagnostic_only"
    assert current["bindingIssue"] == "source_state_unknown"
    assert current["currentEligibility"] is False
    assert "source_state_unknown" in current["currentExclusionReasons"]
    assert "source_claim_binding_mismatch" not in current["currentExclusionReasons"]
    with mature_learning.connect(service.db_path) as con:
        con.execute("UPDATE deep_research_record_evidence SET accepted_projection_hash=? WHERE record_id=?",
                    ("0" * 64, current["writtenRecordId"]))
        con.commit()
    invalid = service.get_research_write_receipt(ref)["currentProjection"][0]
    assert invalid["claimBindingStatus"] == "invalid"
    assert "source_claim_binding_mismatch" in invalid["currentExclusionReasons"]
    assert invalid["currentEligibility"] is False
