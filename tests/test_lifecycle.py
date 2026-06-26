"""Lifecycle-build research tests.

These tests describe the Phase 3A contract: a build is no longer a single static PoB
snapshot, but a staged route with transition gates and feedback memory.
"""

from __future__ import annotations

from server.knowledge import lifecycle


def test_terminal_unique_dependency_is_not_marked_as_starter_to_endgame():
    result = lifecycle.classify_lifecycle(
        {
            "critical_uniques": ["Dream Fragment"],
            "low_level_viable": False,
            "starter_route_available": False,
            "endgame_scaling": True,
        }
    )

    assert result["classification"] == "endgame_only"
    assert result["starter_viable"] is False
    assert any("critical unique" in reason.lower() for reason in result["reasons"])


def test_low_dependency_scaling_build_is_starter_to_endgame():
    result = lifecycle.classify_lifecycle(
        {
            "critical_uniques": [],
            "low_level_viable": True,
            "starter_route_available": True,
            "endgame_scaling": True,
        }
    )

    assert result["classification"] == "starter_to_endgame"
    assert result["starter_viable"] is True


def test_research_build_lifecycle_returns_staged_route_and_transition_gates():
    result = lifecycle.research_build_lifecycle(
        "给我一个强力但新手能看懂的闪电终局BD",
        freshness={"decision": "verified_current", "blockers": [], "warnings": []},
        meta={"ok": True, "source": "poe.ninja", "league": "Runes of Aldur"},
    )

    stage_ids = [stage["id"] for stage in result["stages"]]

    assert result["ok"] is True
    assert result["buildId"].startswith("life-")
    assert result["classification"] in {"starter_then_transition", "starter_to_endgame"}
    assert {"campaign_early", "campaign_mid", "maps_entry", "endgame_final"} <= set(stage_ids)
    assert len(result["transitionGates"]) >= 3
    assert result["researchPlan"]["steps"] == [
        "freshness_gate",
        "question_development",
        "evidence_collection",
        "evidence_extraction",
        "cohort_analysis",
        "lifecycle_synthesis",
        "pob_verification",
        "memory_promotion",
    ]
    assert all(stage["evidenceTags"] for stage in result["stages"])


def test_research_build_lifecycle_uses_goal_specific_skill_evidence(monkeypatch):
    monkeypatch.setattr(
        lifecycle.corpus,
        "find_skills",
        lambda query="", gem_type=None, limit=5, **_kw: (
            [
                {
                    "name": f"{query.title()} Spear",
                    "tags": [query, "attack"],
                    "gem_type": gem_type,
                }
            ]
            if query == "lightning"
            else []
        ),
    )

    result = lifecycle.research_build_lifecycle(
        "我想玩闪电终局BD",
        preferences="远程",
        budget="低预算",
        freshness={"decision": "verified_current"},
    )

    assert result["evidence"]["skillCandidates"][0]["name"] == "Lightning Spear"
    assert result["constraints"]["budget"] == "低预算"
    assert "Lightning Spear" in result["stages"][0]["skillPlan"]


