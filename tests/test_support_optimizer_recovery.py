from __future__ import annotations

from contextlib import contextmanager, nullcontext
import json

import pytest

from server.compute import item_search, supportopt
from server.compute.state import build_state_hash


SNAPSHOT = '<PathOfBuilding><Build level="90"/></PathOfBuilding>'
DELTA = '<PathOfBuilding><Build level="89"/></PathOfBuilding>'
PRIVATE = '<PathOfBuilding private="do-not-expose"/>'
RECOVERY_FLAG = "_poe2_mutation_batch_recovery_required"


class SearchFailure(RuntimeError):
    pass


class ReadFailure(RuntimeError):
    pass


class RestoreFailure(RuntimeError):
    pass


class VerifyFailure(RuntimeError):
    pass


class Engine:
    def __init__(self, *, read_errors=None, load_error=None, apply_restore=True, load_result=None):
        self.xml = SNAPSHOT
        self.reads = 0
        self.read_errors = read_errors or {}
        self.load_error = load_error
        self.apply_restore = apply_restore
        self.load_result = load_result
        self.loads = []

    def transaction_lock(self):
        return nullcontext()

    def get_xml(self):
        self.reads += 1
        if error := self.read_errors.get(self.reads):
            raise error
        return self.xml

    def load_build_xml(self, xml, **kwargs):
        self.loads.append((xml, kwargs.get("name")))
        if self.apply_restore:
            self.xml = xml
        if self.load_error:
            raise self.load_error
        return self.load_result


@pytest.fixture(autouse=True)
def no_registry(monkeypatch):
    monkeypatch.setattr(supportopt, "_register_availability_reviews", lambda *_: None)


def invoke(monkeypatch, engine, *, result=None, failure=None, change=True):
    def search(active, **_kwargs):
        if change:
            active.xml = DELTA
        if failure:
            raise failure
        return result if result is not None else {"ok": True, "supports": ["existing"]}

    monkeypatch.setattr(supportopt, "_optimize_supports_locked", search)
    outcome = supportopt.optimize_supports(engine)
    assert PRIVATE not in json.dumps(outcome)
    return outcome


@pytest.mark.parametrize("result", [
    {"ok": True, "supports": ["existing"]},
    {"ok": False, "errorCode": "no_gain", "measurement": {"status": "inconclusive"}},
])
def test_normal_result_is_unchanged_and_does_not_restore(monkeypatch, result):
    engine = Engine()
    assert invoke(monkeypatch, engine, result=result, change=False) is result
    assert engine.loads == []
    assert not getattr(engine, RECOVERY_FLAG, False)


def test_normal_search_drift_restores_entry_snapshot_without_changing_success(monkeypatch):
    engine = Engine()
    result = {"ok": True, "supports": ["existing"]}
    assert invoke(monkeypatch, engine, result=result) is result
    assert engine.loads == [(SNAPSHOT, "support-optimizer-outer-restore")]
    assert engine.xml == SNAPSHOT


def test_failed_state_read_still_restores_and_preserves_search_failure(monkeypatch):
    engine = Engine(read_errors={2: ReadFailure(PRIVATE)})
    result = invoke(monkeypatch, engine, failure=SearchFailure(PRIVATE))
    assert result["firstFailure"]["errorType"] == "SearchFailure"
    assert result["recovery"]["initialStateReadFailure"]["errorType"] == "ReadFailure"
    assert result["recovery"]["snapshotVerified"] is True
    assert result["actualStateHash"] == build_state_hash(SNAPSHOT)
    assert result["rolledBack"] is True
    assert result["recoveryRequired"] is False


def test_restore_and_verification_errors_do_not_replace_first_failure(monkeypatch):
    engine = Engine(read_errors={2: ReadFailure(PRIVATE), 3: VerifyFailure(PRIVATE)},
                    load_error=RestoreFailure(PRIVATE))
    result = invoke(monkeypatch, engine, failure=SearchFailure(PRIVATE))
    assert result["errorCode"] == "support_optimizer_state_restore_failed"
    assert result["firstFailure"]["errorType"] == "SearchFailure"
    assert [(row["stage"], row["errorType"]) for row in result["recovery"]["errors"]] == [
        ("snapshot_restore", "RestoreFailure"), ("restoration_verification", "VerifyFailure"),
    ]
    assert result["actualStateHash"] is None
    assert result["recoveryRequired"] is True
    assert result["rolledBack"] is False
    assert getattr(engine, RECOVERY_FLAG) is True


