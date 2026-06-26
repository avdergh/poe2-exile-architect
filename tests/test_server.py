"""Server-surface tests: the assistant-facing cohesion layer (instructions + prompts).

These guard the MCP `instructions` channel and the workflow prompts — the only guidance the
LLM client receives beyond per-tool docstrings. They run without booting the engine.
"""

from __future__ import annotations

import asyncio

from server.main import mcp


def test_instructions_are_delivered():
    instr = mcp.instructions or ""
    # Sourced from server/ASSISTANT_GUIDE.md; must actually reach the client, not be empty.
    assert len(instr) > 500
    assert "Path of Exile 2" in instr
    # The cardinal rule has to survive — it's why answers stay grounded in the engine.
    assert "never" in instr.lower() and "engine" in instr.lower()
    # Phase 3 lifecycle guidance must reach the client: strong endgame builds may need a
    # separate starter route and explicit transition gates.
    assert "lifecycle" in instr.lower()
    assert "transition gate" in instr.lower()


def test_workflow_prompts_registered():
    prompts = {p.name for p in asyncio.run(mcp.list_prompts())}
    assert {"start_build_session", "analyze_build", "build_from_goal", "audit_defenses"} <= prompts


def test_tool_surface_intact():
    tools = asyncio.run(mcp.list_tools())
    assert len(tools) == 71
    names = {t.name for t in tools}
    assert {
        "list_jewel_sockets",
        "equip_jewel",
        "apply_combat_profile",
        "pinnacle_readiness",
        "list_reference_builds",
        "benchmark_build",
        "rank_upgrades",
        "optimize_supports",
        "optimize_jewel",
        "plan_gear",
        "relevant_uniques",
        "optimize_build",
        "craft_item",
        "get_freshness_report",
        "suggest_build_lifecycle",
        "analyze_build_lifecycle",
        "compare_lifecycle_routes",
        "list_transition_gates",
        "record_build_feedback",
        "promote_technique_memory",
    } <= names


def test_freshness_report_tool_exposes_force_refresh_schema():
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}

    schema = tools["get_freshness_report"].inputSchema

    assert schema["properties"]["force_refresh"]["type"] == "boolean"
    assert schema["properties"]["force_refresh"]["default"] is False


def test_get_freshness_report_forwards_force_refresh(monkeypatch):
    from server import main

    captured: dict[str, bool] = {}

    def fake_report(*, force_refresh: bool = False):
        captured["force_refresh"] = force_refresh
        return {"decision": "verified_current"}

    monkeypatch.setattr(main.freshness_service, "get_freshness_report", fake_report)

    assert main.get_freshness_report(force_refresh=True) == {"decision": "verified_current"}
    assert captured == {"force_refresh": True}


def test_suggest_build_lifecycle_uses_freshness_and_meta(monkeypatch, tmp_path):
    from server import main

    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path))
    monkeypatch.setattr(
        main.freshness_service,
        "get_freshness_report",
        lambda: {"decision": "verified_current", "blockers": [], "warnings": []},
    )
    monkeypatch.setattr(
        main.live_meta,
        "get_meta_builds",
        lambda limit=5: {"ok": True, "source": "poe.ninja", "limit": limit},
    )

    result = main.suggest_build_lifecycle("给我一个新手能玩的强力终局BD")

    assert result["ok"] is True
    assert result["freshness"]["decision"] == "verified_current"
    assert result["metaContext"]["source"] == "poe.ninja"
    assert result["buildId"] in main.lifecycle.load_memory()["lifecycle_builds"]