def test_lifecycle_cohort_extracts_reference_patterns_and_live_meta(monkeypatch):
    from server.knowledge import lifecycle_cohort

    monkeypatch.setattr(
        lifecycle_cohort.refbuilds,
        "search",
        lambda query="", limit=8: {
            "count": 2,
            "builds": [
                {
                    "ascendancy": "Stormweaver",
                    "mainSkill": "Lightning Spear",
                    "damageTypes": ["lightning"],
                    "delivery": ["spell", "projectile"],
                    "defenseIdentity": "ES recharge",
                    "dominantLever": "+levels to skills",
                    "topLevers": [
                        {"lever": "+levels to skills"},
                        {"lever": "critical multiplier"},
                    ],
                },
                {
                    "ascendancy": "Stormweaver",
                    "mainSkill": "Spark",
                    "damageTypes": ["lightning"],
                    "delivery": ["spell", "projectile"],
                    "defenseIdentity": "ES recharge",
                    "dominantLever": "+levels to skills",
                    "topLevers": [{"lever": "+levels to skills"}, {"lever": "cast speed"}],
                },
            ],
        },
    )

    cohort = lifecycle_cohort.analyze_goal_cohort(
        goal="闪电远程终局BD",
        skill_candidates=[{"name": "Lightning Spear", "query": "lightning"}],
        meta={
            "ok": True,
            "source": "poe.ninja",
            "league": "Runes of Aldur",
            "ascendancies": [{"ascendancy": "Stormweaver", "percentage": 18.5, "trend": "rising"}],
        },
        limit=4,
    )

    assert cohort["ok"] is True
    assert cohort["sampleSize"] == 2
    assert cohort["commonLevers"][0]["name"] == "+levels to skills"
    assert cohort["commonDamageTypes"][0]["name"] == "lightning"
    assert cohort["ascendancyContext"][0]["ascendancy"] == "Stormweaver"
    assert cohort["ascendancyContext"][0]["liveMeta"]["percentage"] == 18.5
    assert "reference-cohort" in cohort["evidenceTags"]
    assert "live-meta" in cohort["evidenceTags"]


def test_research_build_lifecycle_includes_cohort_hints(monkeypatch):
    monkeypatch.setattr(
        lifecycle.corpus,
        "find_skills",
        lambda query="", gem_type=None, limit=5, **_kw: [
            {"name": "Lightning Spear", "tags": ["lightning", "projectile"]}
        ],
    )
    monkeypatch.setattr(
        lifecycle.lifecycle_cohort,
        "analyze_goal_cohort",
        lambda **_kw: {
            "ok": True,
            "sampleSize": 1,
            "referenceMatches": [{"mainSkill": "Lightning Spear", "ascendancy": "Stormweaver"}],
            "commonLevers": [{"name": "+levels to skills", "count": 1}],
            "commonDamageTypes": [{"name": "lightning", "count": 1}],
            "commonDelivery": [{"name": "projectile", "count": 1}],
            "commonDefenses": [{"name": "ES recharge", "count": 1}],
            "ascendancyContext": [{"ascendancy": "Stormweaver", "referenceCount": 1}],
            "warnings": [],
            "evidenceTags": ["reference-cohort", "live-meta"],
        },
    )

    result = lifecycle.research_build_lifecycle(
        "给我一个闪电远程终局BD",
        meta={"ok": True, "ascendancies": []},
    )

    assert result["cohortAnalysis"]["sampleSize"] == 1
    endgame = next(stage for stage in result["stages"] if stage["id"] == "endgame_final")
    assert "+levels to skills" in " ".join(endgame["cohortHints"])
    assert "reference-cohort" in endgame["evidenceTags"]


def test_stage_verification_plan_for_maps_entry_requires_resists_and_sustain():
    from server.knowledge import lifecycle_verification

    plan = lifecycle_verification.plan_stage_verification("maps_entry")

    assert plan["ok"] is True
    assert plan["stage"] == "maps_entry"
    assert plan["levelTarget"] >= 65
    assert "get_defenses" in plan["engineTools"]
    assert "resists_capped" in plan["targetChecks"]
    assert "sustain_ok" in plan["targetChecks"]


def test_research_build_lifecycle_attaches_concrete_stage_verification():
    result = lifecycle.research_build_lifecycle("给我一个新手能懂的终局BD")
    maps_entry = next(stage for stage in result["stages"] if stage["id"] == "maps_entry")

    assert maps_entry["verification"]["status"] == "planned"
    assert maps_entry["verification"]["levelTarget"] >= 65
    assert "gearAssumption" in maps_entry["verification"]
    assert "evaluate_build" in maps_entry["verification"]["engineTools"]