@pytest.mark.parametrize("failure", [RestoreFailure(PRIVATE), None])
def test_unverified_or_mismatching_restore_never_claims_rollback(monkeypatch, failure):
    engine = Engine(load_error=failure, apply_restore=False)
    result = invoke(monkeypatch, engine, failure=SearchFailure(PRIVATE))
    assert result["recoveryRequired"] is True
    assert result["rolledBack"] is False
    assert result["recovery"]["snapshotVerified"] is False
    assert result["actualStateHash"] == build_state_hash(DELTA)


@pytest.mark.parametrize("load_error,load_result", [
    (RestoreFailure(PRIVATE), None),
    (None, {"ok": False, "errorCode": "restore_declined", "error": PRIVATE}),
])
def test_hash_match_does_not_erase_failed_restore_command(monkeypatch, load_error, load_result):
    engine = Engine(load_error=load_error, load_result=load_result)
    result = invoke(monkeypatch, engine, failure=SearchFailure(PRIVATE))
    assert result["recovery"]["snapshotVerified"] is True
    assert result["recovery"]["status"] == "failed"
    assert result["recoveryRequired"] is True
    assert result["rolledBack"] is False


def test_state_read_error_after_success_is_explicit_even_if_recovered(monkeypatch):
    result = invoke(monkeypatch, Engine(read_errors={2: ReadFailure(PRIVATE)}))
    assert result["ok"] is False
    assert result["errorCode"] == "support_optimizer_state_inspection_failed"
    assert result["firstFailure"]["stage"] == "state_inspection"
    assert result["rolledBack"] is True


@pytest.mark.parametrize("restore_error", [None, RestoreFailure(PRIVATE)])
def test_returned_recovery_required_survives_cleanup_errors_and_matching_hash(monkeypatch, restore_error):
    original = {"ok": False, "errorCode": "probe_restore_failed", "recoveryRequired": True,
                "rolledBack": False, "stateHash": build_state_hash(SNAPSHOT), "error": PRIVATE}
    result = invoke(monkeypatch, Engine(read_errors={2: ReadFailure(PRIVATE)}, load_error=restore_error),
                    result=original, change=False)
    assert result["firstFailure"]["errorCode"] == "probe_restore_failed"
    assert result["recoveryRequired"] is True
    assert result["rolledBack"] is False
    assert result["recovery"]["restoreAttempted"] is True
    assert "stateHash" not in result
    assert original["recoveryRequired"] is True


def test_typed_probe_stop_retains_original_code_when_recovery_also_fails(monkeypatch):
    failure = supportopt._SupportRecoveryRequired({
        "ok": False, "errorCode": "support_probe_native_restore_failed",
        "recoveryRequired": True, "error": PRIVATE,
    })
    result = invoke(monkeypatch, Engine(load_error=RestoreFailure(PRIVATE)), failure=failure)
    assert result["firstFailure"]["errorCode"] == "support_probe_native_restore_failed"
    assert result["firstFailure"]["stage"] == "support_probe"
    assert result["recoveryRequired"] is True