def test_check_data_version_calls_service_once_and_nests_legacy_probe(monkeypatch):
    from server import main

    calls = 0
    strict = {
        "decision": "blocked_unknown",
        "evidence": [],
        "active_evidence": [],
        "blockers": ["required component game_patch has no evidence"],
        "warnings": [],
        "evaluated_at": "2026-06-24T12:00:00+00:00",
        "providers": [],
        "provider_status": [],
    }

    def fake_report():
        nonlocal calls
        calls += 1
        return strict

    monkeypatch.setattr(main.freshness_service, "get_freshness_report", fake_report)
    monkeypatch.setattr(
        main.live_version,
        "check_data_version",
        lambda: {"recommendation": "up_to_date"},
    )

    result = main.check_data_version()

    assert calls == 1
    assert result["recommendation"] == "blocked_unknown"
    assert result["freshness"] == strict
    assert result["legacy_corpus_probe"] == {"recommendation": "up_to_date"}


def test_apply_combat_profile_sets_conditions(monkeypatch):
    from server import main

    captured: dict = {}

    class _Stub:
        def set_config(self, options=None, custom_mods=None):
            captured["options"] = options
            return {"stats": {"TotalDPS": 1}}

    monkeypatch.setattr(main, "get_engine", lambda: _Stub())
    r = main.apply_combat_profile(tier="Pinnacle", shocked=True, cursed=False)
    opts = captured["options"]
    assert opts["enemyIsBoss"] == "Pinnacle"
    assert opts.get("conditionEnemyShocked") is True
    assert "conditionEnemyCursed" not in opts  # cursed=False omitted
    assert r["assumptions"] and any("Shocked" in a for a in r["assumptions"])


def test_pinnacle_readiness_gate(monkeypatch):
    from server import main

    class _Stub:
        def get_defenses(self):
            return {
                "resistances": {"fire": 75, "cold": 75, "lightning": 75, "chaos": 40},
                "resistOverCap": {"fire": 10, "cold": 8, "lightning": 12},
                "totalEHP": 30000,
            }

        def get_build(self):
            return {"keystones": [], "stats": {"FullDPS": 600000, "TotalDPS": 50000}}

    monkeypatch.setattr(main, "get_engine", lambda: _Stub())
    r = main.pinnacle_readiness(min_ehp=25000, min_dps=500000)
    assert r["pass"] is False  # chaos 40, not CI -> fails the chaos check
    checks = {c["check"]: c for c in r["checks"]}
    assert checks["elemental resists capped (75%)"]["ok"]  # DPS uses FullDPS (600k >= 500k)

    class _CI(_Stub):
        def get_build(self):
            d = _Stub.get_build(self)
            d["keystones"] = ["Chaos Inoculation"]
            return d

    monkeypatch.setattr(main, "get_engine", lambda: _CI())
    assert main.pinnacle_readiness(min_ehp=25000, min_dps=500000)["pass"] is True


def test_equip_item_flags_illegal_affixes(monkeypatch):
    # The legality wiring: a body-armour "% maximum Mana" affix surfaces a warning (engine stubbed,
    # so this tests the corpus check + merge, not the calc).
    from server import main

    class _Stub:
        def add_item(self, raw, slot=None):
            return {"ok": True, "slot": slot or "Body Armour", "stats": {"TotalDPS": 1.0}}

    monkeypatch.setattr(main, "get_engine", lambda: _Stub())
    monkeypatch.setattr(
        main.corpus,
        "get_item",
        lambda name: {"name": name} if name == "Sacramental Robe" else None,
    )
    monkeypatch.setattr(
        main.corpus,
        "illegal_affixes",
        lambda base, affixes: [{"text": affixes[0]}],
    )
    raw = (
        "Rarity: Rare\nFantasy Plate\nSacramental Robe\n--------\n"
        "60% increased maximum Mana\n+40% to Fire Resistance"
    )
    res = main.equip_item(raw, slot="Body Armour")
    assert res.get("illegalAffixes")
    assert "Sacramental Robe" in (res.get("legalityWarning") or "")


