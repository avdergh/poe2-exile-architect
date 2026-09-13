"""Cache lifetime contracts; synthetic readings are not game measurements."""

from concurrent.futures import ThreadPoolExecutor
import gc
import threading
import weakref

import pytest

from server.compute.engine_pool import SessionEnginePool
from server.generation import validation_checkpoint as checkpoint
from tests.test_generation_fast_path import FakeCheckpointEngine


class CacheEngine(FakeCheckpointEngine):
    def __init__(self, value=111, ready=True):
        super().__init__()
        self.value = value
        self.ready = ready
        self.proc = object()
        self.lock = threading.RLock()
        self.stats_hook = None
        self.closed = False
        self.calls["preflight"] = 0

    def transaction_lock(self):
        return self.lock

    def get_stats(self, _keys):
        self.calls["stats"] += 1
        hook, self.stats_hook = self.stats_hook, None
        if hook:
            hook()
        return {"stats": {"TotalDPS": self.value, "Life": 500}}

    def get_defenses(self):
        self.calls["defenses"] += 1
        return {"totalEHP": self.value}

    def load_build_xml(self, xml, name=""):
        self.xml = xml

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def isolated_checkpoints(monkeypatch):
    checkpoint.clear_validation_checkpoint_cache()
    monkeypatch.setattr(
        checkpoint.completeness, "inspect_build_completeness",
        lambda *_args, **_kwargs: {"status": "complete", "hardFailures": []},
    )

    def preflight(engine, _xml, *, completeness_result):
        engine.calls["preflight"] += 1
        return {
            "readyForJudge": engine.ready,
            "hardLegalityReady": engine.ready,
            "hardLegality": {"passed": engine.ready},
            "completeness": completeness_result,
        }

    monkeypatch.setattr(checkpoint.preflight, "inspect_generation_snapshot", preflight)
    yield
    checkpoint.clear_validation_checkpoint_cache()


@pytest.mark.parametrize("first_ready", [True, False])
def test_same_xml_in_another_engine_recomputes_pass_and_fail(first_ready):
    first = CacheEngine(111, first_ready)
    second = CacheEngine(999, not first_ready)
    a = checkpoint.inspect_generation_checkpoint(first)
    b = checkpoint.inspect_generation_checkpoint(second)

    assert a["stateHash"] == b["stateHash"]
    assert b["cacheHit"] is False
    assert b["stats"]["TotalDPS"] == b["defenses"]["totalEHP"] == 999
    assert b["readyForJudge"] is not first_ready
    assert b["hardLegality"]["passed"] is not first_ready
    assert second.calls["stats"] == second.calls["preflight"] == 1
    assert a["validationRef"] != b["validationRef"]
    repeated = checkpoint.inspect_generation_checkpoint(first)
    assert repeated["cacheHit"] is True
    assert repeated["validationRef"] == a["validationRef"]
    assert first.calls["stats"] == first.calls["preflight"] == 1


def test_replacing_process_on_same_engine_invalidates_cache():
    engine = CacheEngine()
    first = checkpoint.inspect_generation_checkpoint(engine)
    engine.proc = object()
    engine.value, engine.ready = 999, False
    second = checkpoint.inspect_generation_checkpoint(engine)
    assert not second["cacheHit"]
    assert second["stats"]["TotalDPS"] == 999
    assert second["readyForJudge"] is False
    assert first["validationRef"] != second["validationRef"]


@pytest.mark.parametrize("swap_fails", [False, True])
def test_runtime_swap_recomputes_preserved_builds_even_after_install_error(swap_fails):
    runtime = {"value": 111, "ready": True}
    pool = SessionEnginePool(factory=lambda: CacheEngine(**runtime), max_engines=2)
    owner = object()
    try:
        old = pool.get(owner)
        first = checkpoint.inspect_generation_checkpoint(old)
        try:
            with pool.preserve_sessions():
                runtime.update(value=999, ready=False)
                if swap_fails:
                    raise RuntimeError("isolated installation failure")
        except RuntimeError:
            assert swap_fails
        new = pool.get(owner)
        second = checkpoint.inspect_generation_checkpoint(new)
        assert new is not old and old.closed and new.get_xml() == old.get_xml()
        assert second["stateHash"] == first["stateHash"]
        assert second["cacheHit"] is False
        assert second["stats"]["TotalDPS"] == 999
        assert second["readyForJudge"] is False
    finally:
        pool.close_all()