def test_real_locked_control_flow_does_not_lose_probe_dict_to_inner_cleanup(monkeypatch):
    class ProbeEngine(Engine):
        broken = False

        def get_xml(self):
            if self.broken:
                raise ReadFailure(PRIVATE)
            return self.xml

        def get_build(self):
            return {"mainSkillGroup": [{"name": "Spark", "level": 20}]}

        def get_stats(self, _keys):
            return {"stats": {"TotalDPS": 10, "Life": 100, "LifeReserved": 0, "LifeUnreserved": 100}}

        def load_build_xml(self, xml, **kwargs):
            self.loads.append((xml, kwargs.get("name")))
            if self.broken:
                raise RestoreFailure(PRIVATE)
            self.xml = xml

        def call(self, method, **_kwargs):
            if method == "set_skill_group_state":
                return {"ok": True}
            assert method == "list_skill_groups"
            return {"mainGroupIndex": 1, "groups": [{
                "index": 1, "activeSkill": "Spark", "mainActiveSkill": 1, "mainActiveSkillCalcs": 1,
                "activeSkills": [{"index": 1, "name": "Spark", "effectId": "SparkPlayer"}],
                "gems": [{"name": "Spark", "isSupport": False, "level": 20, "quality": 0}],
            }]}

        def probe_regular_skill_group(self, **_kwargs):
            self.broken = True
            return {"ok": False, "errorCode": "inner_probe_restore_failed", "recoveryRequired": True}

    monkeypatch.setattr(supportopt, "_availability_context", lambda *_: {"fingerprint": "fixture"})
    monkeypatch.setattr(supportopt, "_candidate_availability", lambda *_: {"status": "available"})
    monkeypatch.setattr(supportopt, "_screen_set", lambda *_: ["Fixture Support"])
    monkeypatch.setattr(supportopt, "_runtime_support_identity", lambda *_: {
        "status": "resolved", "name": "Fixture Support", "gemId": "fixture:support", "effectId": "FixtureSupport",
    })
    monkeypatch.setattr(supportopt, "_support_evaluation_capability", lambda *_, **__: {
        "numericRanking": "supported", "applicationCheck": "verified", "selectedEffectId": "SparkPlayer",
        "usageConditionContractVersion": 1, "usageConditionContracts": [],
    })
    monkeypatch.setattr(supportopt, "_regular_probe_xml", lambda *_, **__: "<Skill/>")
    monkeypatch.setattr(supportopt.hard_legality, "audit_build", lambda *_: {"status": "passed"})
    monkeypatch.setattr(supportopt.hard_legality, "augment_build_with_snapshot_gear", lambda build, _: build)
    engine = ProbeEngine()
    result = supportopt.optimize_supports(engine)
    assert result["firstFailure"]["errorCode"] == "inner_probe_restore_failed"
    assert result["recoveryRequired"] is True
    assert result["rolledBack"] is False
    assert [name for _, name in engine.loads] == [
        "support-current-combination-reset", "support-optimizer-outer-restore",
    ]
    assert PRIVATE not in json.dumps(result)


def test_explicit_cause_is_preserved_but_unrelated_context_is_not_root(monkeypatch):
    root = SearchFailure(PRIVATE)
    wrapper = RuntimeError(PRIVATE)
    wrapper.__cause__ = root
    result = invoke(monkeypatch, Engine(), failure=wrapper)
    assert result["firstFailure"]["errorType"] == "SearchFailure"
    assert [row["errorType"] for row in result["failureChain"]] == ["SearchFailure", "RuntimeError"]
    unrelated = RuntimeError(PRIVATE)
    unrelated.__context__ = root
    result = invoke(monkeypatch, Engine(), failure=unrelated)
    assert result["firstFailure"]["errorType"] == "RuntimeError"
    assert len(result["failureChain"]) == 1


def test_cause_cycles_and_long_chains_are_bounded(monkeypatch):
    root = SearchFailure(PRIVATE)
    root.__cause__ = root
    result = invoke(monkeypatch, Engine(), failure=root)
    assert result["failureChainTruncated"] is True
    assert len(result["failureChain"]) == 1
    for _ in range(12):
        wrapper = RuntimeError(PRIVATE)
        wrapper.__cause__ = root
        root = wrapper
    result = invoke(monkeypatch, Engine(), failure=root)
    assert result["failureChainTruncated"] is True
    assert len(result["failureChain"]) == 8


def test_unavailable_entry_snapshot_is_safe_and_cannot_claim_restoration(monkeypatch):
    engine = Engine(read_errors={1: ReadFailure(PRIVATE)})
    result = invoke(monkeypatch, engine)
    assert result["firstFailure"]["stage"] == "input_snapshot"
    assert result["recoveryRequired"] is True
    assert result["rolledBack"] is False
    assert engine.loads == []
    assert getattr(engine, RECOVERY_FLAG) is True


def test_malformed_internal_result_does_not_break_final_guard(monkeypatch):
    monkeypatch.setattr(supportopt, "_optimize_supports_locked", lambda *_args, **_kwargs: None)
    result = supportopt.optimize_supports(Engine())
    assert result["ok"] is False
    assert result["firstFailure"]["errorType"] == "TypeError"
    assert result["recovery"]["snapshotVerified"] is True


def test_cancel_is_not_overridden_by_cleanup_failure(monkeypatch):
    stop = KeyboardInterrupt()
    engine = Engine(read_errors={2: ReadFailure(PRIVATE)}, load_error=RestoreFailure(PRIVATE))
    with pytest.raises(KeyboardInterrupt) as caught:
        invoke(monkeypatch, engine, failure=stop)
    assert caught.value is stop
    assert engine.loads
    assert getattr(engine, RECOVERY_FLAG) is True
    previous_reads = engine.reads
    assert supportopt.optimize_supports(engine)["errorCode"] == "build_state_recovery_required"
    assert engine.reads == previous_reads


