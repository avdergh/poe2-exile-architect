"""Independent review regressions at recovery and upgrade-ranking consumers."""

from contextlib import contextmanager

from server.compute import item_search, itemopt
from tests.test_item_search_contract import ItemOracle


def test_waiting_search_rechecks_recovery_after_acquiring_engine_lock():
    class RecoveryWhileWaiting(ItemOracle):
        @contextmanager
        def transaction_lock(self):
            # Another serialized transaction failed restoration before this waiter acquired it.
            self._poe2_mutation_batch_recovery_required = True
            yield

    engine = RecoveryWhileWaiting()
    called = []

    @item_search.read_only_search
    def search(_engine):
        called.append(True)
        return {"ok": True, "item": "must not authorize from a broken input"}

    result = search(engine)

    assert result["ok"] is False
    assert result["errorCode"] == "build_state_recovery_required"
    assert result["recoveryRequired"] is True
    assert "item" not in result
    assert called == []
    assert engine._poe2_mutation_batch_recovery_required is True


def test_upgrade_ranking_preserves_recovered_measurement_failure(monkeypatch):
    monkeypatch.setattr(
        itemopt,
        "optimize_item",
        lambda *_args, **_kwargs: {
            "ok": False,
            "errorCode": "item_measurement_incomplete",
            "candidateIndex": 0,
            "failureCodes": ["item_replacement_group_config_changed"],
            "rolledBack": True,
            "recoveryRequired": False,
        },
    )
    result = itemopt.rank_upgrades(ItemOracle(), slots=["Helmet"])

    assert result["ranked"] == []
    failed = result["rejected"][0]
    assert failed["errorCode"] == "item_measurement_incomplete"
    assert result["skipped"][0]["reason"] != "no craftable affixes"
    assert failed["failureCodes"] == ["item_replacement_group_config_changed"]