def test_verify_stage_metrics_fails_maps_entry_when_resists_and_sustain_are_low():
    from server.knowledge import lifecycle_verification

    result = lifecycle_verification.verify_stage_metrics(
        "maps_entry",
        stats={"TotalDPS": 20000, "Life": 1200, "Mana": 40, "ManaCost": 80},
        defenses={
            "resistances": {"fire": 55, "cold": 76, "lightning": 70},
            "totalEHP": 2400,
        },
    )

    assert result["ok"] is True
    assert result["pass"] is False
    assert result["status"] == "failed"
    assert {"resists_capped", "basic_defense_online", "sustain_ok"} <= set(result["failedChecks"])
    assert "engine-computed" in result["evidenceTags"]


def test_verify_stage_metrics_passes_maps_entry_with_engine_values():
    from server.knowledge import lifecycle_verification

    result = lifecycle_verification.verify_stage_metrics(
        "maps_entry",
        stats={"TotalDPS": 90000, "Life": 2600, "Mana": 500, "ManaCost": 40},
        defenses={
            "resistances": {"fire": 75, "cold": 79, "lightning": 76},
            "totalEHP": 12000,
        },
    )

    assert result["pass"] is True
    assert result["status"] == "passed"
    assert result["failedChecks"] == []


def test_verify_stage_metrics_returns_repair_actions_for_failed_maps_entry():
    from server.knowledge import lifecycle_verification

    result = lifecycle_verification.verify_stage_metrics(
        "maps_entry",
        stats={"Life": 1200, "Mana": 40, "ManaCost": 80},
        defenses={
            "resistances": {"fire": 55, "cold": 76, "lightning": 70},
            "totalEHP": 2400,
        },
    )

    joined = " ".join(result["recommendedActions"]).lower()
    assert "resist" in joined
    assert "sustain" in joined or "mana" in joined
    assert "transition" in joined


def test_verify_stage_metrics_returns_actions_for_unknown_endgame_checks():
    from server.knowledge import lifecycle_verification

    result = lifecycle_verification.verify_stage_metrics(
        "endgame_budget",
        stats={"Life": 4000, "Mana": 500, "ManaCost": 30},
        defenses={
            "resistances": {"fire": 75, "cold": 75, "lightning": 75},
            "totalEHP": 14000,
        },
    )

    joined = " ".join(result["recommendedActions"]).lower()
    assert "build-defining" in joined
    assert result["status"] == "unknown"


def test_transition_gate_blocks_missing_requirements():
    gate = lifecycle.make_transition_gate(
        "maps_entry",
        "endgame_budget",
        required_level=75,
        required_items=["关键暗金戒指"],
        required_checks={"resists_capped": True},
    )

    result = lifecycle.evaluate_transition_gate(
        gate,
        {"level": 72, "items": [], "checks": {"resists_capped": False}},
    )

    assert result["ready"] is False
    assert "level 75" in " ".join(result["missing"]).lower()
    assert "关键暗金戒指" in " ".join(result["missing"])
    assert "resists_capped" in " ".join(result["missing"])


def test_transition_readiness_blocks_missing_gate_requirements_and_feedback():
    result = lifecycle.evaluate_transition_readiness(
        from_stage="maps_entry",
        to_stage="endgame_budget",
        state={
            "level": 72,
            "items": [],
            "checks": {
                "resists_capped": False,
                "sustain_ok": False,
                "pob_model_supported": True,
            },
            "feedback": "进图缺蓝，不能维持输出。",
        },
    )

    assert result["ok"] is True
    assert result["ready"] is False
    assert result["recommendation"] == "hold_current_stage"
    assert "level 75" in " ".join(result["missing"]).lower()
    assert result["feedbackPattern"] == "sustain_gap"
    assert any("sustain" in action.lower() for action in result["recommendedActions"])