@pytest.mark.parametrize("change", ["clear", "replace_process"])
def test_context_change_during_read_cannot_publish_old_checkpoint(change):
    engine = CacheEngine()
    engine.stats_hook = (
        checkpoint.clear_validation_checkpoint_cache
        if change == "clear" else lambda: setattr(engine, "proc", object())
    )
    result = checkpoint.inspect_generation_checkpoint(engine)
    assert result["errorCode"] == "generation_checkpoint_context_changed"
    assert result["readyForJudge"] is False
    fresh = checkpoint.inspect_generation_checkpoint(engine)
    assert fresh["cacheHit"] is False
    assert engine.calls["stats"] == 2


def test_context_change_during_cache_hit_refresh_cannot_return_old_pass(monkeypatch):
    engine = CacheEngine()
    checkpoint.inspect_generation_checkpoint(engine)
    original = checkpoint._refresh_lifecycle

    def refresh(result, *, engine, xml):
        checkpoint.clear_validation_checkpoint_cache()
        return original(result, engine=engine, xml=xml)

    monkeypatch.setattr(checkpoint, "_refresh_lifecycle", refresh)
    result = checkpoint.inspect_generation_checkpoint(engine)
    assert result["errorCode"] == "generation_checkpoint_context_changed"
    assert result["readyForJudge"] is False
    assert engine.calls["stats"] == 1


def test_exited_process_cannot_authorize_cached_pass():
    class Process:
        returncode = None

        def poll(self):
            return self.returncode

    engine = CacheEngine()
    engine.proc = Process()
    checkpoint.inspect_generation_checkpoint(engine)
    engine.proc.returncode = 1
    # The fixture can still return XML; a stale local snapshot must not authorize a dead process.
    result = checkpoint.inspect_generation_checkpoint(engine)
    assert result["errorCode"] == "generation_checkpoint_context_changed"
    assert result["readyForJudge"] is False


def test_same_engine_concurrent_requests_compute_once():
    engine = CacheEngine()
    entered, release = threading.Event(), threading.Event()

    def hold_read():
        entered.set()
        assert release.wait(5)

    engine.stats_hook = hold_read
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(checkpoint.inspect_generation_checkpoint, engine)
        try:
            assert entered.wait(5)
            second = workers.submit(checkpoint.inspect_generation_checkpoint, engine)
        finally:
            release.set()
        a, b = first.result(timeout=5), second.result(timeout=5)
    assert not a["cacheHit"] and b["cacheHit"]
    assert engine.calls["stats"] == engine.calls["preflight"] == 1


def test_refresh_in_one_session_does_not_hold_other_session_cache_lock(monkeypatch):
    first, second = CacheEngine(), CacheEngine(999)
    checkpoint.inspect_generation_checkpoint(first)
    entered, release = threading.Event(), threading.Event()
    original = checkpoint._refresh_lifecycle

    def refresh(result, *, engine, xml):
        if engine is first:
            entered.set()
            assert release.wait(5)
        return original(result, engine=engine, xml=xml)

    monkeypatch.setattr(checkpoint, "_refresh_lifecycle", refresh)
    with ThreadPoolExecutor(max_workers=2) as workers:
        pending = workers.submit(checkpoint.inspect_generation_checkpoint, first)
        try:
            assert entered.wait(5)
            independent = workers.submit(checkpoint.inspect_generation_checkpoint, second)
            b = independent.result(timeout=2)
            assert not b["cacheHit"] and b["stats"]["TotalDPS"] == 999
        finally:
            release.set()
        assert pending.result(timeout=5)["cacheHit"] is True


def test_engine_cache_does_not_keep_closed_sessions_alive():
    engine = CacheEngine()
    checkpoint.inspect_generation_checkpoint(engine)
    reference = weakref.ref(engine)
    engine.close()
    del engine
    gc.collect()
    assert reference() is None


def test_per_engine_cache_eviction_keeps_other_session_reusable(monkeypatch):
    monkeypatch.setattr(checkpoint, "_CACHE_LIMIT", 2)
    first, other = CacheEngine(), CacheEngine(999)
    checkpoint.inspect_generation_checkpoint(other)
    original_xml = first.xml
    for level in (18, 19, 20):
        first.xml = original_xml.replace('level="18"', f'level="{level}"')
        assert not checkpoint.inspect_generation_checkpoint(first)["cacheHit"]
    first.xml = original_xml
    assert not checkpoint.inspect_generation_checkpoint(first)["cacheHit"]
    assert checkpoint.inspect_generation_checkpoint(other)["cacheHit"] is True
