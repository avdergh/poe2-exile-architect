"""Lifecycle build research and local learning memory.

Phase 3 treats a PoE2 build as a route through time: campaign starter, transition
gates, and endgame form. This module deliberately stays in the knowledge layer:
it records evidence, structures research, and stores feedback, while PoB remains
the only source for computed build numbers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from .. import paths
from . import db as corpus
from . import lifecycle_cohort
from . import lifecycle_evidence
from . import lifecycle_verification

STAGES: tuple[dict[str, Any], ...] = (
    {
        "id": "campaign_early",
        "label": "Campaign early",
        "levelRange": "1-25",
        "purpose": "低依赖开局：技能易得、装备不绑定暗金，先保证手感和清怪。",
    },
    {
        "id": "campaign_mid",
        "label": "Campaign mid",
        "levelRange": "25-45",
        "purpose": "第一次升华/关键辅助后形成临时主轴，但仍避免昂贵绑定。",
    },
    {
        "id": "campaign_late",
        "label": "Campaign late",
        "levelRange": "45-65",
        "purpose": "剧情后期补单体、补抗性、补基础防御，准备进入异界。",
    },
    {
        "id": "maps_entry",
        "label": "Maps entry",
        "levelRange": "65-75",
        "purpose": "刚进异界：先让抗性、防御和 sustain 达标，不急着换毕业机制。",
    },
    {
        "id": "endgame_budget",
        "label": "Budget endgame",
        "levelRange": "75-90",
        "purpose": "有基础交易/关键装备后再转型，开始堆主要乘区和机制阈值。",
    },
    {
        "id": "endgame_final",
        "label": "Final endgame",
        "levelRange": "90+",
        "purpose": "毕业或近毕业形态：允许昂贵暗金、珠宝、阈值堆叠和精细配置。",
    },
)

RESEARCH_STEPS = [
    "freshness_gate",
    "question_development",
    "evidence_collection",
    "evidence_extraction",
    "cohort_analysis",
    "lifecycle_synthesis",
    "pob_verification",
    "memory_promotion",
]

_MEMORY_KEYS = (
    "lifecycle_builds",
    "transition_gates",
    "technique_cards",
    "failure_patterns",
    "feedback_reflections",
)
_MEMORY_LOCK = threading.RLock()
_GOAL_QUERY_ALIASES = {
    "闪电": "lightning",
    "雷": "lightning",
    "火": "fire",
    "冰": "cold",
    "冰霜": "cold",
    "混沌": "chaos",
    "物理": "physical",
    "召唤": "minion",
    "投射物": "projectile",
    "远程": "projectile",
    "近战": "melee",
}
_QUERY_STOPWORDS = {
    "bd",
    "build",
    "poe2",
    "强力",
    "终局",
    "毕业",
    "新手",
    "开荒",
    "低预算",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _short_hash(text: str, prefix: str) -> str:
    return f"{prefix}-{hashlib.sha1(text.encode('utf-8')).hexdigest()[:12]}"


def _goal_terms(goal: str) -> set[str]:
    return set(re.findall(r"[\w\u4e00-\u9fff]+", (goal or "").lower()))


def _has_any(text: str, words: set[str]) -> bool:
    low = (text or "").lower()
    terms = _goal_terms(low)
    return bool(terms & words) or any(word in low for word in words)


def _empty_memory() -> dict[str, Any]:
    return {"schema_version": 1, **{key: {} for key in _MEMORY_KEYS}}


def load_memory() -> dict[str, Any]:
    """Load local lifecycle memory, tolerating older/missing files.

    The JSON store is intentionally simple for Phase 3A. It gives the agent a durable
    learning surface without committing us to a heavy vector/graph dependency before the
    research workflow has stabilized.
    """
    p = paths.lifecycle_memory_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except OSError:
        return _empty_memory()
    except ValueError:
        _backup_corrupt_memory(p)
        return _empty_memory()
    if not isinstance(data, dict):
        return _empty_memory()
    data.setdefault("schema_version", 1)
    for key in _MEMORY_KEYS:
        if not isinstance(data.get(key), dict):
            data[key] = {}
    return data


def _backup_corrupt_memory(path: Any) -> None:
    """Move unreadable memory aside so later writes do not silently destroy it."""
    try:
        if path.exists():
            backup = path.with_name(
                f"{path.name}.corrupt-{datetime.now(timezone.utc).timestamp():.0f}"
            )
            os.replace(path, backup)
    except OSError:
        pass


def save_memory(memory: dict[str, Any]) -> None:
    """Persist local lifecycle memory with a process-local lock and atomic replace.

    MCP calls can arrive concurrently, and the process may be interrupted mid-write. A
    temp-file + replace keeps the store from being truncated into invalid JSON.
    """
    p = paths.lifecycle_memory_path()
    payload = json.dumps(memory, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with _MEMORY_LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, p)


def classify_lifecycle(features: dict[str, Any]) -> dict[str, Any]:
    """Classify whether a build can level, transition, or only exist at endgame.

    The classifier is deliberately evidence-shaped rather than skill-name-shaped. A future
    research pass can feed it richer signals from imported PoBs, poe.ninja cohorts, or user
    feedback without rewriting the public contract.
    """
    critical_uniques = list(features.get("critical_uniques") or [])
    low_level_viable = bool(features.get("low_level_viable"))
    starter_route_available = bool(features.get("starter_route_available"))
    endgame_scaling = bool(features.get("endgame_scaling"))

    reasons: list[str] = []
    starter_viable = low_level_viable or starter_route_available

    if critical_uniques:
        reasons.append(
            "Requires critical unique or fixed-effect component: "
            + ", ".join(str(x) for x in critical_uniques)
        )
    if not low_level_viable:
        reasons.append("No evidence that the endgame mechanic works during early campaign.")
    if starter_route_available:
        reasons.append("A separate starter route is available before the endgame transition.")
    if endgame_scaling:
        reasons.append("Evidence indicates the route has endgame scaling potential.")

    if critical_uniques and not starter_route_available and not low_level_viable:
        classification = "endgame_only"
        starter_viable = False
    elif critical_uniques and starter_route_available:
        classification = "starter_then_transition"
    elif low_level_viable and endgame_scaling:
        classification = "starter_to_endgame"
    elif low_level_viable:
        classification = "starter_only"
    else:
        classification = "unknown_lifecycle"

    return {
        "classification": classification,
        "starter_viable": starter_viable,
        "reasons": reasons or ["Insufficient lifecycle evidence; treat as unknown until verified."],
    }


def make_transition_gate(
    from_stage: str,
    to_stage: str,
    *,
    required_level: int | None = None,
    required_items: list[str] | None = None,
    required_gems: list[str] | None = None,
    required_ascendancy_points: int | None = None,
    required_checks: dict[str, Any] | None = None,
    caveats: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"gate-{from_stage}-to-{to_stage}",
        "fromStage": from_stage,
        "toStage": to_stage,
        "requirements": {
            "level": required_level,
            "items": required_items or [],
            "gems": required_gems or [],
            "ascendancyPoints": required_ascendancy_points,
            "checks": required_checks or {},
        },
        "caveats": caveats or [],
    }


def evaluate_transition_gate(gate: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Evaluate whether the player should switch stages now.

    Missing requirements are returned as human-readable strings so the LLM can turn them
    into practical advice instead of silently recommending an impossible transition.
    """
    req = gate.get("requirements") or {}
    missing: list[str] = []

    required_level = req.get("level")
    if isinstance(required_level, int) and int(state.get("level") or 0) < required_level:
        missing.append(f"level {required_level}")

    have_items = {str(x).lower() for x in state.get("items") or []}
    for item in req.get("items") or []:
        if str(item).lower() not in have_items:
            missing.append(str(item))

    have_gems = {str(x).lower() for x in state.get("gems") or []}
    for gem in req.get("gems") or []:
        if str(gem).lower() not in have_gems:
            missing.append(str(gem))

    required_points = req.get("ascendancyPoints")
    if (
        isinstance(required_points, int)
        and int(state.get("ascendancyPoints") or 0) < required_points
    ):
        missing.append(f"{required_points} ascendancy points")

    checks = state.get("checks") or {}
    for name, expected in (req.get("checks") or {}).items():
        if checks.get(name) != expected:
            missing.append(f"{name}={expected}")

    return {
        "ready": not missing,
        "gate": gate.get("id"),
        "fromStage": gate.get("fromStage"),
        "toStage": gate.get("toStage"),
        "missing": missing,
        "caveats": gate.get("caveats") or [],
    }