def test_transition_readiness_uses_stored_build_gates(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path))
    route = lifecycle.research_build_lifecycle("闪电终局BD", persist=True)

    result = lifecycle.evaluate_transition_readiness(
        build_id=route["buildId"],
        from_stage="maps_entry",
        to_stage="endgame_budget",
        state={
            "level": 75,
            "items": ["build-defining unique or equivalent rare affix"],
            "checks": {
                "resists_capped": True,
                "sustain_ok": True,
                "pob_model_supported": True,
            },
        },
    )

    assert result["ready"] is True
    assert result["recommendation"] == "transition_allowed"
    assert result["source"] == "stored"


def test_analyze_imported_gear_marks_known_uniques_as_endgame_dependency(monkeypatch):
    monkeypatch.setattr(
        lifecycle,
        "_known_unique",
        lambda name, base=None: {"name": name, "base": base} if name == "Endgame Idol" else None,
    )

    result = lifecycle.analyze_build_lifecycle(
        "imported",
        imported_build={
            "level": 90,
            "mainSkill": "Example Nuke",
            "gear": {"Ring 1": {"name": "Endgame Idol", "base": "Ruby Ring"}},
        },
    )

    assert result["classification"] == "starter_then_transition"
    assert result["starterViable"] is True
    assert any("Endgame Idol" in reason for reason in result["classificationReasons"])


def test_lifecycle_source_evidence_extracts_starter_transition_and_endgame_signals(
    monkeypatch,
):
    from server.knowledge import lifecycle_evidence

    monkeypatch.setattr(
        lifecycle_evidence.corpus,
        "find_skills",
        lambda query="", gem_type=None, limit=30, **_kw: (
            [{"name": "Spark", "gem_type": "active", "tags": ["lightning"]}]
            if query.lower() == "spark"
            else []
        ),
    )
    monkeypatch.setattr(
        lifecycle_evidence.corpus,
        "search_uniques",
        lambda query="", limit=20, **_kw: (
            [{"name": "Dream Fragment", "base": "Sapphire Ring", "item_type": "ring"}]
            if query.lower() == "dream fragment"
            else []
        ),
    )

    evidence = lifecycle_evidence.extract_lifecycle_source_evidence(
        "Level with Spark through campaign. Switch at level 75 when Dream Fragment is equipped. "
        "Final endgame setup is not a starter."
    )

    assert "campaign_early" in evidence["stageSignals"]
    assert "endgame_final" in evidence["stageSignals"]
    assert evidence["skillCandidates"][0]["name"] == "Spark"
    assert evidence["uniqueCandidates"][0]["name"] == "Dream Fragment"
    assert evidence["transitionHints"][0]["level"] == 75
    assert "required_unique_language" in evidence["riskFlags"]


def test_analyze_build_lifecycle_uses_source_evidence_when_import_is_unavailable(
    monkeypatch,
):
    monkeypatch.setattr(
        lifecycle.lifecycle_evidence,
        "extract_lifecycle_source_evidence",
        lambda source: {
            "stageSignals": ["campaign_early", "endgame_final"],
            "lifecycleHints": ["starter_route", "endgame_form"],
            "uniqueCandidates": [{"name": "Dream Fragment"}],
            "skillCandidates": [{"name": "Spark"}],
            "transitionHints": [{"level": 75, "snippet": "Switch at level 75"}],
            "riskFlags": ["required_unique_language"],
            "evidenceTags": ["external-guide", "corpus", "lifecycle-source-extraction"],
        },
    )

    result = lifecycle.analyze_build_lifecycle("guide text", import_error="not a pob")

    assert result["ok"] is False
    assert result["classification"] == "starter_then_transition"
    assert result["sourceEvidence"]["uniqueCandidates"][0]["name"] == "Dream Fragment"


