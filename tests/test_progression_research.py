from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from server import paths
from server.generation import progression_research


VERSION = {
    "league": "Test League",
    "ruleset": "softcore_trade",
    "gamePatch": "0.5.4",
    "passiveTreeVersion": "0_5",
    "pobVersionOrCommit": "pob:test",
    "graphSnapshotId": "graph:test",
    "researchMemoryRef": "dq-0123456789abcdef",
}


def _claim(source_refs: list[str]) -> dict[str, object]:
    return {
        "claimId": "starter-claim:early-skill",
        "claimKind": "skill_package",
        "levelMin": 1,
        "levelMax": 30,
        "summary": "Use the resolved early lightning package.",
        "componentKeys": ["skill:early-lightning"],
        "sourceRefs": source_refs,
        "verificationTasks": ["Resolve the gem and verify the stage in PoB."],
    }


def _source(
    source_id: str,
    url: str,
    *,
    kind: str = "structured_guide",
    patch: str = "0.5.4",
    levels: bool = True,
) -> dict[str, object]:
    return {
        "sourceId": source_id,
        "sourceUrl": url,
        "sourceKind": kind,
        "title": f"Starter guide {source_id}",
        "claimedPatch": patch,
        "explicitLevelBands": levels,
        "summary": "A short starter progression summary with no copied character data.",
    }


def _packet(sources: list[dict[str, object]]) -> dict[str, object]:
    return {
        "baseClass": "Monk",
        "gamePatch": "0.5.4",
        "passiveTreeVersion": "0_5",
        "levelMin": 1,
        "levelMax": 65,
        "networkStatus": "available",
        "sources": sources,
        "claims": [_claim([str(source["sourceId"]) for source in sources])],
        "contradictions": [],
        "unresolvedChecks": ["Verify resource sustain at the second milestone."],
    }


def test_starter_research_hashes_urls_and_supports_exact_patch_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    payload = _packet(
        [
            _source(
                "source:guide-one",
                "https://www.guides.example/monk?account=secret",
            )
        ]
    )

    result = progression_research.intake_starter_research_packet(
        payload,
        version_context=VERSION,
    )

    assert result["status"] == "accepted"
    assert result["starterResearchPacket"]["evidenceStatus"] == "supported"
    serialized = json.dumps(result, ensure_ascii=False)
    assert "https://" not in serialized
    assert "account=secret" not in serialized
    assert "source-url:www.guides.example:" in serialized
    cached_text = next(paths.starter_research_cache_dir().glob("*.json")).read_text(
        encoding="utf-8"
    )
    assert "https://" not in cached_text
    assert "account=secret" not in cached_text
    assert not paths.mature_learning_path().exists()
    assert not paths.comparative_learning_memory_path().exists()

    hit = progression_research.lookup_starter_research_cache(
        base_class="Monk",
        game_patch="0.5.4",
        passive_tree_version="0_5",
    )
    assert hit["status"] == "hit"
    assert hit["mayAdoptWithoutRevalidation"] is True

    expired = progression_research.lookup_starter_research_cache(
        base_class="Monk",
        game_patch="0.5.4",
        passive_tree_version="0_5",
        now=datetime.now(timezone.utc) + timedelta(days=8),
    )
    assert expired["status"] == "stale"
    assert expired["mayAdoptWithoutRevalidation"] is False


def test_aggregator_alone_is_limited_and_cross_season_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    result = progression_research.intake_starter_research_packet(
        _packet(
            [
                _source(
                    "source:index-one",
                    "https://index.example/list",
                    kind="aggregator",
                )
            ]
        ),
        version_context=VERSION,
    )
    assert result["starterResearchPacket"]["evidenceStatus"] == "limited"

    cross_season = progression_research.lookup_starter_research_cache(
        base_class="Monk",
        game_patch="0.6.0",
        passive_tree_version="0_6",
    )
    assert cross_season["status"] == "miss"
    assert cross_season["cacheStatus"] == "cross_season_rejected"
    assert "starterResearchPacket" not in cross_season


def test_current_patch_creator_guide_can_support_but_claim_ids_and_ranges_are_bounded(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    payload = _packet(
        [
            _source(
                "source:creator-one",
                "https://creator.example/monk",
                kind="creator_guide",
            )
        ]
    )
    accepted = progression_research.intake_starter_research_packet(
        payload,
        version_context=VERSION,
    )
    assert accepted["starterResearchPacket"]["evidenceStatus"] == "supported"

    duplicate = _packet([_source("source:guide-one", "https://guides.example/monk")])
    duplicate["claims"] = [duplicate["claims"][0], duplicate["claims"][0]]
    rejected_duplicate = progression_research.intake_starter_research_packet(
        duplicate,
        version_context=VERSION,
    )
    assert rejected_duplicate["errorCode"] == "invalid_starter_research_packet"

    outside_range = _packet([_source("source:guide-two", "https://guides.example/monk-two")])
    outside_range["claims"][0]["levelMax"] = 80
    rejected_range = progression_research.intake_starter_research_packet(
        outside_range,
        version_context=VERSION,
    )
    assert rejected_range["errorCode"] == "invalid_starter_research_packet"


def test_offline_inference_is_safe_and_raw_web_fields_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    offline = {
        "baseClass": "Monk",
        "gamePatch": "0.5.4",
        "passiveTreeVersion": "0_5",
        "levelMin": 1,
        "levelMax": 65,
        "networkStatus": "unavailable",
        "sources": [],
        "claims": [_claim([])],
        "contradictions": [],
        "unresolvedChecks": ["All community premises require later revalidation."],
    }
    result = progression_research.intake_starter_research_packet(
        offline,
        version_context=VERSION,
    )
    assert result["status"] == "accepted"
    assert result["starterResearchPacket"]["evidenceStatus"] == ("limited_offline_inference")

    unsafe = _packet([_source("source:guide-one", "https://guides.example/monk")])
    unsafe["rawHtml"] = "<html>copied page</html>"
    rejected = progression_research.intake_starter_research_packet(
        unsafe,
        version_context=VERSION,
    )
    assert rejected["status"] == "rejected"
    assert rejected["errorCode"] == "invalid_starter_research_packet"

    hidden_url = _packet([_source("source:guide-two", "https://guides.example/monk")])
    hidden_url["sources"][0]["summary"] = "Mirror at https://other.example/full-guide"
    rejected_url = progression_research.intake_starter_research_packet(
        hidden_url,
        version_context=VERSION,
    )
    assert rejected_url["errorCode"] == "invalid_starter_research_packet"
