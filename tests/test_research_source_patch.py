import pytest

from scripts import research_mature_builds
from server.freshness import providers
from server.knowledge import research_workflow


@pytest.fixture
def old_model_certification(monkeypatch):
    compatibility = providers.LocalCompatibility(
        game_patch="0.5.4", passive_tree="0_5", pob_version="0.23.1",
        pob_commit="7d6f530cbdab20389ff8bc6ba97a37ac27f74e41",
    )
    monkeypatch.setattr(providers, "current_local_compatibility", lambda: compatibility)
    return compatibility


def test_live_source_patch_is_independent_of_old_model_certification(monkeypatch, old_model_certification):
    report = {
        "decision": "blocked_conflict",
        "active_evidence": [
            {
                "source": "ggg-patch",
                "component": "game_patch",
                "status": "current",
                "claims": [{"key": "game_patch", "value": "0.5.5"}],
            },
            {
                "source": "reviewed-ggg-league",
                "component": "league",
                "status": "current",
                "claims": [{"key": "league", "value": "Forbidden Rites"}],
            },
        ],
    }
    monkeypatch.setattr(
        research_workflow.freshness_service, "get_freshness_report", lambda **_: report
    )
    source_patch, league = research_workflow._source_patch_for_run(
        source_game_patch=None, league="current", offline=False, prior_run=None
    )
    assert source_patch == "0.5.5" and league == "forbiddenrites"
    with pytest.raises(ValueError, match="source_patch_mismatch"):
        research_workflow._source_patch_for_run(
            source_game_patch="0.5.4", league="current", offline=False, prior_run=None)
    context = research_mature_builds._runtime_version_context(
        current_patch=source_patch, passive_tree_version=None, pob_version_or_commit=None
    )
    assert context["gamePatch"] == "0.5.5"
    assert context["modelGamePatch"] == old_model_certification.game_patch == "0.5.4"
    assert context["pobVersionOrCommit"] == old_model_certification.pob_version == "0.23.1"
    assert context["status"] == "source_patch_model_mismatch"


def test_offline_source_needs_explicit_patch_and_unknown_live_does_not_guess(monkeypatch):
    with pytest.raises(ValueError, match="source_game_patch_required"):
        research_workflow._source_patch_for_run(
            source_game_patch=None, league="current", offline=True, prior_run=None
        )
    assert (
        research_workflow._source_patch_for_run(
            source_game_patch="0.5.4", league="unknown", offline=True, prior_run=None
        )[0]
        == "0.5.4"
    )
    monkeypatch.setattr(
        research_workflow.freshness_service,
        "get_freshness_report",
        lambda **_: {"active_evidence": []},
    )
    with pytest.raises(ValueError, match="unverified"):
        research_workflow._source_patch_for_run(
            source_game_patch=None, league="current", offline=False, prior_run=None
        )