def test_equip_item_clean_gear_has_no_warning(monkeypatch):
    from server import main

    class _Stub:
        def add_item(self, raw, slot=None):
            return {"ok": True, "slot": slot or "Ring 1", "stats": {}}

    monkeypatch.setattr(main, "get_engine", lambda: _Stub())
    monkeypatch.setattr(
        main.corpus,
        "get_item",
        lambda name: {"name": name} if name == "Sapphire Ring" else None,
    )
    monkeypatch.setattr(main.corpus, "illegal_affixes", lambda base, affixes: [])
    raw = (
        "Rarity: Rare\nGood Ring\nSapphire Ring\n--------\n"
        "+140 to maximum Mana\n+42% to Lightning Resistance"
    )
    res = main.equip_item(raw, slot="Ring 1")
    assert "illegalAffixes" not in res and "legalityWarning" not in res


def test_import_caveats_flag_aspirational_pob():
    from server import main

    class _Stub:
        def get_build(self):
            return {
                "customMods": "+111% to Fire Resistance",
                "pointsUsed": 140,
                "pointsAvailable": 116,
                "level": 93,
                "keystones": [],
            }

        def get_defenses(self):
            return {"resistances": {"fire": 66, "cold": 66, "lightning": 66, "chaos": 33}}

    joined = " ".join(main._import_caveats(_Stub())).lower()
    assert "custom mods" in joined
    assert "over budget" in joined
    assert "below the 75% cap" in joined and "chaos 33" in joined

    class _CI(_Stub):
        def get_build(self):
            d = _Stub.get_build(self)
            d["keystones"] = ["Chaos Inoculation"]
            return d

    ci = " ".join(main._import_caveats(_CI())).lower()
    assert "chaos" not in ci  # chaos resist is irrelevant under Chaos Inoculation


def test_meta_builds_shape():
    # Network-free: exercise the league selection + formatting on a sample payload.
    from server.live import meta

    sample = {
        "leagueBuilds": [
            {
                "leagueName": "Runes of Aldur",
                "leagueUrl": "runesofaldur",
                "total": 124269,
                "statistics": [
                    {"class": "Martial Artist", "percentage": 24.5, "trend": 1},
                    {"class": "Spirit Walker", "percentage": 17.7, "trend": -1},
                ],
            },
            {"leagueName": "HC Runes of Aldur", "total": 5000, "statistics": []},
            {"leagueName": "Standard", "total": 999999, "statistics": []},
        ]
    }
    r = meta.shape(sample, limit=5)
    # defaults to the main softcore challenge league, not Standard/HC (despite Standard's total)
    assert r["ok"] and r["league"] == "Runes of Aldur" and r["sampleSize"] == 124269
    assert r["ascendancies"][0]["ascendancy"] == "Martial Artist"
    assert r["ascendancies"][0]["trend"] == "rising" and r["ascendancies"][1]["trend"] == "falling"
    assert meta.shape(sample, league="Standard")["league"] == "Standard"  # explicit override
    assert meta.shape(sample, league="Nope")["ok"] is False  # not found


def test_build_advice_sections():
    from server.knowledge import advice

    overview = advice.advise()
    assert overview["topics"]
    assert "engine" in overview["intro"].lower()  # framing: numbers come from the engine
    # the durable resistance-cap rule must survive in the defense section
    assert "75%" in advice.advise("defense")["text"]
    # fuzzy keyword match resolves a query that isn't a section title
    assert advice.advise("crit").get("topic")


def test_server_version_reads_utf8_manifest(monkeypatch):
    import json
    from pathlib import Path

    from server import paths
    from server.main import _server_version

    manifest = paths.BUNDLE_ROOT / "manifest.json"
    expected = json.loads(manifest.read_text(encoding="utf-8"))["version"]
    original_read_text = Path.read_text
    observed_encoding = None

    def recording_read_text(path, *args, **kwargs):
        nonlocal observed_encoding
        if path == manifest:
            observed_encoding = kwargs.get("encoding") or (args[0] if args else None)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", recording_read_text)
    assert _server_version() == expected
    assert observed_encoding == "utf-8"