def test_analyze_build_lifecycle_synthesizes_source_transition_gate(monkeypatch):
    monkeypatch.setattr(
        lifecycle.lifecycle_evidence,
        "extract_lifecycle_source_evidence",
        lambda source: {
            "stageSignals": ["campaign_early", "endgame_final"],
            "lifecycleHints": ["starter_route", "transition_required", "endgame_form"],
            "uniqueCandidates": [{"name": "Dream Fragment"}],
            "skillCandidates": [{"name": "Spark"}],
            "transitionHints": [
                {"level": 75, "snippet": "Switch at level 75 when Dream Fragment is equipped."}
            ],
            "riskFlags": ["required_unique_language"],
            "evidenceTags": ["external-guide", "corpus", "lifecycle-source-extraction"],
        },
    )

    result = lifecycle.analyze_build_lifecycle("guide text", import_error="not a pob")

    gate = result["sourceTransitionGates"][0]
    assert gate["source"] == "source-evidence"
    assert gate["fromStage"] == "maps_entry"
    assert gate["toStage"] == "endgame_budget"
    assert gate["requirements"]["level"] == 75
    assert gate["requirements"]["items"] == ["Dream Fragment"]
    assert "resists_capped" in gate["requirements"]["checks"]


def test_feedback_is_episodic_until_promoted(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path))

    feedback = lifecycle.record_build_feedback(
        build_id="life-test",
        stage="maps_entry",
        feedback="进异界后经常暴毙，抗性没满。",
        outcome="补抗性和生命后稳定。",
    )
    store = lifecycle.load_memory()

    assert feedback["memoryType"] == "episodic"
    assert feedback["promotionEligible"] is False
    assert store["feedback_reflections"]
    assert store["technique_cards"] == {}

    promoted = lifecycle.promote_technique_memory(
        evidence_ids=[feedback["feedbackId"]],
        reason="多次反馈证明：进异界前必须先补满元素抗性。",
        current_patch="0.5.4",
        current_tree="0_5",
    )
    store = lifecycle.load_memory()

    assert promoted["ok"] is True
    assert promoted["memoryType"] == "durable_technique"
    assert len(store["technique_cards"]) == 1
    card = next(iter(store["technique_cards"].values()))
    assert card["patch"] == "0.5.4"
    assert card["passiveTree"] == "0_5"


def test_record_build_feedback_returns_stage_repair_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path))

    result = lifecycle.record_build_feedback(
        build_id="life-test",
        stage="maps_entry",
        feedback="刚进异界暴毙，抗性也没满。",
    )

    assert result["failurePattern"] == "defense_gap"
    assert any("resist" in action.lower() for action in result["recommendedActions"])


def test_promote_technique_rejects_missing_evidence_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path))

    feedback = lifecycle.record_build_feedback(
        build_id="life-test",
        stage="maps_entry",
        feedback="伤害很低，boss 打得很慢。",
    )

    result = lifecycle.promote_technique_memory(
        evidence_ids=[feedback["feedbackId"], "fb-missing"],
        reason="missing evidence should block promotion",
    )

    assert result["ok"] is False
    assert result["missingEvidenceIds"] == ["fb-missing"]
    assert lifecycle.load_memory()["technique_cards"] == {}


def test_current_compatibility_claim_prefers_installed_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path))
    (tmp_path / "installed.json").write_text(
        '{"game_patch":"9.9.9","passive_tree":"9_9","pob_commit":"abc"}',
        encoding="utf-8",
    )

    claim = lifecycle.current_compatibility_claim()

    assert claim["game_patch"] == "9.9.9"
    assert claim["passive_tree"] == "9_9"


def test_feedback_ids_do_not_collide_within_same_second(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path))
    monkeypatch.setattr(lifecycle, "_now", lambda: "2026-06-26T00:00:00+00:00")

    first = lifecycle.record_build_feedback("life-test", "maps_entry", "伤害不足")
    second = lifecycle.record_build_feedback("life-test", "maps_entry", "伤害不足")

    assert first["feedbackId"] != second["feedbackId"]
    assert len(lifecycle.load_memory()["feedback_reflections"]) == 2