def evaluate_transition_readiness(
    *,
    build_id: str | None = None,
    from_stage: str = "",
    to_stage: str = "",
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate whether the player should transition between lifecycle stages now.

    A failed gate is intentionally blocking: final-form builds can feel terrible before their
    required items/checks are online, so the safe recommendation is to hold the current stage and
    repair the missing layer first.
    """
    if not isinstance(state, dict):
        return {"ok": False, "error": "state must be a dictionary"}
    gates, source = _readiness_gates(build_id)
    gate = _find_gate(gates, from_stage, to_stage)
    if gate is None:
        return {
            "ok": False,
            "error": "transition gate not found",
            "buildId": build_id,
            "fromStage": from_stage,
            "toStage": to_stage,
            "source": source,
        }

    gate_result = evaluate_transition_gate(gate, state)
    feedback = str(state.get("feedback") or "")
    pattern = _failure_pattern(feedback) if feedback.strip() else None
    actions = _recommended_actions(
        from_stage or str(gate.get("fromStage") or ""), pattern, gate_result["missing"]
    )
    ready = bool(gate_result["ready"])
    return {
        "ok": True,
        "buildId": build_id,
        "source": source,
        "ready": ready,
        "recommendation": "transition_allowed" if ready else "hold_current_stage",
        "fromStage": gate_result["fromStage"],
        "toStage": gate_result["toStage"],
        "missing": gate_result["missing"],
        "feedbackPattern": pattern,
        "recommendedActions": actions,
        "caveats": gate_result["caveats"],
        "gate": gate,
        "evidenceTags": ["transition-gate", "user-state"],
    }


def _readiness_gates(build_id: str | None) -> tuple[list[dict[str, Any]], str]:
    if build_id:
        with _MEMORY_LOCK:
            memory = load_memory()
        gates = memory["transition_gates"].get(build_id)
        if gates:
            return list(gates), "stored"
    return _default_gates(), "default"


def _find_gate(
    gates: list[dict[str, Any]], from_stage: str, to_stage: str
) -> dict[str, Any] | None:
    for gate in gates:
        if gate.get("fromStage") == from_stage and gate.get("toStage") == to_stage:
            return gate
    return None


def _default_gates() -> list[dict[str, Any]]:
    return [
        make_transition_gate(
            "campaign_early",
            "campaign_mid",
            required_level=25,
            required_checks={"first_ascendancy_or_key_support": True},
        ),
        make_transition_gate(
            "campaign_mid",
            "campaign_late",
            required_level=45,
            required_checks={"single_target_feels_ok": True},
        ),
        make_transition_gate(
            "campaign_late",
            "maps_entry",
            required_level=65,
            required_checks={"resists_capped": True, "basic_defense_online": True},
        ),
        make_transition_gate(
            "maps_entry",
            "endgame_budget",
            required_level=75,
            required_items=["build-defining unique or equivalent rare affix"],
            required_checks={
                "resists_capped": True,
                "sustain_ok": True,
                "pob_model_supported": True,
            },
        ),
        make_transition_gate(
            "endgame_budget",
            "endgame_final",
            required_level=90,
            required_checks={"core_threshold_met": True, "upgrade_budget_ready": True},
            caveats=[
                "Do not switch if the endgame mechanic is unmodelled or still missing its key item."
            ],
        ),
    ]


def _collect_goal_evidence(goal: str, preferences: str | None = None) -> dict[str, Any]:
    """Collect lightweight goal-specific anchors from the local corpus.

    This is not a full meta cohort analysis yet; it prevents the lifecycle scaffold from being
    completely generic and gives later PoB verification concrete skill candidates to try.
    """
    text = " ".join(x for x in [goal, preferences or ""] if x)
    queries: list[str] = []
    for zh, query in _GOAL_QUERY_ALIASES.items():
        if zh in text and query not in queries:
            queries.append(query)
    for term in _goal_terms(text):
        if len(term) > 2 and term not in _QUERY_STOPWORDS and term not in queries:
            queries.append(term)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for query in queries[:4]:
        try:
            rows = corpus.find_skills(query=query, gem_type="active", limit=5)
        except Exception:  # noqa: BLE001 - corpus evidence is advisory; route still returns
            rows = []
        for row in rows:
            name = str(row.get("name") or "")
            if not name or name in seen:
                continue
            seen.add(name)
            candidates.append(
                {
                    "name": name,
                    "query": query,
                    "tags": row.get("tags") or [],
                    "source": "corpus-skill-search",
                }
            )
            if len(candidates) >= 5:
                break
        if len(candidates) >= 5:
            break
    return {"queries": queries, "skillCandidates": candidates}


def _stage_plan(
    stage: dict[str, Any],
    goal: str,
    classification: str,
    evidence: dict[str, Any] | None = None,
    cohort: dict[str, Any] | None = None,
    budget: str | None = None,
) -> dict[str, Any]:
    tags = ["lifecycle-research", "corpus"]
    if stage["id"] in {"endgame_budget", "endgame_final"}:
        tags.append("reference-calibration")
        tags.extend(tag for tag in (cohort or {}).get("evidenceTags", []) if tag not in tags)
    if stage["id"] == "maps_entry":
        tags.append("user-feedback-ready")

    transition_note = (
        "This stage may use a different temporary starter skill before the final mechanic is online."
        if classification in {"starter_then_transition", "endgame_only"}
        and stage["id"].startswith("campaign")
        else "Keep the same core identity if engine checks and gearing stay smooth."
    )
    skill_names = [s["name"] for s in (evidence or {}).get("skillCandidates", [])[:3]]
    skill_plan = (
        "Try candidate skill anchors: " + ", ".join(skill_names)
        if skill_names
        else f"Choose a low-dependency skill package aligned with: {goal}"
    )
    budget_note = f"Budget constraint: {budget}." if budget else "Budget not specified."
    cohort_hints = (
        _cohort_hints(cohort) if stage["id"] in {"endgame_budget", "endgame_final"} else []
    )

    return {
        **stage,
        "skillPlan": skill_plan,
        "supportPlan": "Prefer supports available at this stage; re-run support optimization after gear changes.",
        "passivePriorities": [
            "path through efficient nearby damage/defense clusters",
            "avoid expensive detours until a transition gate proves the endgame mechanic is online",
        ],
        "gearPriorities": [
            budget_note,
            "cap elemental resistances before trading defense for damage",
            "use rares or cheap uniques until the build-defining component is actually available",
        ],
        "targetChecks": [
            "resists_capped",
            "basic_defense_online",
            "sustain_ok",
            "pob_model_supported",
        ],
        "risks": [transition_note],
        "cohortHints": cohort_hints,
        "verification": lifecycle_verification.plan_stage_verification(stage["id"]),
        "evidenceTags": tags,
    }


def _cohort_hints(cohort: dict[str, Any] | None) -> list[str]:
    """Translate cohort evidence into short stage hints without copying a reference build."""
    if not cohort or not cohort.get("sampleSize"):
        return ["No mature reference cohort matched yet; verify this stage from first principles."]

    hints: list[str] = []
    for label, key in (
        ("Common mature-build levers", "commonLevers"),
        ("Common damage types", "commonDamageTypes"),
        ("Common delivery traits", "commonDelivery"),
        ("Common defense identities", "commonDefenses"),
    ):
        names = _row_names(cohort.get(key) or [])
        if names:
            hints.append(f"{label}: {', '.join(names)}")
    ascendancies = [
        str(row.get("ascendancy"))
        for row in (cohort.get("ascendancyContext") or [])[:3]
        if row.get("ascendancy")
    ]
    if ascendancies:
        hints.append(f"Reference ascendancies to compare, not copy: {', '.join(ascendancies)}")
    return hints


def _row_names(rows: list[dict[str, Any]]) -> list[str]:
    return [str(row.get("name")) for row in rows[:3] if row.get("name")]


def research_build_lifecycle(
    goal: str,
    *,
    preferences: str | None = None,
    budget: str | None = None,
    mode: str | None = None,
    freshness: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    """Create a staged lifecycle route from a natural-language goal.

    This is the local analogue of a deep-research outline: plan the questions first,
    attach evidence labels, and keep every stage honest about what still requires PoB
    verification. It does not copy a meta build wholesale.
    """
    goal = (goal or "").strip()
    if not goal:
        return {"ok": False, "error": "goal is required"}

    intent_text = " ".join(x for x in [goal, preferences or "", mode or ""] if x)
    wants_starter = _has_any(intent_text, {"开荒", "新手", "starter", "league", "start"})
    wants_endgame = _has_any(intent_text, {"终局", "毕业", "endgame", "pinnacle", "强力", "boss"})
    features = {
        "critical_uniques": ["build-defining unique/threshold component"] if wants_endgame else [],
        "low_level_viable": wants_starter,
        "starter_route_available": True,
        "endgame_scaling": wants_endgame or not wants_starter,
    }
    classification = classify_lifecycle(features)
    evidence = _collect_goal_evidence(goal, preferences)
    cohort = lifecycle_cohort.analyze_goal_cohort(
        goal=goal,
        skill_candidates=evidence.get("skillCandidates") or [],
        meta=meta,
    )
    stages = [
        _stage_plan(stage, goal, classification["classification"], evidence, cohort, budget)
        for stage in STAGES
        if stage["id"] in {"campaign_early", "campaign_mid", "campaign_late", "maps_entry"}
        or wants_endgame
        or stage["id"] == "endgame_budget"
    ]
    gates = _default_gates()
    build_id = _short_hash("|".join([goal, preferences or "", budget or "", mode or ""]), "life")
    freshness = freshness or {"decision": "not_checked", "blockers": [], "warnings": []}

    result = {
        "ok": True,
        "buildId": build_id,
        "goal": goal,
        "classification": classification["classification"],
        "starterViable": classification["starter_viable"],
        "classificationReasons": classification["reasons"],
        "researchPlan": {
            "method": "deep-research-inspired lifecycle workflow",
            "steps": RESEARCH_STEPS,
            "questions": [
                "Can the endgame mechanic function before its key item/gem/ascendancy?",
                "What temporary starter carries campaign and early maps?",
                "Which exact gate proves it is safe to transition?",
                "Which numbers still require PoB engine verification?",
            ],
        },
        "freshness": {
            "decision": freshness.get("decision"),
            "blockers": freshness.get("blockers") or [],
            "warnings": freshness.get("warnings") or [],
        },
        "metaContext": meta or {"ok": False, "note": "meta not fetched"},
        "constraints": {"preferences": preferences, "budget": budget, "mode": mode},
        "evidence": evidence,
        "cohortAnalysis": cohort,
        "stages": stages,
        "transitionGates": gates,
        "memoryPolicy": (
            "Feedback starts as episodic memory. Promote only when evidence is reusable, verified, "
            "and scoped to the current patch/passive tree."
        ),
        "dataTags": ["freshness-gate", "corpus", "reference-calibration", "user-feedback"],
        "note": (
            "This lifecycle route is a research scaffold, not a finished PoB. Run PoB verification "
            "per stage before presenting computed DPS/EHP/resistance numbers."
        ),
    }

    if persist:
        with _MEMORY_LOCK:
            memory = load_memory()
            memory["lifecycle_builds"][build_id] = {
                "goal": goal,
                "constraints": result["constraints"],
                "evidence": result["evidence"],
                "cohortSummary": {
                    "sampleSize": cohort.get("sampleSize"),
                    "commonLevers": cohort.get("commonLevers") or [],
                    "ascendancyContext": cohort.get("ascendancyContext") or [],
                },
                "classification": result["classification"],
                "starterViable": result["starterViable"],
                "stageIds": [s["id"] for s in stages],
                "freshnessDecision": result["freshness"]["decision"],
                "createdAt": _now(),
            }
            memory["transition_gates"][build_id] = gates
            save_memory(memory)

    return result


def analyze_lifecycle_cohort(
    goal: str,
    *,
    preferences: str | None = None,
    meta: dict[str, Any] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Inspect non-copyable mature-build cohort evidence for a natural-language goal."""
    goal = (goal or "").strip()
    if not goal:
        return {"ok": False, "error": "goal is required"}
    evidence = _collect_goal_evidence(goal, preferences)
    cohort = lifecycle_cohort.analyze_goal_cohort(
        goal=goal,
        skill_candidates=evidence.get("skillCandidates") or [],
        meta=meta,
        limit=limit,
    )
    cohort["goalEvidence"] = evidence
    return cohort


def analyze_build_lifecycle(
    source: str,
    *,
    imported_build: dict[str, Any] | None = None,
    import_caveats: list[str] | None = None,
    import_error: str | None = None,
) -> dict[str, Any]:
    """Analyze lifecycle viability for an imported or externally described build."""
    build = imported_build or {}
    source_evidence = lifecycle_evidence.extract_lifecycle_source_evidence(source)
    level = int(build.get("level") or 0)
    unique_names = _unique_dependencies(build)
    source_unique_names = [
        str(row.get("name"))
        for row in source_evidence.get("uniqueCandidates") or []
        if row.get("name")
    ]
    critical_uniques = sorted(
        {
            *unique_names,
            *(
                source_unique_names
                if "required_unique_language" in (source_evidence.get("riskFlags") or [])
                else []
            ),
        }
    )
    stage_signals = set(source_evidence.get("stageSignals") or [])
    lifecycle_hints = set(source_evidence.get("lifecycleHints") or [])
    features = {
        "critical_uniques": critical_uniques,
        "low_level_viable": (1 <= level <= 70 and not critical_uniques)
        or ("campaign_early" in stage_signals and "starter_route" in lifecycle_hints),
        # An imported final-form unique-dependent build needs a separate starter route. If there
        # is no unique dependency and the import is already high-level, do not infer starter safety.
        "starter_route_available": bool(critical_uniques)
        or "starter_route" in lifecycle_hints
        or bool(source_evidence.get("transitionHints")),
        "endgame_scaling": level >= 75
        or bool(critical_uniques)
        or bool(build.get("mainSkill"))
        or "endgame_final" in stage_signals
        or "endgame_form" in lifecycle_hints,
    }
    classification = classify_lifecycle(features)
    return {
        "ok": import_error is None,
        "classification": classification["classification"],
        "starterViable": classification["starter_viable"],
        "classificationReasons": classification["reasons"],
        "sourceSummary": {
            "provided": bool((source or "").strip()),
            "imported": imported_build is not None,
            "mainSkill": build.get("mainSkill"),
            "level": level or None,
        },
        "transitionGates": _default_gates(),
        "sourceEvidence": source_evidence,
        "importCaveats": import_caveats or [],
        "importError": import_error,
        "evidenceTags": sorted(
            {
                "engine-computed" if imported_build else "external-guide",
                *(source_evidence.get("evidenceTags") or []),
            }
        ),
        "note": "Use transition gates before recommending this as a leveling route.",
    }


def _unique_dependencies(build: dict[str, Any]) -> list[str]:
    """Known unique names present on an imported build.

    PoB readback exposes equipped items as `gear` with name/base, not raw rarity. We therefore
    resolve the displayed item name against the unique corpus instead of relying on an `items`
    list shape that imported builds do not provide.
    """
    found: list[str] = []
    for item in build.get("items") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        base = str(item.get("base") or "")
        if str(item.get("rarity") or "").lower() == "unique" or _known_unique(name, base):
            found.append(name)
    for item in (build.get("gear") or {}).values():
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        base = str(item.get("base") or "")
        if name and _known_unique(name, base):
            found.append(name)
    return sorted({name for name in found if name})


def _known_unique(name: str, base: str | None = None) -> dict[str, Any] | None:
    """Return corpus unique metadata for an exact displayed item name, if known."""
    unique = corpus.get_unique(name)
    if not unique:
        return None
    if base and unique.get("base") and str(unique["base"]).lower() != str(base).lower():
        return None
    return unique


def compare_lifecycle_routes(route_a: dict[str, Any], route_b: dict[str, Any]) -> dict[str, Any]:
    """Compare two lifecycle-route dictionaries for explainable trade-offs."""
    stages_a = route_a.get("stages") or []
    stages_b = route_b.get("stages") or []
    gates_a = route_a.get("transitionGates") or []
    gates_b = route_b.get("transitionGates") or []
    return {
        "ok": True,
        "a": {
            "buildId": route_a.get("buildId"),
            "classification": route_a.get("classification"),
            "stages": len(stages_a),
            "gates": len(gates_a),
        },
        "b": {
            "buildId": route_b.get("buildId"),
            "classification": route_b.get("classification"),
            "stages": len(stages_b),
            "gates": len(gates_b),
        },
        "differences": {
            "classification": route_a.get("classification") != route_b.get("classification"),
            "stageCount": len(stages_a) - len(stages_b),
            "gateCount": len(gates_a) - len(gates_b),
        },
        "guidance": (
            "Prefer the route with explicit starter stages and concrete transition gates unless "
            "the user specifically wants an endgame-only import."
        ),
    }


def list_transition_gates(build_id: str | None = None) -> dict[str, Any]:
    with _MEMORY_LOCK:
        memory = load_memory()
    if build_id:
        gates = memory["transition_gates"].get(build_id)
        return {
            "ok": gates is not None,
            "buildId": build_id,
            "transitionGates": gates or [],
            "note": "No stored gates for build_id." if gates is None else "Stored lifecycle gates.",
        }
    return {
        "ok": True,
        "buildIds": sorted(memory["transition_gates"].keys()),
        "transitionGates": _default_gates(),
        "note": "Default gates shown; pass build_id for a stored lifecycle route.",
    }


def _failure_pattern(feedback: str) -> str:
    text = (feedback or "").lower()
    if any(token in text for token in ("暴毙", "死", "die", "one-shot", "oneshot")):
        return "defense_gap"
    if any(token in text for token in ("抗性", "resist")):
        return "resistance_gap"
    if any(token in text for token in ("缺蓝", "mana", "sustain", "续航")):
        return "sustain_gap"
    if any(token in text for token in ("伤害", "dps", "boss慢", "刮痧")):
        return "damage_gap"
    if any(token in text for token in ("清图", "clear")):
        return "clear_speed_gap"
    return "general_feedback"


def _recommended_actions(
    stage: str,
    pattern: str | None,
    missing: list[str] | None = None,
) -> list[str]:
    """Stage-aware repair advice used by readiness checks and feedback memory.

    These actions are intentionally conservative: when the player reports a failure pattern or a
    gate requirement is missing, the agent should stabilize the current stage before recommending a
    switch to the next lifecycle form.
    """
    actions: list[str] = []
    missing = missing or []
    if missing:
        actions.append("Do not transition yet; missing gate requirements: " + ", ".join(missing))

    if pattern == "defense_gap":
        actions.extend(
            [
                "Cap elemental resistances before moving to the next stage.",
                "Raise the current stage's basic defense layer before trading defense for damage.",
            ]
        )
    elif pattern == "resistance_gap":
        actions.append("Hold the current stage until elemental resistances are capped.")
    elif pattern == "sustain_gap":
        actions.append("Fix mana/Spirit/life sustain before adding more damage supports.")
    elif pattern == "damage_gap":
        actions.append("Use engine lever ranking to find the missing multiplier before switching.")
    elif pattern == "clear_speed_gap":
        actions.append("Separate clear-speed support choices from bossing support choices first.")

    if stage == "maps_entry":
        actions.append(
            "For maps_entry, keep farming/repairing until resists_capped, basic_defense_online, "
            "and sustain_ok are true."
        )
    if not actions:
        actions.append("Gate is satisfied; snapshot the current PoB before changing the build.")
    return actions


def record_build_feedback(
    build_id: str,
    stage: str,
    feedback: str,
    outcome: str | None = None,
) -> dict[str, Any]:
    """Record user practice feedback as episodic memory.

    A single report should not become a durable rule by itself. Promotion is a separate,
    explicit step after evidence or repeated feedback proves the lesson is reusable.
    """
    if not build_id.strip() or not stage.strip() or not feedback.strip():
        return {"ok": False, "error": "build_id, stage, and feedback are required"}

    with _MEMORY_LOCK:
        memory = load_memory()
        pattern = _failure_pattern(feedback)
        recommended_actions = _recommended_actions(stage, pattern)
        # Include a UUID so repeated identical feedback in the same second never overwrites the prior
        # reflection while still producing compact, human-scannable ids.
        feedback_id = _short_hash(
            "|".join([build_id, stage, feedback, _now(), uuid.uuid4().hex]), "fb"
        )
        reflection = {
            "id": feedback_id,
            "buildId": build_id,
            "stage": stage,
            "feedback": feedback,
            "outcome": outcome,
            "failurePattern": pattern,
            "recommendedActions": recommended_actions,
            "memoryType": "episodic",
            "promotionEligible": False,
            "createdAt": _now(),
        }
        memory["feedback_reflections"][feedback_id] = reflection
        pattern_row = memory["failure_patterns"].setdefault(
            pattern, {"count": 0, "evidenceIds": [], "lastSeenAt": None}
        )
        pattern_row["count"] += 1
        pattern_row["evidenceIds"].append(feedback_id)
        pattern_row["lastSeenAt"] = _now()
        save_memory(memory)
    return {
        "ok": True,
        "feedbackId": feedback_id,
        "memoryType": "episodic",
        "promotionEligible": False,
        "failurePattern": pattern,
        "recommendedActions": recommended_actions,
        "diagnosis": _diagnosis_for_pattern(pattern),
    }


def _diagnosis_for_pattern(pattern: str) -> str:
    return {
        "defense_gap": "Treat as a stage-readiness problem: check resists, EHP, recovery, and guard layers.",
        "resistance_gap": "Do not transition stages until elemental resistances are capped.",
        "sustain_gap": "Check mana/spirit/life sustain before adding more damage supports.",
        "damage_gap": "Find the missing multiplier with engine lever ranking before changing the route.",
        "clear_speed_gap": "Separate clear-speed supports/skills from bossing supports before judging the build.",
    }.get(pattern, "Record as feedback and compare against future reports before promoting.")


def promote_technique_memory(
    evidence_ids: list[str],
    reason: str,
    *,
    current_patch: str | None = None,
    current_tree: str | None = None,
) -> dict[str, Any]:
    """Promote feedback/evidence into durable technique memory."""
    with _MEMORY_LOCK:
        memory = load_memory()
        missing = [eid for eid in evidence_ids if eid not in memory["feedback_reflections"]]
        if missing:
            return {
                "ok": False,
                "error": "some evidence ids were not found",
                "missingEvidenceIds": missing,
            }
        evidence = [memory["feedback_reflections"][eid] for eid in evidence_ids]
        if not evidence:
            return {"ok": False, "error": "no matching evidence ids found"}

        card_id = _short_hash("|".join(evidence_ids + [reason]), "tech")
        card = {
            "id": card_id,
            "reason": reason,
            "evidenceIds": evidence_ids,
            "buildIds": sorted({row["buildId"] for row in evidence}),
            "stages": sorted({row["stage"] for row in evidence}),
            "patch": current_patch or "unknown",
            "passiveTree": current_tree or "unknown",
            "confidence": "promoted",
            "createdAt": _now(),
        }
        memory["technique_cards"][card_id] = card
        for row in evidence:
            row["promotedTo"] = card_id
        save_memory(memory)
    return {
        "ok": True,
        "techniqueId": card_id,
        "memoryType": "durable_technique",
        "technique": card,
    }


def current_compatibility_claim() -> dict[str, Any]:
    """Best-effort latest local compatibility claim for patch-scoping memories.

    User-data installed metadata wins because it describes the runtime that path resolution will
    actually prefer after self-update. Bundled compatibility is only the development fallback.
    """
    installed_path = paths.user_data_dir() / "installed.json"
    try:
        installed = json.loads(installed_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        installed = {}
    if installed.get("game_patch") or installed.get("passive_tree"):
        return {
            "commit": installed.get("pob_commit"),
            "game_patch": installed.get("game_patch"),
            "passive_tree": installed.get("passive_tree"),
            "source": "installed-runtime",
        }

    p = paths.BUNDLE_ROOT / "data" / "compatibility" / "pob.json"
    try:
        entries = json.loads(p.read_text(encoding="utf-8")).get("entries") or []
    except (OSError, ValueError, AttributeError):
        return {}
    return entries[-1] if entries else {}