@pytest.mark.parametrize("public_entry", [False, True])
def test_marked_engine_is_rejected_before_reads_or_registry(monkeypatch, public_entry):
    engine = Engine(read_errors={1: AssertionError("must not observe a marked engine")})
    setattr(engine, RECOVERY_FLAG, True)
    registry_calls = []
    monkeypatch.setattr(supportopt, "_register_availability_reviews",
                        lambda *_: registry_calls.append(True))
    if public_entry:
        from server import main
        monkeypatch.setattr(main, "get_engine", lambda: engine)
        result = main.optimize_supports()
    else:
        result = supportopt.optimize_supports(engine)
    assert result == {"ok": False, "errorCode": "build_state_recovery_required",
                      "recoveryRequired": True}
    assert engine.reads == 0 and engine.loads == [] and registry_calls == []
    assert getattr(engine, RECOVERY_FLAG) is True


def test_recovery_mark_is_checked_after_entering_transaction_lock():
    class WaitingEngine(Engine):
        @contextmanager
        def transaction_lock(self):
            # Another operation can finish unsuccessfully while this call waits for the lock.
            setattr(self, RECOVERY_FLAG, True)
            yield

    engine = WaitingEngine()
    result = supportopt.optimize_supports(engine)
    assert result["errorCode"] == "build_state_recovery_required"
    assert engine.reads == 0 and engine.loads == []


class SelectionFailureEngine(Engine):
    """Use the real support search; fault at its native group-selection boundary."""
    def call(self, method, **_kwargs):
        if method == "list_skill_groups":
            return {"mainGroupIndex": 1, "groups": [{"index": 2}]}
        assert method == "set_skill_group_state"
        self.xml = DELTA
        raise SearchFailure(PRIVATE)


def test_real_selection_failure_blocks_support_and_item_search_retries():
    engine = SelectionFailureEngine(load_error=RestoreFailure(PRIVATE), apply_restore=False)
    failure = supportopt.optimize_supports(engine, group_index=2)
    assert failure["firstFailure"]["errorType"] == "SearchFailure"
    assert failure["recoveryRequired"] is True and failure["rolledBack"] is False
    assert getattr(engine, RECOVERY_FLAG) is True and engine.xml == DELTA
    previous_reads, previous_loads = engine.reads, list(engine.loads)
    assert supportopt.optimize_supports(engine, group_index=2)["errorCode"] == "build_state_recovery_required"
    item_search_calls = []

    @item_search.read_only_search
    def other_search(_engine):
        item_search_calls.append(True)
        return {"ok": True}

    assert other_search(engine)["errorCode"] == "build_state_recovery_required"
    assert engine.reads == previous_reads and engine.loads == previous_loads
    assert item_search_calls == []


def test_real_selection_failure_with_verified_restore_does_not_block_next_call():
    engine = SelectionFailureEngine()
    failure = supportopt.optimize_supports(engine, group_index=2)
    assert failure["rolledBack"] is True and failure["recoveryRequired"] is False
    assert engine.xml == SNAPSHOT and not getattr(engine, RECOVERY_FLAG, False)
    previous_reads = engine.reads
    next_result = supportopt.optimize_supports(engine, group_index=99)
    assert next_result["errorCode"] == "skill_group_not_found"
    assert engine.reads > previous_reads


def test_stop_marked_by_nested_work_cannot_be_cleared_by_matching_snapshot(monkeypatch):
    engine = Engine()

    def nested_stop(active, **_kwargs):
        setattr(active, RECOVERY_FLAG, True)
        return {"ok": False, "errorCode": "nested_recovery_required"}

    monkeypatch.setattr(supportopt, "_optimize_supports_locked", nested_stop)
    result = supportopt.optimize_supports(engine)
    assert result["recovery"]["snapshotVerified"] is True
    assert result["recoveryRequired"] is True and result["rolledBack"] is False
    assert getattr(engine, RECOVERY_FLAG) is True


def test_interrupted_cleanup_marks_state_unconfirmed_without_swallowing_interrupt(monkeypatch):
    stop = KeyboardInterrupt()
    engine = Engine(load_error=stop, apply_restore=False)
    with pytest.raises(KeyboardInterrupt) as caught:
        invoke(monkeypatch, engine, failure=SearchFailure(PRIVATE))
    assert caught.value is stop
    assert getattr(engine, RECOVERY_FLAG) is True
