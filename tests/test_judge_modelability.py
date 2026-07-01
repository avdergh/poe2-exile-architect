from __future__ import annotations

from server.judge import modelability


def test_main_socket_group_meta_trigger_is_core_blocker():
    build = {
        "mainSkillGroup": [
            {"name": "Spark", "isSupport": False},
            {"name": "Cast on Critical", "isSupport": True},
        ]
    }

    result = modelability.evaluate_modelability(build)

    assert result["status"] == "not_modelable"
    assert result["coreBlocked"] is True
    assert "unmodelled_mechanic" in result["failureCodes"]


def test_unknown_unmodelled_signal_defaults_to_partial():
    build = {"mainSkillGroup": [{"name": "Spark", "isSupport": False}]}

    result = modelability.evaluate_modelability(
        build,
        warnings=["Engine limitation - secondary cosmetic effect is not modelled"],
    )

    assert result["status"] == "partial"
    assert result["coreBlocked"] is False
    assert "modelability_penalty" in result["caveats"]


def test_whitelisted_unmodelled_signal_is_light_caveat():
    build = {"mainSkillGroup": [{"name": "Spark", "isSupport": False}]}

    result = modelability.evaluate_modelability(
        build,
        warnings=["Projectile overlap caveat: manual positioning may change real DPS"],
    )

    assert result["status"] == "partial"
    assert result["coreBlocked"] is False
    assert "non_core_unmodelled_whitelist" in result["caveats"]
