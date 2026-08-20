"""poe2-build-mcp MCP server.

Exposes the full v1 surface: the compute layer (import + Path-of-Building-faithful stats,
passives, mutation, optimize), the offline knowledge corpus (items/skills/mods/uniques/
passives/mechanics search), and live ops (prices, data-version, self-update). Tool
implementations live in the layer packages; this module registers them and ships the
assistant-facing operating guide via the MCP `instructions` channel.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from scripts import create_build as generation_run_helper

from . import paths
from . import scaffold
from .compute.engine import PobEngine
from .compute.engine_pool import (
    SessionCallGate,
    SessionEnginePool,
    current_session,
    reset_current_session,
    set_current_session,
)
from .compute import buildopt
from .compute import craftopt
from .compute import completeness
from .compute import itemopt
from .compute import mutation_batch
from .compute import passiveopt
from .compute import skillgroups
from .compute import solver
from .compute import state as compute_state
from .compute import supportopt
from .compute.pob_code import PobCodeError, decode_code, encode_code, is_link, to_xml
from .knowledge import advice
from .knowledge import db as corpus
from .knowledge import item_legality
from .knowledge import itemparse
from .knowledge import lifecycle
from .knowledge import lifecycle_eval
from .knowledge import graph_tools
from .knowledge import graph_seed
from .knowledge import mechanics
from .knowledge import refbuilds
from .knowledge import research_memory
from .knowledge import research_models
from .knowledge import research_packet
from .knowledge import research_prompt
from .live import meta as live_meta
from .live import prices as live_prices
from .live import update as live_update
from .live import version as live_version
from .live import wiki as live_wiki
from .freshness import service as freshness_service
from .generation import artifacts as generation_artifacts
from .generation import progression_lifecycle as generation_progression_lifecycle
from .generation import evaluation as generation_evaluation
from .generation import delivery as generation_delivery
from .generation import leveled_build as generation_leveled_build
from .generation import pob_exports as generation_pob_exports
from .generation import preflight as generation_preflight
from .generation import validation_checkpoint as generation_validation_checkpoint
from .judge import evaluator as judge_evaluator
from .learning import memory as learning_memory
from .learning import models as learning_models
from .learning import service as learning_service
from .build_planner import converter as build_planner_converter
from .build_planner import exporter as build_planner_exporter
from .runtime import tool_telemetry
from .runtime import task_cleanup

# Keep MCP bootstrap instructions intentionally small.  The complete runtime guide remains the
# human-maintained source of truth, while skills load only the workflow references they need.
# Deferred tool discovery may repeat MCP instructions, so sending the full guide here causes severe
# context amplification during multi-stage Create.
_GUIDE = Path(__file__).with_name("MCP_BOOTSTRAP.md")
try:
    _INSTRUCTIONS: str | None = _GUIDE.read_text(encoding="utf-8")
except OSError:
    _INSTRUCTIONS = (
        "Path of Exile 2 build toolset: an offline knowledge corpus plus a Path of Building "
        "compute engine. Every build number must come from a compute tool — never invent DPS, "
        "EHP, or resistances. One active build persists across calls."
    )

_engine_pool = SessionEnginePool()
_session_call_gate = SessionCallGate()


class _SessionIsolatedFastMCP(FastMCP):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        started = time.perf_counter()
        result: Any = None
        failed = False
        try:
            session = self.get_context().session
        except ValueError:
            session = None
        token = set_current_session(session)
        try:
            if name == "apply_updates":
                result = await super().call_tool(name, arguments)
            else:
                async with _session_call_gate.hold(session):
                    result = await super().call_tool(name, arguments)
            return result
        except Exception:
            failed = True
            raise
        finally:
            tool_telemetry.record_tool_call(
                tool_name=name,
                arguments=arguments,
                result=result,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                failed=failed,
            )
            reset_current_session(token)


mcp = _SessionIsolatedFastMCP("poe2-build-mcp", instructions=_INSTRUCTIONS)


def get_engine() -> PobEngine:
    """Return the current MCP session's headless engine, starting it if needed."""
    return _engine_pool.get(current_session())


@contextmanager
def _runtime_install_context(replace_engine: bool):
    with _session_call_gate.maintenance_sync():
        context = _engine_pool.preserve_sessions() if replace_engine else nullcontext()
        with context:
            yield


def _validate_staged_engine(staged_pob: Path) -> None:
    with PobEngine(
        src_dir=staged_pob / "PathOfBuilding-PoE2" / "src",
        script=staged_pob / "pob_headless.lua",
    ) as engine:
        engine.ping()


# PoB-PoE2 (pinned) has the gem DATA for energy-based meta triggers (Cast on Critical, the
# Invocations, Spell-on-Hit…) but NO calc that turns "energy generated on crit/hit" into a trigger
# rate — so a socketed spell computes as a weak SELF-CAST, never the triggered nuke it is in game.
# We can't invent the number (engine = source of truth), so surface the limitation wherever such a
# gem appears, lest a triggered skill's tiny self-cast DPS be mistaken for its real damage.
_META_TRIGGER_CAVEAT = (
    "Engine limitation — this build uses an energy-based meta-trigger gem ({gems}). The pinned PoB "
    "engine does NOT model the trigger rate of these gems: any socketed spell is computed as a weak "
    "SELF-CAST, so its real TRIGGERED DPS is not reflected. Do not present this number as the "
    "build's true damage. Trigger-meta archetypes (e.g. Cast on Critical → Comet, the ~1M-DPS meta) "
    "can't be faithfully modelled until upstream PoB-PoE2 adds the energy-trigger calc — prefer an "
    "archetype the engine CAN model (see build_advice), or flag the gap to the user."
)


def _gem_names_in(skill_text: str) -> list[str]:
    """Best-effort gem names from PoB paste text (one gem per line, or ' / ', '|', ',' separated),
    dropping the trailing '<level>/<quality> <count>' spec (the level slash has no spaces, so it
    isn't mistaken for a gem separator)."""
    names: list[str] = []
    for chunk in re.split(r"[\n|,]+|\s+/\s+", skill_text or ""):
        name = re.sub(
            r"\s+\d[\d/ ]*$", "", chunk
        ).strip()  # strip "20/20 1", keep Roman-numeral tiers
        if name:
            names.append(name)
    return names


def _flag_meta_trigger(result: dict[str, Any], gem_names: list[str]) -> dict[str, Any]:
    """Attach the meta-trigger engine-limitation caveat to `result` if any gem is one (see above)."""
    if isinstance(result, dict):
        metas = corpus.meta_trigger_gems(gem_names)
        if metas:
            result["engineLimitation"] = _META_TRIGGER_CAVEAT.format(gems=", ".join(metas))
    return result


def _source_to_xml(source: str) -> str:
    """Normalize a user-supplied build source (code / link / raw XML / local file) to PoB XML."""
    src = (source or "").strip()
    if not src:
        raise ValueError("empty build source")
    # A local PoB export file (XML or a saved share code), e.g. a path into PoB's Builds folder.
    if len(src) < 500 and "\n" not in src and Path(src).expanduser().is_file():
        src = Path(src).expanduser().read_text(encoding="utf-8").strip()
    if is_link(src):
        return to_xml(src)
    if "PathOfBuilding" in src and "<" in src:
        return src  # already raw PoB XML
    return decode_code(src)  # otherwise assume a PoB import/share code


def _graph_query_service() -> graph_tools.GraphQueryService:
    index_path = graph_seed.ensure_installed()
    return graph_tools.service_from_snapshot_index(str(index_path))


def _research_memory_service() -> research_memory.ResearchMemoryService:
    return research_memory.ResearchMemoryService()


def _research_memory_service_with_graph() -> research_memory.ResearchMemoryService:
    try:
        graph_service = _graph_query_service()
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
        graph_service = None
    return research_memory.ResearchMemoryService(graph_service=graph_service)


@mcp.tool()
def import_build(source: str) -> dict[str, Any]:
    """Import a Path of Exile 2 build for analysis and theorycrafting.

    `source` may be a Path of Building import/share code, a pobb.in or pastebin link, or
    raw PoB XML. Returns the selected main skill and a summary of engine-computed stats.
    The imported build becomes the active build for subsequent tool calls.

    Shared PoBs are often aspirational, so the result carries `importCaveats` when the build has
    author-added custom mods, an over-budget tree, or uncapped resists — don't read its raw numbers
    as achieved-as-shown without accounting for those.
    """
    try:
        xml = _source_to_xml(source)
    except (PobCodeError, ValueError) as e:
        return {"ok": False, "error": f"Could not read that build source: {e}"}
    eng = get_engine()
    res = eng.load_build_xml(xml)
    res["importCaveats"] = _import_caveats(eng)
    return res


def _import_caveats(eng: PobEngine) -> list[str]:
    """Flag why a shared PoB's raw numbers may overstate reality (best-effort; never raises)."""
    caveats: list[str] = []
    try:
        b = eng.get_build()
        if (b.get("customMods") or "").strip():
            caveats.append(
                "carries author-added custom mods (configTab) that can inflate its stats beyond "
                "what its gear provides"
            )
        used, avail = b.get("pointsUsed") or 0, b.get("pointsAvailable") or 0
        if used > avail:
            caveats.append(
                f"tree spends {used} passive points but level {b.get('level')} grants only {avail} "
                f"({used - avail} over budget — aspirational, not attainable as shown)"
            )
        res = eng.get_defenses().get("resistances") or {}
        elems = ["fire", "cold", "lightning"]
        if "Chaos Inoculation" not in (b.get("keystones") or []):
            elems.append("chaos")
        under = [
            f"{el} {res.get(el)}"
            for el in elems
            if isinstance(res.get(el), (int, float)) and res[el] < 75
        ]
        if under:
            caveats.append(
                "resistances below the 75% cap ("
                + ", ".join(under)
                + ") — not fully defended as imported"
            )
    except Exception:
        return caveats  # advisory only
    return caveats


@mcp.tool()
def get_build_stats(keys: list[str] | None = None) -> dict[str, Any]:
    """Return Path-of-Building-computed stats for the currently loaded build.

    Pass `keys` to request specific stats (e.g. ["TotalDPS", "Life", "EnergyShield"]);
    omit it for a default summary. Every value is computed by the real PoB engine.
    """
    return get_engine().get_stats(keys)


@mcp.tool()
def get_build() -> dict[str, Any]:
    """Full read-back of the active build.

    Returns class/level/ascendancy, the main skill group (gems + levels), allocated
    notables/keystones/ascendancy nodes, equipped gear by slot, passive points used, and
    summary stats — so you can see the whole build you've assembled.
    """
    build = get_engine().get_build()
    names = (
        [g.get("name", "") for g in (build.get("mainSkillGroup") or [])]
        if isinstance(build, dict)
        else []
    )
    return _flag_meta_trigger(build, names)


@mcp.tool()
def get_defenses() -> dict[str, Any]:
    """Defensive summary for the active build: life/ES/mana/ward, armour/evasion, block,
    elemental + chaos resistances (with over-cap), and TotalEHP. Elemental resists are shown
    net of PoB's configurable area penalty (default Endgame -60%); the response includes the
    active `resistPenalty` and a note. Cap is 75%; aim at or just over it.
    """
    return get_engine().get_defenses()


@mcp.tool()
def export_build() -> dict[str, Any]:
    """Export the active build as a Path of Building import code.

    Paste the returned `code` into Path of Building (Import/Export → Import) or share it.
    """
    return {"code": encode_code(get_engine().get_xml())}


@mcp.tool()
def new_build() -> dict[str, Any]:
    """Reset to a blank build — clears gear, skills, passives, and config.

    Use this to start a build truly from scratch mid-session: `set_class` re-roots the tree but
    KEEPS existing gear/skills/config, which can carry leftovers from a prior build. Call
    `new_build` first, then `set_class` → `set_level` → … for a clean slate.
    """
    return get_engine().new_build()


@mcp.tool()
def set_class(class_name: str, ascendancy: str | None = None) -> dict[str, Any]:
    """Set the active build's character class and (optionally) ascendancy.

    `class_name` is a base class (e.g. "Mercenary", "Witch", "Ranger"); `ascendancy` is one of
    its ascendancies (e.g. "Witchhunter"). This re-roots the passive tree at that class's start,
    so subsequent passive search/allocate/optimize operate on the correct class. It does NOT clear
    existing gear/skills/config — call `new_build` first if you want a clean slate. Returns stats.
    """
    return get_engine().set_class(class_name, ascendancy=ascendancy)


@mcp.tool()
def set_level(level: int) -> dict[str, Any]:
    """Set the active build's character level (1-100). Returns updated stats."""
    if not 1 <= level <= 100:
        return {"ok": False, "error": f"level must be in 1-100, got {level}"}
    return get_engine().set_level(level)


@mcp.tool()
def set_skill(skill: str) -> dict[str, Any]:
    """Set the active build's MAIN skill (gem + its support gems) in PoB paste format.

    Format: "<Gem> <level>/<quality> <count>", e.g. "<gem name> 20/0 1". List the main skill first,
    then its supports — one gem per line, OR separated inline by " / ", "," or "|" (all accepted);
    a bare active gem name uses the highest base gem level legal for the current character level;
    a bare support gets a cosmetic default because PoE2 supports are fixed-effect. An explicitly
    over-levelled active gem is rejected and the build is left unchanged. This REPLACES the current
    main skill group; auras/heralds/reservation buffs
    added via `add_skill_group` are separate groups and are preserved. If nothing parses (or the main
    gem name isn't a real skill) the build is left UNCHANGED and `ok:false` is returned — it won't
    silently drop supports or corrupt the skill. Returns updated stats, plus `ProjectileCount` + a
    `dpsNote` for multi-projectile skills. For persistent buffs, use `add_skill_group`.
    """
    return _flag_meta_trigger(get_engine().paste_skill(skill), _gem_names_in(skill))


@mcp.tool()
def add_skill_group(skill: str, in_full_dps: bool = False) -> dict[str, Any]:
    """Add an ENABLED secondary skill group (aura, herald, or persistent buff) WITHOUT changing
    the main skill — so its buff/reservation applies to the active build.

    This is how you model the damage layers that carry endgame casters/attackers: auras, heralds,
    and reservation/mana-scaling buffs, etc. Same paste format as `set_skill`
    ("<Gem> <level>/<quality>  <count>", supports newline-separated). The group is added enabled
    and its effect is reflected in the returned stats; the main skill is preserved. Mind Spirit
    reservation — check it still fits (get_build_stats / list_config_options) after stacking auras.

    Set `in_full_dps=True` only for a second DAMAGE skill (clear+boss combo, a trigger/totem) so it
    aggregates into FullDPS. Leave it False for auras/heralds/buffs (otherwise their standalone
    damage inflates the combined number).
    """
    return _flag_meta_trigger(
        get_engine().add_skill_group(skill, include_in_full_dps=in_full_dps), _gem_names_in(skill)
    )


@mcp.tool()
def list_skill_groups() -> dict[str, Any]:
    """List the active build's skill groups with safe selectors for precise edits.

    Each group includes its current `index` and opaque `fingerprint`; the response also includes a
    `stateHash`. Pass the fingerprint to every group mutation, and preferably pass the state hash as
    `expected_state_hash`, so a stale index can never edit or delete the wrong group.
    """

    return skillgroups.list_skill_groups(get_engine())


@mcp.tool()
def replace_skill_group(
    group_index: int,
    expected_fingerprint: str,
    skill: str,
    expected_state_hash: str | None = None,
) -> dict[str, Any]:
    """Atomically replace one user-owned skill group without rebuilding the whole PoB.

    Read `list_skill_groups` immediately beforehand. The group position, enabled state, Full DPS
    flag and label are preserved. Item/passive-provided groups are immutable, invalid gem text or
    illegal active-gem levels roll back, and stale selectors fail without changing the build.
    """

    return _flag_meta_trigger(
        skillgroups.replace_skill_group(
            get_engine(),
            group_index=group_index,
            expected_fingerprint=expected_fingerprint,
            skill=skill,
            expected_state_hash=expected_state_hash,
        ),
        _gem_names_in(skill),
    )


@mcp.tool()
def remove_skill_group(
    group_index: int,
    expected_fingerprint: str,
    replacement_main_group_index: int | None = None,
    expected_state_hash: str | None = None,
) -> dict[str, Any]:
    """Atomically remove a user-owned skill group selected from `list_skill_groups`.

    Item/passive-provided groups and the only remaining group cannot be removed. Removing the main
    group requires `replacement_main_group_index`; main/calculation indices are updated together.
    """

    return skillgroups.remove_skill_group(
        get_engine(),
        group_index=group_index,
        expected_fingerprint=expected_fingerprint,
        replacement_main_group_index=replacement_main_group_index,
        expected_state_hash=expected_state_hash,
    )


@mcp.tool()
def set_skill_group_state(
    group_index: int,
    expected_fingerprint: str,
    enabled: bool | None = None,
    in_full_dps: bool | None = None,
    make_main: bool = False,
    active_skill_index: int | None = None,
    label: str | None = None,
    expected_state_hash: str | None = None,
) -> dict[str, Any]:
    """Atomically change typed state on one skill group.

    Supports enabled/Full DPS flags, label, selected active skill and making the group main. The
    current main group cannot be disabled until another group is selected. Stale fingerprints or
    state hashes fail closed.
    """

    return skillgroups.set_skill_group_state(
        get_engine(),
        group_index=group_index,
        expected_fingerprint=expected_fingerprint,
        enabled=enabled,
        in_full_dps=in_full_dps,
        make_main=make_main,
        active_skill_index=active_skill_index,
        label=label,
        expected_state_hash=expected_state_hash,
    )


@mcp.tool()
def set_config(
    options: dict[str, Any] | None = None, custom_mods: str | None = None
) -> dict[str, Any]:
    """Set combat/configuration options and/or extra modifiers on the active build.

    `options` are Path of Building config keys, e.g. {"enemyIsBoss": "Boss"},
    {"usePowerCharges": true}. `custom_mods` is free-form modifier text applied to the
    character, e.g. "100% increased Fire Damage\\n+2 to Level of all Fire Skills".
    Recomputes and returns stats.
    """
    return get_engine().set_config(options=options, custom_mods=custom_mods)


@mcp.tool()
def apply_combat_profile(
    tier: str = "Pinnacle",
    shocked: bool = True,
    cursed: bool = True,
    power_charges: bool = True,
    frenzy_charges: bool = True,
    full_es: bool = True,
    full_life: bool = False,
) -> dict[str, Any]:
    """Apply a realistic boss-combat profile in one call, so DPS reflects an actual fight.

    The engine's enemy-condition levers are OFF by default, so a bare `get_build_stats` understates
    a build that, in play, keeps shock/curse/charges up. This sets the common ones at once
    (`enemyIsBoss`=tier plus the toggles) and returns the resulting stats.

    IMPORTANT — these are ASSUMPTIONS the build must actually produce: only keep `shocked` if the
    build shocks, `cursed` if it runs a curse, the charge flags if it generates them. Turn off the
    ones that don't apply (they'd otherwise inflate DPS with effects the build can't sustain). The
    response lists what was assumed. Tiers: None / Boss / Pinnacle / Uber.
    """
    options: dict[str, Any] = {"enemyIsBoss": tier}
    assumptions = [f"enemy tier = {tier}"]
    if shocked:
        options["conditionEnemyShocked"] = True
        assumptions.append("enemy is Shocked (needs your build to shock)")
    if cursed:
        options["conditionEnemyCursed"] = True
        assumptions.append("enemy is Cursed (needs a curse skill applied)")
    if power_charges:
        options["usePowerCharges"] = True
        assumptions.append("Power Charges up (needs generation)")
    if frenzy_charges:
        options["useFrenzyCharges"] = True
        assumptions.append("Frenzy Charges up (needs generation)")
    if full_es:
        options["conditionFullEnergyShield"] = True
        assumptions.append("on Full Energy Shield")
    if full_life:
        options["conditionFullLife"] = True
        assumptions.append("on Full Life")
    res = get_engine().set_config(options=options)
    res["assumptions"] = assumptions
    res["note"] = (
        "DPS now assumes these combat conditions are active — verify the build actually maintains "
        "each (shock/curse/charges) or disable the ones it can't. This is the realistic fighting "
        "number, not a guaranteed floor."
    )
    return res


@mcp.tool()
def list_config_options(query: str = "", limit: int = 60) -> dict[str, Any]:
    """List Path of Building configuration options usable with `set_config`.

    Covers combat conditions, charges, enemy settings, exposure, etc. Filter with `query`
    (matches the option's key or label), e.g. "boss", "charge", "exposure". Returns each
    option's `var` (the key for set_config), `type`, `label`, and valid `values` for dropdowns.
    """
    return get_engine().list_config_options(query=query, limit=limit)


@mcp.tool()
def equip_item(
    raw: str,
    slot: str | None = None,
    craft_receipt_ref: str | None = None,
) -> dict[str, Any]:
    """Equip an item on the active build from raw Path of Building item text.

    Replaces the target slot item. `slot` optionally forces the slot; for PAIRED slots the
    item's primary slot is the first one — pass an explicit `slot` ("Ring 2"/"Weapon 2") or it
    silently overwrites Ring 1/Weapon 1. Returns updated stats.

    `craft_item` results can carry Perfect-Essence/rune/corrupted effects outside the ordinary
    affix pool: pass its `craftReceiptRef` unchanged so the same source-aware legality receipt
    verifies after PoB normalizes the item text.

    Hand-written items are checked against the real mod pool; unrollable affixes return
    `illegalAffixes` + `legalityWarning` and the computed stats include invented mods (not
    achievable). Ground gear in real mods (`optimize_item`/`parse_item`/`search_mods`).
    """
    legality = item_legality.audit_item(
        raw,
        craft_receipt_ref=craft_receipt_ref,
        slot=slot,
        require_special_provenance=True,
    )
    if craft_receipt_ref is not None and not legality.get("ok"):
        return {
            "ok": False,
            "errorCode": "item_legality_check_failed",
            "legalityCheck": legality,
        }
    if "special_source_provenance_required" in (legality.get("issues") or []):
        return {
            "ok": False,
            "errorCode": "special_source_provenance_required",
            "legalityCheck": legality,
        }
    res = get_engine().add_item(raw, slot=slot)
    return _annotate_item_legality(
        res,
        raw,
        craft_receipt_ref=craft_receipt_ref,
        slot=slot,
        legality=legality,
    )


def _annotate_item_legality(
    result: dict[str, Any],
    raw: str,
    *,
    craft_receipt_ref: str | None = None,
    slot: str | None = None,
    legality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    res = result
    try:
        audit = legality or item_legality.audit_item(
            raw,
            craft_receipt_ref=craft_receipt_ref,
            slot=slot,
            require_special_provenance=True,
        )
        res["itemLegality"] = audit
        if not audit.get("ok"):
            issues = [str(value) for value in audit.get("issues") or []]
            res["illegalAffixes"] = [{"issue": issue} for issue in issues]
            base = str(itemparse.semantic_item_structure(raw).get("base") or "item")
            res["legalityWarning"] = (
                f"{len(issues)} deterministic legality issue(s) were found on {base}; "
                "the computed stats cannot be accepted for a generated artifact until the "
                "shared source-aware audit passes."
            )
    except Exception:
        pass  # legality is advisory; never let it break an equip
    return res


def _decorate_batch_mutation_result(
    operation: mutation_batch.BuildMutationOperation,
    result: dict[str, Any],
) -> dict[str, Any]:
    if operation.operation in {"set_main_skill", "add_skill_group"} and operation.skill:
        return _flag_meta_trigger(result, _gem_names_in(operation.skill))
    if operation.operation == "equip_item" and operation.raw:
        decorated = _annotate_item_legality(
            result,
            operation.raw,
            craft_receipt_ref=operation.craft_receipt_ref,
            slot=operation.slot,
        )
        legality = decorated.get("itemLegality")
        if not isinstance(legality, dict) or legality.get("ok") is not True:
            decorated["ok"] = False
            decorated["errorCode"] = "item_legality_check_failed"
        return decorated
    return result


@mcp.tool()
def apply_build_mutation_batch(
    batch_kind: mutation_batch.FunctionalBatchKind,
    operations: Annotated[
        list[mutation_batch.BuildMutationOperation],
        Field(min_length=1, max_length=mutation_batch.MAX_FUNCTIONAL_BATCH_OPERATIONS),
    ],
    expected_state_hash: str | None = None,
) -> dict[str, Any]:
    """Apply one small, function-scoped atomic mutation batch chosen by the Agent.

    `batch_kind` is one of bootstrap, mechanism_shell, skill_loadout, passive_delta,
    required_gear, ordinary_gear or config. Each scope has its own operation whitelist, small limit
    and lightweight postconditions; mixed-function mega-batches are rejected. Only a bootstrap
    beginning with `new_build` may omit `expected_state_hash`. Later scopes must chain the previous
    `outputStateHash`. Search and optimizers are unsupported. A failure rolls back the current
    functional batch when possible; trust restoration only when `rolledBack=true`, otherwise stop
    and recover the session because `recoveryRequired=true`.
    """
    return mutation_batch.apply_build_mutation_batch(
        get_engine(),
        batch_kind=batch_kind,
        operations=operations,
        expected_state_hash=expected_state_hash,
        result_decorator=_decorate_batch_mutation_result,
    )


@mcp.tool()
def unequip_item(slot: str) -> dict[str, Any]:
    """Clear an equipment slot on the active build (e.g. "Ring 2", "Body Armour", "Weapon 1").

    Weapon-swap slots ("Weapon 1 Swap"/"Weapon 2 Swap") and jewel sockets are valid slots too;
    use `equip_item`/`equip_jewel` to fill them.
    """
    return get_engine().unequip_item(slot)


@mcp.tool()
def list_jewel_sockets() -> dict[str, Any]:
    """List the passive tree's jewel sockets: each socket's `id`, whether it's `allocated`, and
    whether it's already `filled`. A jewel only contributes when its socket is allocated (allocate
    a Socket node with `alloc_passive` first). Use a socket `id` with `equip_jewel`.
    """
    return get_engine().list_jewel_sockets()


@mcp.tool()
def inspect_build_completeness() -> dict[str, Any]:
    """Inspect whether the active build is a playable loadout rather than a scoring skeleton.

    Reports active-gem and item level legality, rare/magic item levels, scaffold placeholders,
    rune/soul-core decisions, passive-tree jewel sockets, life/mana flasks, and belt-supported
    charms. Explicit level-requirement violations are hard failures; the remaining findings are
    advisory and require an explicit design decision.
    """
    return completeness.inspect_build_completeness(get_engine())


@mcp.tool()
def inspect_generation_preflight(strict_mode: bool = False) -> dict[str, Any]:
    """Run cheap deterministic checks before consuming a generation Judge attempt.

    Reads one active PoB snapshot and reports missing/invalid main groups, multi-active groups,
    duplicate supports, completely duplicated enabled groups, and completeness findings. Blocking
    issues should be repaired before `evaluate_generation_candidate`. Subjective completeness
    advisories are hidden by default; pass ``strict_mode=true`` to request them explicitly. The
    response never contains XML or raw item text.
    """
    return generation_preflight.inspect_generation_preflight(
        get_engine(),
        strict_mode=strict_mode,
    )


@mcp.tool()
def inspect_generation_checkpoint(strict_mode: bool = False) -> dict[str, Any]:
    """Merge repeated read-only generation checks by semantic build-state hash.

    Completeness, preflight, bounded stats and defenses are computed once for an unchanged state.
    A later call with the same semantic hash reuses the safe process-local result. Formal Judge and
    artifact-bound lifecycle verification remain separate trust steps. Subjective advisories are
    omitted unless ``strict_mode=true`` is supplied.
    """
    return generation_validation_checkpoint.inspect_generation_checkpoint(
        get_engine(),
        strict_mode=strict_mode,
    )


@mcp.tool()
def equip_jewel(raw: str, socket: int | None = None) -> dict[str, Any]:
    """Socket a jewel (raw PoB item text) into a passive-tree jewel socket.

    `socket` is a socket id from `list_jewel_sockets`; if omitted, the first allocated empty socket
    is used. The jewel only applies in an ALLOCATED socket (the result warns otherwise). Ground the
    jewel's mods in real jewel rolls (`search_mods`) — jewels aren't covered by the equip legality
    check. Mana/ES/damage stat jewels are a meaningful chunk of mana-stacker power.
    """
    return get_engine().equip_jewel(raw, socket=socket)


@mcp.tool()
def evaluate_jewel_socket(
    socket: int,
    raw: str,
    keys: list[str] | None = None,
) -> dict[str, Any]:
    """Read-only: measure ONE candidate jewel (raw PoB item text) placed in ONE tree socket.

    This is the positional-evaluation path unique/radius jewels need: the candidate is placed in
    `socket` (an id from `list_jewel_sockets`), and radius/Time-Lost grants are computed by the
    engine over the socket radius' ALLOCATED passives. Returns per-key deltas vs the current
    build; the build is restored afterwards. Use it to rank sockets for a Time-Lost Jewel or to
    value a unique jewel's real effect before `equip_jewel` commits it. Ground the raw text in
    `get_unique` (knowledge server) or a real drop; the engine owns every number.
    """
    return itemopt.evaluate_jewel_socket(
        get_engine(),
        socket=socket,
        raw=raw,
        keys=keys,
    )


@mcp.tool()
def evaluate_build(goals: dict[str, Any]) -> dict[str, Any]:
    """Check the active build against named numeric goals.

    `goals` maps a stat to a constraint: a bare number (treated as a minimum) or an object
    like {"min": 500000, "max": 1000000}. Example:
    {"TotalDPS": {"min": 500000}, "Life": {"min": 5000}, "TotalEHP": 20000}.
    Returns per-goal pass/fail with actual values and an overall `pass`.
    """
    stats = get_engine().get_stats(list(goals.keys()))["stats"]
    results = []
    all_ok = True
    for stat, constraint in goals.items():
        lo = hi = None
        if isinstance(constraint, dict):
            lo, hi = constraint.get("min"), constraint.get("max")
        else:
            lo = constraint
        value = stats.get(stat)
        ok = (
            isinstance(value, (int, float))
            and (lo is None or value >= lo)
            and (hi is None or value <= hi)
        )
        all_ok = all_ok and ok
        results.append({"stat": stat, "value": value, "min": lo, "max": hi, "ok": ok})
    return {"pass": all_ok, "results": results}


@mcp.tool()
def start_generation_run(
    memory_mode: Literal["standard", "no_memory", "memory_assisted"] = "memory_assisted",
) -> dict[str, Any]:
    """Start one isolated Phase 5 generation run without relying on a repository checkout.

    The run is stored in the normal per-user data directory and is immediately usable by
    ``evaluate_generation_candidate``.  Published plugins should call this tool instead of a
    repository-relative ``scripts/create_build.py start-run`` command.
    """
    return generation_run_helper.start_generation_run(memory_mode)


@mcp.tool()
def validate_generation_output(
    run_id: str,
    run_token: str,
    agent_output: dict[str, Any],
) -> dict[str, Any]:
    """Submit and validate one safe generation summary without consuming its review binding."""
    return generation_run_helper.validate_generation_output(run_id, run_token, agent_output)


@mcp.tool()
def complete_generation_review(
    run_id: str,
    run_token: str,
    agent_output: dict[str, Any],
) -> dict[str, Any]:
    """Submit the final safe summary and atomically consume the trusted human-review binding."""
    return generation_run_helper.complete_generation_review(run_id, run_token, agent_output)


@mcp.tool()
def evaluate_generation_candidate(
    run_id: str,
    run_token: str,
    candidate_id: str,
    version_context: dict[str, Any],
    strict_mode: bool = False,
) -> dict[str, Any]:
    """Run the Phase 1 Judge against the Agent-built active PoB state.

    Call this only after the current generation candidate has been fully assembled with the
    stateful PoB tools. The tool snapshots the active build, evaluates that immutable snapshot in
    a dedicated Judge engine, writes a raw-free immutable attempt receipt bound to the generation
    run, and returns `attemptIndex` plus the exact `transientBuildState` and
    `judgeAdvisoryReport` objects required by the generation review helper. The same run accepts an
    initial attempt and at most two Agent-led retries; it never fills gear, passives, skills, or
    configuration for the Agent. The default ``strict_mode=false`` returns only hard failures and
    deterministic diagnostics. Set ``strict_mode=true`` manually to expose the legacy score,
    quality bands, playability warnings, caveats and reward fields for the whole run.
    """
    return generation_evaluation.evaluate_generation_candidate(
        get_engine(),
        run_id=run_id,
        run_token=run_token,
        candidate_id=candidate_id,
        version_context=version_context,
        strict_mode=strict_mode,
    )


@mcp.tool()
def save_final_build_artifact(
    run_id: str,
    run_token: str,
    candidate_id: str,
    attempt_index: int,
    selection_reason: str | None = None,
    later_findings_scope: Literal[
        "not_applicable",
        "candidate_delta_only",
        "baseline_implicated",
        "unknown",
    ] = "not_applicable",
) -> dict[str, Any]:
    """Save the final Agent-accepted, passing PoB candidate in local private storage.

    Any passing attempt with a still-live exact Judge snapshot may be selected. Selecting an older
    baseline requires an explicit reason and evidence that later findings affect only the explored
    delta. Each generation run can save only one artifact; raw PoB is never returned.
    """
    return generation_artifacts.save_final_build_artifact(
        get_engine(),
        run_id=run_id,
        run_token=run_token,
        candidate_id=candidate_id,
        attempt_index=attempt_index,
        selection_reason=selection_reason,
        later_findings_scope=later_findings_scope,
    )


@mcp.tool()
def list_final_build_artifacts() -> dict[str, Any]:
    """List safe metadata for locally saved final build artifacts; never returns PoB XML."""
    return generation_artifacts.list_final_build_artifacts()


@mcp.tool()
def load_final_build_artifact(artifact_id: str) -> dict[str, Any]:
    """Restore a saved final build artifact into the active Headless PoB session.

    The artifact is verified against its source hash before loading. The response contains only a
    safe summary, never the stored XML or PoB import code.
    """
    return generation_artifacts.load_final_build_artifact(get_engine(), artifact_id=artifact_id)


@mcp.tool()
def export_final_pob_artifact(
    artifact_id: str,
    format: Literal["xml", "import_code", "both"] = "both",
    name: str = "",
) -> dict[str, Any]:
    """Export a verified final artifact to local files for desktop Path of Building.

    `xml` writes the complete PoB XML build, `import_code` writes a text file containing the PoB
    import code, and `both` writes both. The response returns only local paths and safe metadata;
    it never includes the XML or import code itself.
    """
    return generation_pob_exports.export_final_pob_artifact(
        artifact_id,
        format=format,
        name=name,
    )


@mcp.tool()
def export_final_build_package(
    artifact_id: str,
    name: str = "",
    author: str = "",
    description: str = "",
    link: str = "",
) -> dict[str, Any]:
    """Export the complete final delivery package with a fixed artifact inventory.

    Produces local PoB XML, a PoB import-code text file, and an official `.build` file. The response
    always lists all three expected artifacts with either an output path or a structured error, so
    the Agent cannot accidentally omit a successful or failed deliverable from the user summary.
    """
    return generation_delivery.export_final_build_package(
        artifact_id,
        name=name,
        author=author,
        description=description,
        link=link,
    )


# --------------------------------------------------------------------------------------
# Phase 7 comparative-learning tools (safe state only; Desktop skill owns task creation)
# --------------------------------------------------------------------------------------
@mcp.tool()
def start_learning_campaign(operation_id: str, case_limit: int = 10) -> dict[str, Any]:
    """Start the fixed ten-case, strictly serial Phase 7 comparative-learning campaign.

    The service stores only safe control state and never creates Desktop tasks or calls a model.
    Reusing the same operation id is idempotent.
    """
    return learning_service.start_campaign(operation_id=operation_id, case_limit=case_limit)


@mcp.tool()
def intake_learning_case(
    campaign_id: str,
    expected_revision: int,
    operation_id: str,
    source: str,
    source_mode: Literal["direct", "source_file", "automatic"] = "direct",
    source_ref: str = "",
) -> dict[str, Any]:
    """Put one reference PoB source into case-bound quarantine.

    `direct` accepts a PoB code/link/XML, `source_file` accepts a local file path, and `automatic`
    accepts import material already collected by the existing poe.ninja collector. Raw code/XML is
    never returned and is never written to campaign state, reports, Memory, or Git.
    """
    return learning_service.intake_case(
        campaign_id=campaign_id,
        expected_revision=expected_revision,
        operation_id=operation_id,
        source=source,
        source_mode=source_mode,
        source_ref=source_ref,
    )


@mcp.tool()
def claim_learning_phase(
    campaign_id: str,
    case_id: str,
    phase: Literal["profile", "create", "compare", "learn", "rereview"],
    task_id: str,
    thread_id: str,
    expected_revision: int,
    operation_id: str,
) -> dict[str, Any]:
    """Claim one Phase 7 checkpoint with CAS and an explicit Desktop task/thread binding.

    Profile/Compare/Learn/Rereview must use the same Reference/Comparator task. Create must use a
    different task and thread. One campaign has only one active case.
    """
    return learning_service.claim_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        phase=phase,
        task_id=task_id,
        thread_id=thread_id,
        expected_revision=expected_revision,
        operation_id=operation_id,
    )


@mcp.tool()
def load_learning_reference_case(
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
) -> dict[str, Any]:
    """Load a claimed quarantined reference into this task's active PoB session without raw output."""
    return learning_service.load_reference_into_engine(
        get_engine(),
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=claim_id,
        thread_id=thread_id,
    )


@mcp.tool()
def submit_learning_profile(
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
    expected_revision: int,
    operation_id: str,
    identity_records: list[dict[str, Any]],
    target_level: int,
    version_context: dict[str, Any],
    reference_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Infer the exact existing Research Family and persist a safe reference Profile.

    Ambiguous Family evidence or a level mismatch fails the case closed. The output FamilyTarget
    excludes reference gear, passives, skill groups, configuration, mechanisms, and Judge results.
    """
    return learning_service.submit_profile(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=claim_id,
        thread_id=thread_id,
        expected_revision=expected_revision,
        operation_id=operation_id,
        identity_records=identity_records,
        target_level=target_level,
        version_context=version_context,
        reference_evidence=reference_evidence,
    )


@mcp.tool()
def get_learning_create_packet(
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
) -> dict[str, Any]:
    """Return the Create task's blind FamilyTarget + level packet; never reference build details."""
    return learning_service.get_blind_create_packet(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=claim_id,
        thread_id=thread_id,
    )


@mcp.tool()
def query_learning_memory(
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
    expected_revision: int,
    operation_id: str,
    dimensions: list[str] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Recall Memory in an active Create claim and persist a safe use-audit receipt."""
    return learning_service.query_memory_for_create(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=claim_id,
        thread_id=thread_id,
        expected_revision=expected_revision,
        operation_id=operation_id,
        dimensions=dimensions,
        limit=limit,
    )


@mcp.tool()
def query_public_learning_memory(
    family_key: str,
    target_level: int,
    version_context: learning_models.LearningVersionContext,
    dimensions: list[str] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Recall copy-safe public/local Learning Memory for an ordinary Create.

    Unlike ``query_learning_memory``, this read-only entry is not tied to a Phase 7 blind-create
    claim and does not write a campaign receipt.  It returns only the release-seeded plus local
    append-only lesson projection; raw cases, campaign state, and source material are never read.
    """
    return learning_memory.query_memory(
        family_key=family_key,
        target_level=target_level,
        version_context=(
            version_context.model_dump(mode="json", by_alias=True)
            if isinstance(version_context, learning_models.LearningVersionContext)
            else version_context
        ),
        dimensions=dimensions,
        limit=limit,
    )


@mcp.tool()
def cleanup_completed_task_runtime(
    task_kind: Literal["generation", "research", "learning_campaign"],
    task_id: str,
    allow_rejected: bool = False,
    abandon_incomplete: bool = False,
) -> dict[str, Any]:
    """Delete one completed task's private runtime state after its durable result is safe.

    Learning Memory, Research Memory, release seeds, and user-exported files are never deleted.
    Active, unreviewed, unexported, paused, or still-referenced tasks fail closed.
    ``allow_rejected`` is a research opt-in: permits cleanup when the run also contains
    acceptance_rejected cases blocked by source-data gaps (at least one case must still
    hold accepted durable records). Default stays strict.
    ``abandon_incomplete`` is a separate Research-only opt-in that requires an explicit user
    decision to discard an unfinished run. It releases only exact queued intake-ledger
    reservations owned by that run; accepted ledger history and Research Memory are preserved.
    """
    return task_cleanup.cleanup_completed_task_runtime(
        task_kind=task_kind,
        task_id=task_id,
        allow_rejected=allow_rejected,
        abandon_incomplete=abandon_incomplete,
    )


@mcp.tool()
def submit_learning_create_result(
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
    expected_revision: int,
    operation_id: str,
    identity_records: list[dict[str, Any]],
    target_level: int,
    artifact_id: str,
    generated_evidence: dict[str, Any],
    learning_memory_use: dict[str, Any],
) -> dict[str, Any]:
    """Commit the one allowed Create result after exact Family/level readback and Memory-use audit."""
    return learning_service.submit_create_result(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=claim_id,
        thread_id=thread_id,
        expected_revision=expected_revision,
        operation_id=operation_id,
        identity_records=identity_records,
        target_level=target_level,
        artifact_id=artifact_id,
        generated_evidence=generated_evidence,
        learning_memory_use=learning_memory_use,
    )


@mcp.tool()
def submit_learning_comparison(
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
    expected_revision: int,
    operation_id: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    """Commit the independent Comparator's ten-dimension report.

    Judge attachments must say `advisoryOnly=true`; the service validates but never derives a
    winner from Judge scores and never writes reward.
    """
    return learning_service.submit_comparison(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=claim_id,
        thread_id=thread_id,
        expected_revision=expected_revision,
        operation_id=operation_id,
        report=report,
    )


@mcp.tool()
def propose_learning_lesson(
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
    proposal: dict[str, Any],
) -> dict[str, Any]:
    """Append one reviewed cross-dimensional Create lesson to local Learning Memory.

    Concrete knowledge that fits a Research record kind must be sent through Research instead;
    this schema requires `dbFit=false`.
    """
    return learning_service.propose_memory_lesson(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=claim_id,
        thread_id=thread_id,
        proposal=proposal,
    )


@mcp.tool()
def append_learning_memory_correction(
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
    correction: dict[str, Any],
) -> dict[str, Any]:
    """Append narrow/revise/supersede/deprecate history; never overwrite a prior lesson."""
    return learning_service.correct_memory_lesson(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=claim_id,
        thread_id=thread_id,
        correction=correction,
    )


@mcp.tool()
def complete_learning_case_feedback(
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
    expected_revision: int,
    operation_id: str,
    mutations: list[Literal["none", "research", "memory", "code"]],
    research_refs: list[str] | None = None,
    memory_lesson_ids: list[str] | None = None,
    correction_ids: list[str] | None = None,
    code_change_refs: list[str] | None = None,
    backlog: list[str] | None = None,
) -> dict[str, Any]:
    """Record Fix/Learn routing and require conditional rereview after any mutation.

    A backlog pauses for human product/architecture decisions. This never regenerates the case.
    """
    return learning_service.complete_learning(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=claim_id,
        thread_id=thread_id,
        expected_revision=expected_revision,
        operation_id=operation_id,
        mutations=mutations,
        research_refs=research_refs,
        memory_lesson_ids=memory_lesson_ids,
        correction_ids=correction_ids,
        code_change_refs=code_change_refs,
        backlog=backlog,
    )


@mcp.tool()
def submit_learning_rereview(
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
    expected_revision: int,
    operation_id: str,
    accepted: bool,
    summary: str,
    safe_evidence_refs: list[str],
) -> dict[str, Any]:
    """Finish conditional rereview of code/Research/Memory changes without rerunning Create."""
    return learning_service.submit_rereview(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=claim_id,
        thread_id=thread_id,
        expected_revision=expected_revision,
        operation_id=operation_id,
        accepted=accepted,
        summary=summary,
        safe_evidence_refs=safe_evidence_refs,
    )


@mcp.tool()
def fail_learning_phase(
    campaign_id: str,
    case_id: str,
    claim_id: str,
    thread_id: str,
    expected_revision: int,
    operation_id: str,
    error_code: str,
) -> dict[str, Any]:
    """Mark the currently claimed phase failed so it can be explicitly retried."""
    return learning_service.fail_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=claim_id,
        thread_id=thread_id,
        expected_revision=expected_revision,
        operation_id=operation_id,
        error_code=error_code,
    )


@mcp.tool()
def retry_learning_phase(
    campaign_id: str,
    case_id: str,
    expected_revision: int,
    operation_id: str,
) -> dict[str, Any]:
    """Explicitly retry a failed phase; a consumed Create result can never be retried."""
    return learning_service.retry_failed_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        expected_revision=expected_revision,
        operation_id=operation_id,
    )


@mcp.tool()
def pause_learning_campaign(
    campaign_id: str,
    expected_revision: int,
    operation_id: str,
    reason: str,
) -> dict[str, Any]:
    """Pause at a safe checkpoint; a running claim returns to its pending phase."""
    return learning_service.pause_campaign(
        campaign_id=campaign_id,
        expected_revision=expected_revision,
        operation_id=operation_id,
        reason=reason,
    )


@mcp.tool()
def resume_learning_campaign(
    campaign_id: str,
    expected_revision: int,
    operation_id: str,
    human_decision: str = "",
) -> dict[str, Any]:
    """Resume a paused campaign, optionally recording a safe human backlog decision."""
    return learning_service.resume_campaign(
        campaign_id=campaign_id,
        expected_revision=expected_revision,
        operation_id=operation_id,
        human_decision=human_decision,
    )


@mcp.tool()
def get_learning_campaign_status(campaign_id: str) -> dict[str, Any]:
    """Return safe case progress, accumulated metrics, rolling windows, and the ten-case trend."""
    return learning_service.campaign_status(campaign_id=campaign_id)


@mcp.tool()
def get_build_planner_converter_status() -> dict[str, Any]:
    """Check whether the pinned, isolated PoB-to-official-`.build` provider is ready."""
    return build_planner_converter.converter_status()


@mcp.tool()
def export_final_build_artifact(
    artifact_id: str,
    name: str = "",
    author: str = "",
    description: str = "",
    link: str = "",
) -> dict[str, Any]:
    """Convert one verified final PoB artifact to an official single-stage `.build` file.

    The stored PoB XML remains private. Conversion uses a pinned provider, validates the official
    Build Planner shape, blocks error-level warnings, and returns the local output path plus safe
    warnings for human in-game import review.
    """
    return build_planner_exporter.export_final_build_artifact(
        artifact_id,
        name=name,
        author=author,
        description=description,
        link=link,
    )


@mcp.tool()
def pinnacle_readiness(min_ehp: float = 20000, min_dps: float = 500000) -> dict[str, Any]:
    """Gate a build against the endgame/pinnacle checklist — defense beyond raw EHP, plus a DPS bar.

    This is NOT a campaign/starter gate. Do not use it to optimize an early-stage build: its chaos
    resistance, EHP, and DPS thresholds deliberately describe established endgame content.

    Engine-computed pass/fail for: elemental resists capped, chaos handled (capped OR Chaos
    Inoculation), a resist over-cap buffer (advisory, vs penetration/curses), EHP ≥ `min_ehp`, and
    DPS ≥ `min_dps` (uses FullDPS when higher). Defaults are a generic pinnacle bar — set them to the
    player's content. (For reference, real imported ~1M-DPS pinnacle builds often run only ~17–20k
    EHP and lean on Mageblood + charms + dodge, so EHP breadth/recovery matters more than a huge
    pool.) `pass` covers the critical criteria; the buffer is advisory. Verify recovery
    (regen/leech/recoup), ailment/stun handling, and DPS uptime in-game.
    """
    eng = get_engine()
    d = eng.get_defenses()
    b = eng.get_build()
    res = d.get("resistances") or {}
    over = d.get("resistOverCap") or {}
    stats = b.get("stats") or {}
    ci = "Chaos Inoculation" in (b.get("keystones") or [])
    ehp = d.get("totalEHP") or stats.get("TotalEHP") or 0
    dps = max(stats.get("FullDPS") or 0, stats.get("TotalDPS") or 0)
    elems = ("fire", "cold", "lightning")

    checks = [
        {
            "check": "elemental resists capped (75%)",
            "ok": all((res.get(e) or 0) >= 75 for e in elems),
            "detail": {e: res.get(e) for e in elems},
        },
        {
            "check": "chaos handled",
            "ok": ci or (res.get("chaos") or 0) >= 75,
            "detail": "Chaos Inoculation" if ci else f"chaos resist {res.get('chaos')}",
        },
        {
            "check": f"EHP >= {int(min_ehp)}",
            "ok": ehp >= min_ehp,
            "detail": round(ehp),
        },
        {
            "check": f"DPS >= {int(min_dps)}",
            "ok": dps >= min_dps,
            "detail": round(dps),
        },
        {
            "check": "resist over-cap buffer (advisory)",
            "ok": all((over.get(e) or 0) >= 5 for e in elems),
            "detail": {e: over.get(e) for e in elems},
            "advisory": True,
        },
    ]
    critical = [c for c in checks if not c.get("advisory")]
    return {
        "pass": all(c["ok"] for c in critical),
        "checks": checks,
        "note": (
            "Engine numbers; `pass` = the critical criteria (resists, chaos, EHP, DPS). Thresholds "
            "are defaults — pass min_ehp/min_dps for the player's content. Still verify recovery, "
            "ailment/stun handling, and DPS uptime in-game."
        ),
    }


@mcp.tool()
def compare_to(source: str, keys: list[str] | None = None) -> dict[str, Any]:
    """Compare the active build against another build (code/link/XML) without losing it.

    Snapshots the current build, loads `source` to read its stats, then restores the
    current build. Returns the current stats, the other build's stats, and per-stat deltas
    (other - current).
    """
    try:
        other_xml = _source_to_xml(source)
    except (PobCodeError, ValueError) as e:
        return {"ok": False, "error": f"Could not read the comparison build: {e}"}
    eng = get_engine()
    snapshot = eng.get_xml()
    current = eng.get_stats(keys)["stats"]
    try:
        eng.load_build_xml(other_xml)
        other = eng.get_stats(keys)["stats"]
    finally:
        eng.load_build_xml(snapshot)
    delta = {
        k: other[k] - current[k]
        for k in current.keys() & other.keys()
        if isinstance(current[k], (int, float)) and isinstance(other[k], (int, float))
    }
    return {"current": current, "other": other, "delta": delta}


@mcp.tool()
def solve_for(metric: str, target: float, lever: str, tolerance: float = 0.01) -> dict[str, Any]:
    """Solve for the magnitude of one modifier needed to reach a stat target on the active build.

    Holds the build fixed and binary-searches `lever` until `metric` reaches `target` — every
    probe is a real engine evaluation, so the answer is computed, not estimated. Example:
    `solve_for("TotalDPS", 1000000, "increased fire damage")` →
    "you need ≈ +N% increased Fire Damage."

    `lever` is a named lever (e.g. "increased fire damage", "attack speed", "maximum life",
    "increased critical strike chance") or a raw custom-mod template containing "{}" for the
    magnitude (e.g. "+{} to Level of all Fire Skills"). Returns the required magnitude, or flags
    the target unreachable with the best achievable value (and `alreadyMet` if you're past it).

    Scope: ONE lever, ONE (increasing) metric. It does not balance survivability or cost and
    reports a *requirement* — verify with get_defenses / evaluate_build and confirm the magnitude
    is attainable via search_mods / find_supports_for.
    """
    return solver.solve_for(
        get_engine(), metric=metric, target=target, lever=lever, tolerance=tolerance
    )


@mcp.tool()
def rank_levers(
    metric: str = "TotalDPS", unit: float = 10.0, levers: list[str] | None = None
) -> dict[str, Any]:
    """Rank which stat levers give the most `metric` per unit on the active build — the min/max
    direction-finder ("where do I invest next?").

    Applies each lever at `unit` (default 10 = "10%" or "+10") and measures the real Δmetric,
    ranked high→low — so you can see, e.g., that lightning penetration beats increased lightning
    damage for this build. Defaults to a broad damage+defense set; pass build-specific `levers`
    (custom-mod templates containing "{}", e.g. "{}% increased Lightning Damage", "Damage
    Penetrates {}% Lightning Resistance") for sharper guidance. Greedy/marginal — levers are
    measured independently, so verify combined picks (more-multiplier stacking, breakpoints)
    together. Every value is engine-computed; use it to direct gear/tree/support choices.
    """
    return solver.rank_levers(get_engine(), metric=metric, unit=unit, levers=levers)


@mcp.tool()
def list_levers() -> dict[str, Any]:
    """List the named levers accepted by `solve_for` and `rank_levers` (discoverability).

    Returns the recognized lever names plus guidance: names are forgiving (a directional phrase
    like "increased lightning damage" works even if unlisted), and you can pass any PoB mod text
    containing "{}" as a custom lever. A lever only moves a metric if it actually applies to the
    build (crit needs a crit build, attack speed needs an attack skill, the damage type must match).
    """
    return solver.list_levers()


@mcp.tool()
def search_passives(
    query: str = "",
    node_type: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    """Search the active build's passive tree by node name or stat text.

    `node_type` filters by kind: "Notable", "Keystone", "Mastery", or "Normal" (small nodes).
    Returns nodes with their id, stats, whether they're allocated, and `pathDist` (points to
    reach from the current tree; absent if unreachable). Use the id with alloc/dealloc.
    """
    return get_engine().search_passives(query=query, node_type=node_type, limit=limit)


@mcp.tool()
def get_passive(node: str | int) -> dict[str, Any]:
    """Return a passive node's details by id (preferred) or exact name."""
    return get_engine().get_passive(node)


@mcp.tool()
def alloc_passive(node: str | int) -> dict[str, Any]:
    """Allocate a passive node (and the shortest path to it) by id or name.

    Returns points spent and the resulting stat deltas. Fails if the node isn't reachable
    from the currently allocated tree.
    """
    return get_engine().alloc_passive(node)


@mcp.tool()
def dealloc_passive(node: str | int) -> dict[str, Any]:
    """Deallocate a passive node (and nodes that depend on it) by id or name.

    Returns points freed and the resulting stat deltas.
    """
    return get_engine().dealloc_passive(node)


@mcp.tool()
def optimize_passives(
    metric: str = "TotalDPS",
    points: int = 0,
    node_type: str = "Notable",
    candidates: int = 50,
    goals: dict[str, float] | None = None,
    require: list[str | int] | None = None,
    reset: bool = False,
    preview: bool = False,
    expected_state_hash: str | None = None,
) -> dict[str, Any]:
    """Reproducibly optimize passive points from an immutable snapshot.

    Normal Create may use bounded non-reset requests for an identified local gap or a
    deliberate high-impact quality pass. The `reset=True, points=0` whole-tree replan is outside
    the current Create policy; use explicit passive nodes or a bounded non-reset request instead.

    Goal modes: single `metric` ("TotalDPS"/"Life"/"TotalEHP"...); `metric="balanced"` (offense
    AND defense); or weighted `goals` like {"TotalDPS":0.5,"Life":0.3,"CritChance":0.2} (relative
    gains). A goal whose base is ~0 (e.g. crit on a non-crit build) contributes nothing — fix the
    base first.

    `require=[node ids/names]` allocates those nodes (+ shortest path) first, then optimizes the
    rest within budget (never over-allocates; skipped requires in `requireSkipped`).
    `reset=True` deallocates the tree (keeping ascendancy) to re-plan from scratch. `points`
    defaults to 0 = the FULL remaining passive budget; pass a positive number only to CAP
    allocation. Ascendancy is a SEPARATE 8-point pool, auto-allocated regardless of `points`.
    `preview=True` returns the exact plan without changing the build. A commit runs on an isolated
    snapshot and succeeds only if the active state still matches `expected_state_hash` (when
    supplied) and the captured input hash; the response binds optimizer/request/input/output
    hashes and returns exact allocated/path node ids.

    Bounded greedy search, not a global optimum.
    """
    return passiveopt.optimize_passives(
        get_engine(),
        metric=metric,
        points=points,
        node_type=node_type,
        candidates=candidates,
        goals=goals,
        require=require,
        reset=reset,
        preview=preview,
        expected_state_hash=expected_state_hash,
    )


@mcp.tool()
def scaffold_gear(
    pool: str = "auto", target_resist: int = 75, slots: list[str] | None = None
) -> dict[str, Any]:
    """Fill the active build's EMPTY armour/jewellery slots with placeholder BASELINE gear.

    Closes the build's *actual* defensive gaps so a from-scratch skeleton becomes engine-
    evaluable: it adds only the resistances that are below `target_resist` (default 75 — a build
    already capping a resist gets none) and a hit pool. `pool` is "auto" (Energy Shield for an
    ES/CI build, else Life), "life", "energy_shield", or "none". `slots` limits which empty slots
    to fill (default all). The items are an explicit BASELINE — NOT the player's real gear and NOT
    optimal; the assistant still chooses the weapon and offense/identity gear (via equip_item).
    Use this to complete a build's defenses, then re-check with get_defenses / evaluate_build and
    price the real versions with get_prices — and never present scaffolded gear as finished.
    """
    return scaffold.scaffold_gear(get_engine(), pool=pool, target_resist=target_resist, slots=slots)


@mcp.tool()
def optimize_item(
    slot: str,
    metric: str = "TotalDPS",
    base: str | None = None,
    ilvl: int = 82,
    rolls: str = "realistic",
    thorough: bool = False,
    keep_resists_capped: bool = True,
    goals: dict[str, float] | None = None,
    planning: bool = False,
) -> dict[str, Any]:
    """Craft the best-in-slot rare for a `slot` — one `metric`, or a weighted `goals` blend.

    Searches the slot's REAL craftable affix pool (base mod restrictions) and greedily fills
    prefixes/suffixes respecting the 3/3 limits and mod-group exclusivity; every candidate is
    engine-computed. `base` defaults to the currently-equipped base (so a wand build stays a
    wand); pass it to try another base. `rolls`: "realistic" (default) or "max" (idealized T1).
    `thorough=true` adds a swap pass. Returns the crafted item (equip with equip_item), the
    before/after numbers, and a warning if it breaks a resistance cap.

    `planning=true` keeps an otherwise-legal candidate when the CURRENT character only lacks
    attributes to equip it: instead of discarding, it returns `projectedShortfalls` plus real
    `bridgeAffixSuggestions` so gear assembly can be ordered (equip a bridge piece first, then
    re-run). Formal Judge/artifact paths still require the fully-legal build.

    For realistic endgame gear pass `goals` (e.g. {"TotalDPS": 0.6, "TotalEHP": 0.4}) so the
    craft balances offense AND defense in one piece; a single `metric` craft strips the other
    axis (no life/resists). A blended craft returns `metricsBefore`/`metricsAfter` per goal.
    Re-check `get_defenses` after equipping.

    Each result reports `attainability` (per affix: required ilvl + tier depth) and a coarse
    `craft` effort rating — a realism check from tier depth, NOT a market price (no spawn-weight
    data). The crafted item is a *theoretical best-in-slot target*; verify price with
    get_prices. Bounded greedy search, not a global optimum.
    """
    return itemopt.optimize_item(
        get_engine(),
        slot,
        metric=metric,
        base=base,
        ilvl=ilvl,
        rolls=rolls,
        thorough=thorough,
        keep_resists_capped=keep_resists_capped,
        goals=goals,
        planning=planning,
    )


@mcp.tool()
def rank_upgrades(
    metric: str = "TotalDPS",
    goals: dict[str, float] | None = None,
    slots: list[str] | None = None,
    rolls: str = "realistic",
    top: int = 8,
) -> dict[str, Any]:
    """Rank gear slots by upgrade potential — "what should I craft/upgrade next?".

    Recrafts each gear slot to its best (same crafter as optimize_item — a single `metric` or a
    weighted `goals` blend like {"TotalDPS":0.6,"TotalEHP":0.4}) and ranks slots by the gain over
    your CURRENT item there, so the top slot is where the next upgrade buys the most. Read-only —
    every probe is snapshotted and restored. Gains are NOT additive (recrafting one slot shifts the
    others): recraft the top slot, equip it, then re-run. Empty slots with no base are skipped —
    explore those with optimize_item(slot, base=…). Targets are theoretical; price with get_prices.
    """
    return itemopt.rank_upgrades(
        get_engine(), metric=metric, goals=goals, slots=slots, rolls=rolls, top=top
    )


@mcp.tool()
def optimize_supports(
    metric: str = "TotalDPS",
    goals: dict[str, float] | None = None,
    max_supports: int = 5,
    candidates: int = 16,
) -> dict[str, Any]:
    """Choose the best support-gem set for the active main skill (engine-measured).

    Supports are usually a build's biggest "more" multiplier, but the corpus stores no support
    MAGNITUDES — so this values them empirically. It picks the candidate pool by MEASUREMENT, not
    tags (solo-measuring each tag-relevant support and keeping the strongest, so premier levers like
    penetration aren't missed just because they share few tags), then greedily adds the support that
    most raises the goal on the REAL build, round by round, until the sockets are full or nothing
    helps. Pass `goals` (weighted, e.g. {"TotalDPS":0.7,"TotalEHP":0.3}) to blend objectives; omit
    for a single `metric`. Read-only (the build is restored); raise `candidates` for a wider greedy
    search. Apply the result with set_skill. Greedy, not a global optimum.
    """
    return supportopt.optimize_supports(
        get_engine(), metric=metric, goals=goals, max_supports=max_supports, candidates=candidates
    )


@mcp.tool()
def optimize_jewel(
    metric: str = "TotalDPS",
    base: str = "Emerald",
    goals: dict[str, float] | None = None,
    rolls: str = "realistic",
) -> dict[str, Any]:
    """Craft the best-in-slot rare JEWEL for the active build (one metric or a weighted goals blend).

    A jewel's explicit mods apply globally, so each candidate is measured as a real modifier on the
    build and ranked by marginal gain (jewel mods are ~independent, so the top picks ≈ the best
    jewel). Pick a `base` matching the socket's attribute — Emerald=dex, Ruby=str, Sapphire=int,
    Diamond=all. Returns a jewel to socket with equip_jewel into an ALLOCATED tree socket
    (list_jewel_sockets); verify the base's affix limit. Radius/Time-Lost jewels aren't modelled
    here (their effect is positional). Read-only: the build is restored.
    """
    return itemopt.optimize_jewel(get_engine(), metric=metric, base=base, goals=goals, rolls=rolls)


@mcp.tool()
def plan_gear(
    dps_weight: float = 0.7,
    rolls: str = "realistic",
    slots: list[str] | None = None,
    auto_base: bool = True,
    min_ehp: float | None = None,
    stage: Literal["auto", "campaign", "maps_entry", "endgame"] = "auto",
    chaos_resist_target: int | None = None,
) -> dict[str, Any]:
    """Plan a whole gear set that maximizes damage while capping resistances (budget allocation).

    Cross-slot trade-off: limited suffix slots for resistances, so the plan crafts OFFENSE slots
    damage-leaning and DEFENSE slots EHP-leaning (pulling missing resists onto defensive pieces),
    building each slot on the previous so the set is coherent. `dps_weight` (0..1) tilts the
    offense slots. `auto_base` (default on) fills EMPTY armour/jewellery slots with a sensible
    attribute-appropriate base so it builds a WHOLE set from scratch (weapons stay yours — they
    define the archetype). `min_ehp` sets a survivability floor: defensive slots re-craft toward
    pure EHP until TotalEHP reaches it (reports `ehpFloorMet`). `stage` defaults from character
    level and controls defense/offense trade-offs plus the non-CI chaos resistance target:
    campaign 0%, maps entry 30%, endgame 60% — once reached, chaos stops competing for suffixes.
    Use `chaos_resist_target=75` only for a deliberate pinnacle/content requirement, not a
    universal starter baseline.

    Returns the per-slot plan + projected whole-build DPS/EHP/resists; equip with equip_item.
    A heavier call (~10-20s); greedy heuristic — refine individual slots with optimize_item.
    """
    return itemopt.plan_gear(
        get_engine(),
        dps_weight=dps_weight,
        rolls=rolls,
        slots=slots,
        auto_base=auto_base,
        min_ehp=min_ehp,
        stage=stage,
        chaos_resist_target=chaos_resist_target,
    )


@mcp.tool()
def craft_item(
    slot: str,
    metric: str = "TotalDPS",
    base: str | None = None,
    goals: dict[str, float] | None = None,
    rolls: str = "realistic",
    rune_sockets: int = 2,
    ilvl: int = 82,
    use_essences: bool = True,
    use_corruption: bool = True,
) -> dict[str, Any]:
    """Craft the best-in-slot item using the FULL crafting system — beyond a plain rare.

    Where `optimize_item` crafts the best rare from the standard affix pool, this adds the three
    real PoE2 power sources, each valued on the engine (PoB owns the crafting data — nothing is
    invented): **runes / soul cores** (mods socketed on top of affixes), **essences** (force a
    mod; *Perfect* essences grant mods the normal pool can't roll), and **corruptions** (a
    corrupted implicit). Pass a single `metric` or a weighted `goals` blend; `rune_sockets` is
    how many the base is assumed to support (Artificer's Orb; martial weapons/armour typically
    allow up to 2). Returns the item + `craftSteps` (the corruption is a Vaal gamble — do it
    last). A theoretical best-in-slot target with idealized rolls; price the steps. The active
    build is restored, while a raw-free `craftReceiptRef` is persisted so later
    equip/checkpoint/Judge calls can verify special sources.
    """
    return craftopt.craft_item(
        get_engine(),
        slot,
        metric=metric,
        base=base,
        goals=goals,
        rolls=rolls,
        rune_sockets=rune_sockets,
        ilvl=ilvl,
        use_essences=use_essences,
        use_corruption=use_corruption,
    )


@mcp.tool()
def optimize_build(
    metric: str = "TotalDPS",
    min_ehp: float | None = 20000,
    levers: list[str] | None = None,
    tier: str = "Pinnacle",
    passes: int = 2,
    max_jewel_sockets: int = 3,
    try_uniques: bool = False,
    crafting: bool = False,
    combat: dict[str, Any] | None = None,
    archetypes: list[dict[str, Any]] | None = None,
    parallel: bool = False,
) -> dict[str, Any]:
    """Maintenance-only holistic optimizer, temporarily disabled by default.

    Normal Create runs must use Agent-selected exact mutations and focused component
    tools.  This retained entry only supports explicit optimizer maintenance experiments when the
    process owner opts in with ``POE2_ENABLE_GLOBAL_BUILD_OPTIMIZER=1``; otherwise it returns a typed
    disabled result without reading or changing the active build.
    """
    if os.environ.get("POE2_ENABLE_GLOBAL_BUILD_OPTIMIZER", "").strip() != "1":
        return {
            "status": "disabled",
            "ok": False,
            "errorCode": "global_optimizer_temporarily_disabled",
            "reason": (
                "The whole-build optimizer is disabled by default while Create quality is "
                "evaluated without global tree/gear search. Use exact mutations and targeted "
                "component tools instead."
            ),
            "enableEnvironmentVariable": "POE2_ENABLE_GLOBAL_BUILD_OPTIMIZER=1",
            "stateChanged": False,
        }
    return buildopt.optimize_build(
        get_engine(),
        metric=metric,
        min_ehp=min_ehp,
        levers=levers,
        tier=tier,
        passes=passes,
        max_jewel_sockets=max_jewel_sockets,
        try_uniques=try_uniques,
        crafting=crafting,
        combat=combat,
        archetypes=archetypes,
        parallel=parallel,
    )


def _server_version() -> str:
    """The installed server (code) version, read from the bundled manifest."""
    try:
        # Repository manifests are UTF-8 and contain Unicode punctuation. Relying on the
        # Windows locale here makes valid installs report "unknown" on GBK systems.
        return json.loads((paths.BUNDLE_ROOT / "manifest.json").read_text(encoding="utf-8")).get(
            "version", "unknown"
        )
    except (OSError, ValueError):
        return "unknown"


@mcp.tool()
def engine_health() -> dict[str, Any]:
    """Report engine + install diagnostics: liveness, LuaJIT and passive-tree versions, the
    installed data/server versions, and whether data is served from the auto-updated user-data
    copy or the bundled seed — so you can confirm exactly what's running.
    """
    eng = get_engine()
    health = eng.ping()  # {pong, jit}
    info = getattr(eng, "info", {}) or {}
    from_user_data = (paths.user_data_dir() / "corpus.sqlite").exists()
    return {
        **health,
        "treeVersion": info.get("treeVersion"),
        "dataVersion": live_update.installed_version(),
        "serverVersion": _server_version(),
        "dataSource": "user-data" if from_user_data else "bundled",
    }


# --------------------------------------------------------------------------------------
# Corpus / knowledge tools (bundled SQLite; no engine required)
# --------------------------------------------------------------------------------------
@mcp.tool()
def search_items(
    query: str = "",
    item_class: str | None = None,
    limit: int = 20,
    max_drop_level: int | None = None,
    order: str = "drop_desc",
) -> list[dict[str, Any]]:
    """Search Path of Exile 2 item bases by name/tags, optionally filtered by item class.

    `max_drop_level` filters to bases obtainable by a character level (e.g. 18 for a campaign
    snapshot); `order` is "drop_desc" (highest tier first, default) or "drop_asc"
    (campaign-friendly). Returns matching bases (name, item_class, drop_level, tags). Use
    `get_item` for full detail.
    """
    return corpus.search_items(
        query=query,
        item_class=item_class,
        limit=limit,
        max_drop_level=max_drop_level,
        order=order,
    )


@mcp.tool()
def get_item(name_or_id: str) -> dict[str, Any] | None:
    """Return full data for a single item base by exact name or metadata id."""
    return corpus.get_item(name_or_id)


@mcp.tool()
def find_skills(
    query: str = "",
    gem_type: str | None = None,
    tag: str | None = None,
    color: str | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Find skill/support gems by text, tag, color, or type.

    `gem_type` is one of "active", "support", "spirit". `tag` filters by gem tag (e.g. "fire",
    "projectile", "minion"). `color` is "r"/"g"/"b". Returns gems with recommended supports.
    """
    return corpus.find_skills(query=query, gem_type=gem_type, tag=tag, color=color, limit=limit)


@mcp.tool()
def get_gem(name_or_id: str) -> dict[str, Any] | None:
    """Return full data for a single gem by name or id (tags, granted skills, supports, types)."""
    return corpus.get_gem(name_or_id)


@mcp.tool()
def list_skills_for_level(
    level: int,
    gem_type: str | None = None,
    class_key: str | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """List gems usable as ACQUISITION references at `level`, optionally class/type-filtered.

    NOTE the level semantics: the corpus has no reliable character-level gem requirement — this
    filter is SOFT (crafting-level ≤ level, plus unknown) and every entry carries
    ``craftingLevelIsReference``. TRUE level availability must be verified on the engine
    (``validate_level_availability`` / PoB readback); treat this as a candidate pool, not a gate.
    `class_key` filters by the base class's dominant attribute (e.g. "Ranger" → dexterity gems).
    """
    return corpus.list_gems_for_level(
        level=level, gem_type=gem_type, class_key=class_key, limit=limit
    )


@mcp.tool()
def validate_level_availability(
    skill_keys: list[str],
    level: int,
    class_key: str | None = None,
) -> dict[str, Any]:
    """Verify candidate skills at a target level (constraint-layer reference, not a hard gate).

    Uses the PoB engine's real per-level gem requirements plus the corpus' attribute weights to
    report each skill as ok / partial / unavailable. This is the constraint layer for directions
    proposed by the Agent (web research + model knowledge); it never picks a direction, and the
    final legality and numbers always come from PoB readback / Judge.
    """
    return generation_leveled_build.validate_level_availability(
        get_engine(), skill_keys=skill_keys, level=level, class_key=class_key
    )


@mcp.tool()
def find_supports_for(skill: str, limit: int = 25) -> dict[str, Any]:
    """List support gems for a skill: curated recommendations + tag-compatible supports (most
    relevant first). This only LISTS candidates — to actually pick the best set, use
    `optimize_supports`, which measures each on the engine (the corpus has no support magnitudes).
    """
    return corpus.find_supports_for(skill, limit=limit)


@mcp.tool()
def explain_mechanic(topic: str) -> dict[str, Any]:
    """Explain a Path of Exile 2 mechanic (corpus — offline, deterministic).

    Returns our evergreen `principle` (hand-authored) plus the matching auto-refreshed `wiki`
    page when one exists (attributed: PoE2 Wiki, CC BY-NC-SA 3.0 — cite it when you use it).
    Curated principle topics include: resistances, ailments, armour, evasion, energy_shield,
    spirit, critical_strike, ehp, accuracy, recovery. If nothing matches, use `search_mechanics`
    to browse, or `lookup_mechanic` to fetch a page live from the wiki.
    """
    return mechanics.explain(topic)


@mcp.tool()
def search_mechanics(query: str, limit: int = 8) -> dict[str, Any]:
    """Full-text search the bundled wiki mechanics tier (corpus — offline, deterministic).

    Returns matching page titles + snippets + source links so you can pick one to read with
    `explain_mechanic`. Wiki content is PoE2 Wiki, CC BY-NC-SA 3.0 — attribute it when quoting.
    For a page not bundled here, use `lookup_mechanic` (live wiki fetch).
    """
    results = corpus.search_mechanics(query, limit=limit)
    return {
        "query": query,
        "results": results,
        "note": "Bundled wiki mechanics (CC BY-NC-SA 3.0). Use explain_mechanic(title) to read "
        "one; lookup_mechanic(topic) to fetch a page not in the corpus.",
    }


@mcp.tool()
def relevant_mechanics() -> dict[str, Any]:
    """The mechanics worth understanding for the ACTIVE build (corpus + engine).

    Reads the current build's signals — main skill + its tags (and the ailment its damage type
    builds), keystones, ascendancy notables, plus staples — and points each at its best corpus
    mechanics page. Also surfaces the engine's damage diagnostic, so an uncomputable layer
    (reservation buff, undamageable minion, %-life/corpse detonation) is called out up front.
    Use it when starting/auditing a build to read up before theorycrafting.
    """
    eng = get_engine()
    build = eng.get_build()
    skill = build.get("mainSkill")
    tags: list[str] = []
    if skill:
        gem = corpus.get_gem(skill)
        if gem:
            tags = gem.get("tags") or []
    topics = mechanics.relevant(
        skill=skill,
        tags=tags,
        keystones=build.get("keystones") or [],
        ascendancy=build.get("ascendancyNotables") or [],
    )
    diagnostic = eng.get_stats(["TotalDPS"]).get("warning")
    return {
        "mainSkill": skill,
        "relevant": topics,
        "diagnostic": diagnostic,
        "note": "Read these with explain_mechanic(title); use lookup_mechanic for anything not "
        "listed. Wiki content is CC BY-NC-SA 3.0 — attribute it. If `diagnostic` is set, that "
        "damage layer isn't engine-computable — validate it in-game.",
    }


@mcp.tool()
def build_advice(topic: str = "") -> dict[str, Any]:
    """Curated PoE2 build-planning heuristics, not versioned mechanical authority.

    Omit `topic` for the framing + section list; pass a topic (e.g. "defense", "offense",
    "resistances", "crit", "spirit", "red flags") to get that section. Current pinned PoB data,
    the physical graph, and the current corpus override patch-sensitive statements in this prose;
    actual DPS/EHP numbers still come from the compute tools.
    """
    return advice.advise(topic)


def _live_meta_context(limit: int) -> dict[str, Any]:
    """Fetch live meta context without letting one unavailable slice block lifecycle research."""
    try:
        return live_meta.get_meta_context(ascendancy_limit=limit, archetype_limit=limit)
    except live_meta.MetaError as e:
        return {
            "ok": False,
            "error": f"meta data unavailable: {e}",
            "archetypeTrends": {
                "ok": False,
                "source": "poe.ninja",
                "kind": "archetype_trends",
                "archetypes": [],
                "error": f"archetype trend data unavailable: {e}",
                "evidenceTags": ["live-meta", "unavailable"],
            },
        }


@mcp.tool()
def suggest_build_lifecycle(
    goal: str,
    preferences: str | None = None,
    budget: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """Research a staged PoE2 build route: campaign starter → transition → endgame.

    Use this when the user asks for a strong build but has not supplied a skill/item anchor, or
    when an endgame build might be impossible to level directly. The response is a lifecycle
    scaffold with evidence labels and transition gates; run PoB verification for each stage before
    presenting DPS/EHP/resistance numbers.
    """
    freshness = freshness_service.get_freshness_report()
    meta = _live_meta_context(limit=5)
    return lifecycle.research_build_lifecycle(
        goal,
        preferences=preferences,
        budget=budget,
        mode=mode,
        freshness=freshness,
        meta=meta,
        persist=True,
    )


@mcp.tool()
def analyze_lifecycle_cohort(
    goal: str,
    preferences: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Analyze non-copyable lifecycle cohort evidence for a natural-language build goal.

    This is a research inspection tool: it summarizes recurring levers, delivery traits, defenses,
    and live ascendancy context from calibration sources. It does not produce a final build and must
    not be treated as permission to copy a reference build.
    """
    meta = _live_meta_context(limit=limit)
    return lifecycle.analyze_lifecycle_cohort(
        goal,
        preferences=preferences,
        meta=meta,
        limit=limit,
    )


@mcp.tool()
def analyze_build_lifecycle(source: str) -> dict[str, Any]:
    """Import or inspect a build source and classify its lifecycle viability.

    The tool answers whether the build can be used as a starter, needs a separate starter route,
    or should be treated as endgame-only. If import succeeds, the source becomes the active build
    just like `import_build`; if import fails, the result is still a structure-only lifecycle
    analysis with the import error attached.
    """
    imported = import_build(source)
    if not imported.get("ok", True):
        return lifecycle.analyze_build_lifecycle(source, import_error=imported.get("error"))
    eng = get_engine()
    return lifecycle.analyze_build_lifecycle(
        source,
        imported_build=eng.get_build(),
        import_caveats=imported.get("importCaveats") or [],
    )


@mcp.tool()
def compare_lifecycle_routes(route_a: dict[str, Any], route_b: dict[str, Any]) -> dict[str, Any]:
    """Compare two lifecycle route dictionaries for starter/transition/endgame trade-offs."""
    return lifecycle.compare_lifecycle_routes(route_a, route_b)


@mcp.tool()
def audit_lifecycle_route(route: dict[str, Any]) -> dict[str, Any]:
    """Audit whether a lifecycle route has the minimum structure needed before presentation.

    This is a structural quality gate, not a power check: it verifies starter/maps/endgame stages,
    transition gates, evidence tags, and verification plans before a route is treated as complete.
    """
    return lifecycle.lifecycle_quality.audit_lifecycle_route(route)


@mcp.tool()
def evaluate_lifecycle_route(
    route: dict[str, Any],
    reference_profile: dict[str, Any] | None = None,
    goal: str | None = None,
) -> dict[str, Any]:
    """Evaluate a lifecycle route for regression/development review.

    This tool re-audits route structure and compares only safe, non-copyable reference/cohort fields.
    It does not run PoB, fetch live data, write memory, or certify numeric DPS/EHP strength.
    """
    return lifecycle_eval.evaluate_lifecycle_route(
        route,
        reference_profile=reference_profile,
        goal=goal,
    )


@mcp.tool()
def list_transition_gates(build_id: str = "") -> dict[str, Any]:
    """List stored transition gates for a lifecycle build, or default gates when omitted."""
    return lifecycle.list_transition_gates(build_id or None)


@mcp.tool()
def evaluate_transition_readiness(
    from_stage: str,
    to_stage: str,
    state: dict[str, Any],
    build_id: str = "",
) -> dict[str, Any]:
    """Check whether a player should switch lifecycle stages now.

    `state` may include level, items, gems, ascendancyPoints, checks such as resists_capped or
    sustain_ok, and optional free-text feedback. A failed gate means hold the current stage and fix
    the missing requirements before recommending the next build form.
    """
    return lifecycle.evaluate_transition_readiness(
        build_id=build_id or None,
        from_stage=from_stage,
        to_stage=to_stage,
        state=state,
    )


@mcp.tool()
def plan_lifecycle_stage_verification(
    stage: str,
    state: dict[str, Any] | None = None,
    build_id: str = "",
) -> dict[str, Any]:
    """Return the PoB verification budget for one lifecycle stage.

    This is a plan, not a computed result: use it to decide which level, passive budget, gear
    assumption, metrics, and engine tools must be checked before making stage-specific claims.
    """
    result = lifecycle.lifecycle_verification.plan_stage_verification(stage, state=state)
    if build_id:
        result["buildId"] = build_id
    return result


def _typed_payload(value: Any) -> dict[str, Any]:
    """Normalize FastMCP Pydantic inputs while preserving direct-call test compatibility."""
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if not callable(dump):
        raise TypeError("typed MCP payload must be a mapping or Pydantic model")
    return dump(mode="json", by_alias=True)


@mcp.tool()
def verify_lifecycle_stage(
    stage: str,
    state: lifecycle.lifecycle_verification.LifecycleStageVerificationState | None = None,
    build_id: str = "",
    artifact_id: str = "",
    detail: Literal["compact", "full"] = "compact",
    strict_mode: bool = False,
) -> dict[str, Any]:
    """Execute lifecycle verification against the active build or one immutable artifact.

    Pulls the active build's PoB stats/defenses and evaluates the stage target checks, returning
    pass/fail/unknown without mutating gear, passives, level, or config. With `artifact_id`, the
    tool restores that private artifact itself and writes a trusted artifact-bound verification
    receipt (keeping the original artifact hash even when PoB's import/save XML is byte-unstable).
    ``detail="compact"`` (Create default) returns all blocking checks plus the bounded numeric
    evidence needed for the next decision; ``detail="full"`` only for focused diagnosis.
    Recommendations and advisory caveats are hidden unless ``strict_mode=true`` is supplied;
    computed checks and metrics still run.
    """
    state_payload = _typed_payload(state) if state is not None else {}
    plan = lifecycle.lifecycle_verification.plan_stage_verification(stage, state=state_payload)
    if not plan.get("ok"):
        return _project_lifecycle_verification_feedback(plan, strict_mode=strict_mode)

    eng = get_engine()
    artifact_manifest = None
    evidence_xml = None
    if artifact_id:
        verified_artifact = generation_artifacts.read_final_build_artifact_for_export(artifact_id)
        if verified_artifact is None:
            return {
                "ok": False,
                "stage": stage,
                "status": "unknown",
                "pass": False,
                "errorCode": "lifecycle_artifact_not_trusted",
            }
        artifact_manifest, evidence_xml = verified_artifact
        try:
            eng.load_build_xml(evidence_xml, name=artifact_manifest.artifact_id)
        except Exception:  # noqa: BLE001 - never expose engine internals through MCP.
            return {
                "ok": False,
                "stage": stage,
                "status": "unknown",
                "pass": False,
                "errorCode": "lifecycle_artifact_restore_failed",
            }
    try:
        source_before = eng.get_xml()
    except Exception:  # noqa: BLE001 - return a stable safe error, never engine internals.
        return {
            "ok": False,
            "stage": stage,
            "status": "unknown",
            "pass": False,
            "errorCode": "lifecycle_snapshot_unavailable",
        }
    raw_source_hash = judge_evaluator.compute_source_hash(source_before)
    # PoB refreshes derived output nodes such as PlayerStat and FullDPSSkill during otherwise
    # read-only calls. Raw XML hashes therefore produce false mutation conflicts after importing an
    # artifact. Use the shared semantic state projection for the no-mutation guard, while keeping
    # the original raw artifact/Judge hash as evaluatedSourceHash.
    restored_state_hash = compute_state.build_state_hash(source_before)
    evidence_xml = evidence_xml or source_before
    effective_state = dict(state_payload)
    main_skill_evidence = generation_preflight.inspect_main_skill_socketed(evidence_xml)
    # This evidence must come from the exact active XML snapshot. Never accept a caller-supplied
    # boolean as proof that the main skill is socketed.
    effective_state["mainSkillSocketed"] = bool(main_skill_evidence.get("socketed"))
    effective_state["mainSkillSocketEvidence"] = main_skill_evidence
    lifecycle_skill_evidence = generation_preflight.inspect_lifecycle_skill_evidence(
        evidence_xml,
        single_target_skill_name=effective_state.get("singleTargetSkillName"),
    )
    effective_state["ascendancyOrKeySupport"] = lifecycle_skill_evidence.get(
        "ascendancyOrKeySupport"
    )
    single_target_evidence = dict(lifecycle_skill_evidence.get("singleTargetDuty") or {})
    evidence_refs = list(effective_state.get("singleTargetEvidenceRefs") or [])
    single_target_evidence["evidenceRefs"] = evidence_refs
    single_target_evidence["verified"] = bool(
        single_target_evidence.get("verified") and evidence_refs
    )
    effective_state["singleTargetDuty"] = single_target_evidence
    build_defining_evidence = generation_preflight.inspect_lifecycle_component_evidence(
        evidence_xml,
        component_kind=effective_state.get("buildDefiningComponentKind"),
        component_name=effective_state.get("buildDefiningComponentName"),
    )
    build_defining_evidence["componentKey"] = effective_state.get("buildDefiningComponentKey")
    build_defining_refs = list(effective_state.get("buildDefiningEvidenceRefs") or [])
    build_defining_evidence["evidenceRefs"] = build_defining_refs
    build_defining_evidence["verified"] = bool(
        build_defining_evidence.get("verified")
        and build_defining_evidence.get("componentKey")
        and build_defining_refs
    )
    effective_state["buildDefiningComponent"] = build_defining_evidence
    # Flask presence is evidence from the evaluated build, never a caller-authorized boolean.
    read_build = getattr(eng, "get_build", None)
    build = read_build() if callable(read_build) else {}
    gear = build.get("gear") if isinstance(build, dict) else {}
    if isinstance(build, dict):
        try:
            actual_level = int(build.get("level") or 0)
        except (TypeError, ValueError):
            actual_level = 0
        if 1 <= actual_level <= 100:
            # Lifecycle resistance bands are keyed to the evaluated PoB level. A caller-provided
            # stage label or stale state hint must not move the build into a different band.
            effective_state["level"] = actual_level
    effective_state["manaFlaskEquipped"] = _mana_flask_equipped(gear)
    stat_keys = lifecycle.lifecycle_verification.requested_metric_keys(stage)
    stats_result = eng.get_stats(stat_keys)
    stats = stats_result.get("stats") if isinstance(stats_result, dict) else {}
    defenses = eng.get_defenses()
    # Preserve engine warnings as caveats instead of hiding them behind a boolean. This is
    # especially important for PoE2 mechanics that the pinned PoB runtime cannot model faithfully.
    engine_warning = None
    if isinstance(stats_result, dict):
        engine_warning = stats_result.get("warning") or stats_result.get("engineLimitation")
    result = lifecycle.lifecycle_verification.verify_stage_metrics(
        stage,
        stats=stats if isinstance(stats, dict) else {},
        defenses=defenses if isinstance(defenses, dict) else {},
        state=effective_state,
        engine_warning=engine_warning,
        unmodelled_mana_mechanisms=(
            generation_preflight.inspect_resource_model_gap(evidence_xml, gear).get(
                "mechanismNames"
            )
            or []
        ),
    )
    try:
        source_after = eng.get_xml()
    except Exception:  # noqa: BLE001 - return a stable safe error, never engine internals.
        return {
            "ok": False,
            "stage": stage,
            "status": "unknown",
            "pass": False,
            "errorCode": "lifecycle_snapshot_unavailable",
        }
    if compute_state.build_state_hash(source_after) != restored_state_hash:
        return {
            "ok": False,
            "stage": stage,
            "status": "unknown",
            "pass": False,
            "errorCode": "lifecycle_snapshot_changed_during_verification",
        }
    result["evaluatedSourceHash"] = (
        artifact_manifest.source_hash if artifact_manifest is not None else raw_source_hash
    )
    if build_id:
        result["buildId"] = build_id
    result = _project_lifecycle_verification_feedback(result, strict_mode=strict_mode)
    if artifact_manifest is not None:
        receipt = generation_progression_lifecycle.save_artifact_lifecycle_receipt(
            artifact_id=artifact_manifest.artifact_id,
            source_hash=artifact_manifest.source_hash,
            restored_engine_source_hash=restored_state_hash,
            result=result,
        )
        if receipt.get("status") != "recorded":
            return {
                "ok": False,
                "stage": stage,
                "status": "unknown",
                "pass": False,
                "errorCode": receipt.get(
                    "errorCode",
                    "artifact_lifecycle_receipt_write_failed",
                ),
            }
        result.update(
            {
                "verificationRef": receipt["verificationRef"],
                "artifactId": artifact_manifest.artifact_id,
                "restoredEngineSourceHash": restored_state_hash,
                "artifactBound": True,
            }
        )
    return (
        _compact_lifecycle_verification_response(result)
        if detail == "compact"
        else {**result, "responseProfile": "full"}
    )


def _project_lifecycle_verification_feedback(
    result: dict[str, Any],
    *,
    strict_mode: bool,
) -> dict[str, Any]:
    projected = deepcopy(result)
    projected["feedbackMode"] = "strict" if strict_mode else "hard_only"
    projected["subjectiveFeedbackSuppressed"] = not strict_mode
    if not strict_mode:
        projected["recommendedActions"] = []
        projected["caveats"] = []
    return projected


def _compact_lifecycle_verification_response(result: dict[str, Any]) -> dict[str, Any]:
    """Project a full computed verification into a bounded Create decision packet."""

    observations = result.get("observations")
    observations = observations if isinstance(observations, dict) else {}
    checks = result.get("checks")
    checks = [row for row in checks if isinstance(row, dict)] if isinstance(checks, list) else []
    state_snapshot = result.get("stateSnapshot")
    state_snapshot = state_snapshot if isinstance(state_snapshot, dict) else {}
    identity_keys = (
        "level",
        "mainSkillSocketed",
        "manaFlaskEquipped",
        "singleTargetSkillName",
        "buildDefiningComponentKind",
        "buildDefiningComponentName",
        "buildDefiningComponentKey",
    )
    metric_keys = (
        "resistances",
        "life",
        "energyShield",
        "totalPool",
        "totalEHP",
        "mana",
        "manaUnreserved",
        "manaCost",
        "netManaRegen",
        "manaRegenRecovery",
        "manaLeechGainRate",
        "manaOnHitRate",
        "skillUseRate",
        "manaSustain",
        "spirit",
        "offense",
    )
    compact: dict[str, Any] = {
        "ok": result.get("ok"),
        "stage": result.get("stage"),
        "status": result.get("status"),
        "pass": result.get("pass"),
        "failedChecks": list(result.get("failedChecks") or []),
        "unknownChecks": list(result.get("unknownChecks") or []),
        "checkStatuses": {
            str(row.get("check")): row.get("status") for row in checks if row.get("check")
        },
        "blockingChecks": [row for row in checks if row.get("status") in {"failed", "unknown"}],
        "stateSummary": {
            key: state_snapshot[key] for key in identity_keys if key in state_snapshot
        },
        "metrics": {key: observations[key] for key in metric_keys if key in observations},
        "recommendedActions": list(result.get("recommendedActions") or []),
        "caveats": list(result.get("caveats") or []),
        "evidenceTags": list(result.get("evidenceTags") or []),
        "feedbackMode": result.get("feedbackMode", "hard_only"),
        "subjectiveFeedbackSuppressed": bool(result.get("subjectiveFeedbackSuppressed", True)),
        "responseProfile": "compact",
    }
    for key in (
        "evaluatedSourceHash",
        "buildId",
        "verificationRef",
        "artifactId",
        "restoredEngineSourceHash",
        "artifactBound",
        "errorCode",
    ):
        if key in result:
            compact[key] = result[key]
    return compact


def _mana_flask_equipped(gear: Any) -> bool:
    if not isinstance(gear, dict):
        return False
    for slot, item in gear.items():
        if not str(slot).casefold().startswith("flask") or not isinstance(item, dict):
            continue
        text = f"{item.get('name') or ''} {item.get('base') or ''}".casefold()
        if "mana flask" in text:
            return True
    return False


@mcp.tool()
def record_build_feedback(
    build_id: str,
    stage: str,
    feedback: str,
    outcome: str | None = None,
) -> dict[str, Any]:
    """Record user practice feedback as episodic lifecycle memory.

    A single feedback report is not automatically promoted into a durable rule. Use
    `promote_technique_memory` only after the lesson is reusable and evidence-backed.
    """
    return lifecycle.record_build_feedback(
        build_id=build_id,
        stage=stage,
        feedback=feedback,
        outcome=outcome,
    )


@mcp.tool()
def promote_technique_memory(evidence_ids: list[str], reason: str) -> dict[str, Any]:
    """Promote verified feedback/evidence into durable, patch-scoped technique memory."""
    claim = lifecycle.current_compatibility_claim()
    return lifecycle.promote_technique_memory(
        evidence_ids=evidence_ids,
        reason=reason,
        current_patch=claim.get("game_patch"),
        current_tree=claim.get("passive_tree"),
    )


@mcp.tool()
def list_reference_builds(query: str = "", limit: int = 8) -> dict[str, Any]:
    """Browse engine-verified reference / CALIBRATION builds (corpus — offline, deterministic).

    A deliberately diverse set of real high-end builds across many ascendancies/skills, kept ONLY
    to calibrate. They are **not templates**: never copy, export, or recommend one wholesale when a
    user asks for a build — build to the USER's stated goal and use these to sanity-check it. Filter
    by `query` (class, ascendancy, skill, element, delivery like "spell"/"attack"/"minion", defense
    like "CI"/"mana", or a lever). Each result returns the build's VERIFIED DPS/EHP, its archetype
    tags, and the lever it scales on — enough to range-check a number or learn an archetype's
    dominant scaler, with deliberately nothing to copy (no code, gear, or passive list).
    """
    return refbuilds.search(query=query, limit=limit)


@mcp.tool()
def benchmark_build() -> dict[str, Any]:
    """Calibrate the ACTIVE build against the verified reference set (corpus + engine).

    Compares this build's computed DPS/EHP to the distribution of real high-end builds of the SAME
    delivery archetype (spell/attack/minion/…), and reports which levers those references scale on.
    Answers "is this build's number in a sane endgame range, and what should I scale next?" — it is
    a calibration check, NOT a license to copy a reference. The user's goal drives the build; if a
    number is low, find the missing multiplier on THIS build (rank_levers), don't clone a reference.
    """
    eng = get_engine()
    b = eng.get_build()
    s = b.get("stats", {}) or {}
    skill = b.get("mainSkill")
    delivery_tags = (
        "attack",
        "spell",
        "projectile",
        "melee",
        "minion",
        "totem",
        "trap",
        "mine",
        "brand",
        "slam",
        "channelling",
        "area",
    )
    delivery: list[str] = []
    if skill:
        tags = (corpus.get_gem(skill) or {}).get("tags") or []
        delivery = [t for t in delivery_tags if t in tags]
    ehp = (eng.get_defenses() or {}).get("totalEHP")
    return refbuilds.benchmark(
        total_dps=s.get("TotalDPS"), full_dps=s.get("FullDPS"), ehp=ehp, delivery=delivery
    )


@mcp.tool()
def parse_item(text: str) -> dict[str, Any]:
    """Parse a Path of Exile 2 item (in-game clipboard or PoB item text) and enrich it.

    For each explicit affix, identifies its mod group and the **tier it rolled (T1 = best)**
    using the corpus' per-tier ranges, and reports **open prefix/suffix slots** for craftable
    rarities. Use it to evaluate a drop or plan a craft ("is this worth using / can I add
    more?"). Tiers and ranges are looked-up corpus facts — to see how the item changes a build,
    equip it with `equip_item`. Affix detection is best-effort; unmatched lines come back under
    `unrecognized`.
    """
    return itemparse.parse_item(text)


@mcp.tool()
def list_ascendancies(character: str | None = None) -> list[dict[str, Any]]:
    """List Path of Exile 2 ascendancies, optionally filtered by base class."""
    return corpus.list_ascendancies(character=character)


@mcp.tool()
def search_mods(
    query: str = "",
    item_tag: str | None = None,
    mod_type: str | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Search Path of Exile 2 affixes/modifiers by readable text.

    `item_tag` filters by what the mod can roll on (e.g. "ring", "amulet", "body_armour");
    `mod_type` is "prefix" or "suffix". Returns mod text, type, required level, and rolls-on tags.
    """
    return corpus.search_mods(query=query, item_tag=item_tag, mod_type=mod_type, limit=limit)


@mcp.tool()
def reverse_lookup(stat: str, limit: int = 30) -> dict[str, Any]:
    """Find where a stat comes from: matching affixes, gems, and unique items.

    Example: reverse_lookup("maximum life") or reverse_lookup("increased fire damage").
    """
    return corpus.reverse_lookup(stat, limit=limit)


@mcp.tool()
def search_uniques(
    query: str = "", item_type: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    """Search Path of Exile 2 unique items by name, base, or mod text.

    `item_type` filters by slot family (e.g. "ring", "body", "bow"). Use `get_unique` for full text.
    """
    return corpus.search_uniques(query=query, item_type=item_type, limit=limit)


@mcp.tool()
def get_unique(name: str) -> dict[str, Any]:
    """Return a unique item's full readable text (base, mods) by name.

    If the name is a base type rather than a unique (e.g. "Warmonger Bow"), says so and points to
    get_item, instead of returning a confusing null.
    """
    u = corpus.get_unique(name)
    if u:
        return u
    # disambiguate: a base type isn't a unique — guide the caller rather than returning null
    if corpus.get_item(name):
        return {
            "found": False,
            "name": name,
            "note": f"'{name}' is a base item type, not a unique. Use get_item('{name}') for the "
            "base, or search_uniques to find uniques on that base.",
        }
    return {"found": False, "name": name, "note": f"No unique named '{name}'. Try search_uniques."}


@mcp.tool()
def relevant_uniques(limit: int = 15) -> dict[str, Any]:
    """Surface unique items + unique JEWELS that synergize with the ACTIVE build (corpus suggestions).

    Matches the active main skill's scaling — its damage type, skill type (spell/attack/projectile/…)
    and the skill name — against unique mod text, ranked by how many match. Uniques often DEFINE or
    ENABLE a build (extra projectiles, "+levels to skills", a converted mechanic), and unique JEWELS
    supply the passive/notable density meta trees lean on — exactly the power a from-scratch,
    rare-only build misses. These are CANDIDATES, not verified: a unique often enables a mechanic,
    so read full text with `get_unique`, then `equip_item` / `equip_jewel` and measure the real
    delta — every number still comes from the engine. Radius/Time-Lost jewels are positional: rank
    sockets with `evaluate_jewel_socket` before committing.
    """
    b = get_engine().get_build()
    skill = str(b.get("mainSkill") or "")
    gem = corpus.get_gem(skill) if skill else None
    tags = set(gem["tags"]) if gem and isinstance(gem.get("tags"), list) else set()
    damage = {"fire", "cold", "lightning", "chaos", "physical"}
    types = {"spell", "attack", "projectile", "minion", "melee", "area"}
    keywords = sorted((tags & damage) | (tags & types))
    if skill:
        keywords.append(skill)
    unique_jewels = [
        u
        for u in corpus.relevant_uniques(keywords, limit=40)
        if u["item_type"] == "jewel" and u["base"] != "Timeless Jewel"
    ][:10]
    return {
        "skill": skill,
        "keywords": keywords,
        "uniques": corpus.relevant_uniques(keywords, limit=limit) if keywords else [],
        "uniqueJewels": unique_jewels,
        "note": (
            "Corpus suggestions matched to your build's scaling — NOT engine-verified. A unique "
            "often ENABLES a mechanic, so read its full text (get_unique) before judging; then "
            "equip_item / equip_jewel and measure the real delta. Unique jewels are common "
            "build-definers a rare-only build misses — and radius/Time-Lost jewels are "
            "positional: rank sockets with evaluate_jewel_socket before committing. Data "
            "caveat: the bundled corpus unique-jewel table is missing the PoE2 Time-Lost series "
            "(the physical graph ingests the 8 uniques generated in Uniques/Special/"
            "Generated.lua, but the corpus text table still lacks them), and Historic timeless "
            "jewels (base 'Timeless Jewel', e.g. Heroic Tragedy/Undying Hate) are excluded "
            "from candidates because the pinned engine's conquered rule is a no-op. Verify any "
            "jewel text against the engine. Every number must come from the engine."
        ),
    }


@mcp.tool()
def corpus_info() -> dict[str, Any]:
    """Report the bundled game-data corpus version and entity counts."""
    return corpus.corpus_info()


@mcp.tool()
def graph_tool_query(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Run a Phase 3 read-only typed graph query against the latest registered snapshot.

    `tool_name` must be one of the Phase 3 typed graph query families, and `payload` must match
    that family's schema. Raw Cypher, Gremlin, SQL, or other backend query strings are rejected by
    the shared GraphQueryService and returned as structured public errors.
    """
    try:
        return _graph_query_service().run_tool(tool_name, payload)
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError) as exc:
        endpoint_assessment = {
            "classification": "graph_snapshot_unavailable",
            "hallucinationVerdict": "not_assessed",
            "candidateEndpointKeys": [],
            "missingEndpointKeys": [],
            "reason": (
                "No graph snapshot was available, so endpoint reality could not be assessed. "
                "Do not classify mature-build entities as hallucinations from this result alone."
            ),
            "requiresStaticSourceReview": True,
        }
        return {
            "toolName": tool_name,
            "queryFamily": tool_name,
            "snapshotId": None,
            "status": "error",
            "errorCode": "graph_snapshot_unavailable",
            "endpointAssessment": endpoint_assessment,
            "resolvedSubject": None,
            "facts": {"recoverable": True, "endpointAssessment": endpoint_assessment},
            "evidencePath": None,
            "sourceRefs": [],
            "confidence": 0.0,
            "caveats": [f"{type(exc).__name__}: graph snapshot unavailable"],
            "contextPolicy": "none",
            "contextUsed": {},
            "missingContext": [],
            "contextCaveats": [],
            "freshness": {"versionContext": {}},
            "noRawQuery": True,
        }
    except Exception as exc:
        return {
            "toolName": tool_name,
            "queryFamily": tool_name,
            "snapshotId": None,
            "status": "error",
            "errorCode": "graph_tool_runtime_error",
            "resolvedSubject": None,
            "facts": {"recoverable": True},
            "evidencePath": None,
            "sourceRefs": [],
            "confidence": 0.0,
            "caveats": [f"{type(exc).__name__}: graph tool failed"],
            "contextPolicy": "none",
            "contextUsed": {},
            "missingContext": [],
            "contextCaveats": [],
            "freshness": {"versionContext": {}},
            "noRawQuery": True,
        }


@mcp.tool()
def build_research_packet(
    case: dict[str, Any],
    persist_for_transport: bool = False,
    ttl_seconds: int = 3600,
) -> dict[str, Any]:
    """Build a transient Phase 4 external-Researcher packet."""
    return research_packet.build_research_packet(
        case,
        persist_for_transport=persist_for_transport,
        ttl_seconds=ttl_seconds,
    )


@mcp.tool()
def validate_researcher_output(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a strict Phase 4 Researcher output proposal without writing memory."""
    return research_models.validate_researcher_output(payload)


@mcp.tool()
def query_research_memory(
    query: str,
    component_keys: list[str] | None = None,
    limit: int = 10,
    detail_level: str = "summary",
    record_ids: list[str] | None = None,
    include_transferable: bool = False,
    research_axes: list[str] | None = None,
    ascendancy_key: str | None = None,
    primary_skill_key: str | None = None,
    build_family_keys: list[str] | None = None,
    record_kinds: list[str] | None = None,
    class_key: str | None = None,
    game_patch: str | None = None,
    passive_tree_version: str | None = None,
    response_profile: Literal["full", "create_compact"] = "full",
) -> dict[str, Any]:
    """Query safe Family memory with optional exact identity and record-kind filters."""
    result = _research_memory_service_with_graph().query_research_memory(
        query,
        component_keys=component_keys or [],
        limit=limit,
        detail_level=detail_level,
        record_ids=record_ids or [],
        include_transferable=include_transferable,
        research_axes=research_axes or [],
        ascendancy_key=ascendancy_key,
        primary_skill_key=primary_skill_key,
        build_family_keys=build_family_keys or [],
        record_kinds=record_kinds or [],
        class_key=class_key,
        game_patch=game_patch,
        passive_tree_version=passive_tree_version,
    )
    return (
        _compact_create_research_response(result)
        if response_profile == "create_compact"
        else result
    )


def _compact_create_research_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep Create-critical semantics while dropping repeated retrieval plumbing."""

    if payload.get("status") == "error":
        # Pass through the full structured error: errorCode / caveats / suggestedRepair / facts
        # are exactly what the Agent needs to repair the call; compacting them away hides the
        # reason a query failed.
        return payload

    detail_level = payload.get("detailLevel")
    record_keys = (
        "recordId",
        "buildFamilyKey",
        "recordKind",
        "title",
        "summary",
        "componentKeys",
        "gamePatch",
        "passiveTreeVersion",
        "status",
    )
    if detail_level == "record":
        record_keys = (
            *record_keys,
            "conditions",
            "failureConditions",
            "content",
            "typedPayload",
        )
    pattern_keys = (
        "patternId",
        "patternType",
        "title",
        "summary",
        "componentKeys",
        "confidenceTier",
        "sampleCount",
        "familyCount",
        "transferScope",
        "matchScope",
        "plannerHint",
        "gamePatch",
        "passiveTreeVersion",
        "status",
    )
    fragment_keys = (
        "memoryItemId",
        "fragmentId",
        "fragmentType",
        "title",
        "summary",
        "reusablePrinciple",
        "componentKeys",
        "confidence",
        "modelability",
        "gamePatch",
        "passiveTreeVersion",
        "status",
        "contextCaveats",
    )
    edge_keys = (
        "edgeId",
        "sourceKey",
        "targetKey",
        "edgeType",
        "rationale",
        "confidence",
        "modelability",
        "affectedComponentKeys",
        "gamePatch",
        "passiveTreeVersion",
        "status",
    )
    family_keys = (
        "buildFamilyKey",
        "ascendancyKey",
        "primarySkillKey",
        "secondarySkillKeys",
        "evidenceCount",
        "deepRecordCount",
        "recordKindCounts",
        "availableRecordKinds",
        "classKey",
        "gamePatch",
        "passiveTreeVersion",
        "keyPremises",
        "failureConditions",
        "supportingRecordIds",
        "eligibility",
    )
    raw_records = [
        item for item in payload.get("deepResearchRecords", []) if isinstance(item, dict)
    ]
    raw_fragments = [item for item in payload.get("results", []) if isinstance(item, dict)]
    raw_edges = [item for item in payload.get("semanticEdges", []) if isinstance(item, dict)]
    raw_patterns = [item for item in payload.get("buildPatterns", []) if isinstance(item, dict)]
    raw_transferable = [
        item for item in payload.get("transferablePatterns", []) if isinstance(item, dict)
    ]
    records = [_select_mapping_fields(item, record_keys) for item in raw_records]
    fragments = [_select_mapping_fields(item, fragment_keys) for item in raw_fragments]
    semantic_edges = [_select_mapping_fields(item, edge_keys) for item in raw_edges]
    patterns = [_select_mapping_fields(item, pattern_keys) for item in raw_patterns]
    transferable = [_select_mapping_fields(item, pattern_keys) for item in raw_transferable]
    # Compact mode removes repeated per-result fields, not results.  Candidate/evidence count is
    # controlled only by the caller's query; the response profile must not silently narrow it.
    premise_digest: list[dict[str, Any]] = []
    for item in raw_records:
        conditions = list(item.get("conditions") or [])
        failures = list(item.get("failureConditions") or [])
        if conditions or failures:
            premise_digest.append(
                {
                    "evidenceRef": item.get("recordId"),
                    "title": item.get("title"),
                    "criticalConditions": conditions,
                    "failureConditions": failures,
                    "verificationTasks": [],
                }
            )
    for item in raw_fragments:
        conditions = list(item.get("conditions") or [])
        failures = list(item.get("risks") or [])
        tasks = list(item.get("verificationTasks") or [])
        if conditions or failures or tasks:
            premise_digest.append(
                {
                    "evidenceRef": item.get("memoryItemId") or item.get("fragmentId"),
                    "title": item.get("title"),
                    "criticalConditions": conditions,
                    "failureConditions": failures,
                    "verificationTasks": tasks,
                }
            )
    for item in raw_edges:
        requirements = list(item.get("contextRequirements") or [])
        if requirements:
            premise_digest.append(
                {
                    "evidenceRef": item.get("edgeId"),
                    "title": item.get("edgeType"),
                    "criticalConditions": requirements,
                    "failureConditions": [],
                    "verificationTasks": [],
                }
            )
    for item in [*raw_patterns, *raw_transferable]:
        requirements = list(item.get("applicabilityRequirements") or [])
        exclusions = list(item.get("exclusionConditions") or [])
        tasks = list(item.get("verificationTasks") or [])
        if requirements or exclusions or tasks:
            premise_digest.append(
                {
                    "evidenceRef": item.get("patternId"),
                    "title": item.get("title"),
                    "criticalConditions": requirements,
                    "failureConditions": exclusions,
                    "verificationTasks": tasks,
                }
            )
    requested_build_family_keys = {
        str(key) for key in (payload.get("requestedBuildFamilyKeys") or []) if str(key).strip()
    }

    def family_scoped(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Premise catalog / record index / coverage are retrieval plumbing for a targeted query:
        # when the caller narrowed to explicit Families, only those catalogs belong in the compact
        # response (the full result set is never truncated — these are auxiliary metadata only).
        if not requested_build_family_keys:
            return items
        return [
            item
            for item in items
            if str(item.get("buildFamilyKey") or "") in requested_build_family_keys
        ]

    compact = {
        "status": payload.get("status"),
        "dedupeQueryRef": payload.get("dedupeQueryRef"),
        "results": fragments,
        "deepResearchRecords": records,
        "buildFamilies": [
            _select_mapping_fields(item, family_keys)
            for item in payload.get("buildFamilies", [])
            if isinstance(item, dict)
        ],
        "semanticEdges": semantic_edges,
        "buildPatterns": patterns,
        "transferablePatterns": transferable,
        "familyRecordCoverage": family_scoped(payload.get("familyRecordCoverage") or []),
        "familyRecordIndex": family_scoped(payload.get("familyRecordIndex") or []),
        "familyPremiseCatalog": family_scoped(payload.get("familyPremiseCatalog") or []),
        "premiseAuditVersion": payload.get("premiseAuditVersion"),
        "criticalPremiseDigest": premise_digest,
        "requestedComponentKeys": payload.get("requestedComponentKeys") or [],
        "requestedResearchAxes": payload.get("requestedResearchAxes") or [],
        "requestedAscendancyKey": payload.get("requestedAscendancyKey"),
        "requestedPrimarySkillKey": payload.get("requestedPrimarySkillKey"),
        "requestedBuildFamilyKeys": payload.get("requestedBuildFamilyKeys") or [],
        "requestedRecordKinds": payload.get("requestedRecordKinds") or [],
        "requestedClassKey": payload.get("requestedClassKey"),
        "requestedGamePatch": payload.get("requestedGamePatch"),
        "requestedPassiveTreeVersion": payload.get("requestedPassiveTreeVersion"),
        "familyDiscovery": payload.get("familyDiscovery"),
        "includeTransferable": bool(payload.get("includeTransferable")),
        "componentKeyGroups": payload.get("componentKeyGroups") or [],
        "detailLevel": payload.get("detailLevel"),
        "noRawQuery": True,
        "noRawMatureBuildMaterial": True,
        "responseProfile": "create_compact",
        "responseProfileTruncatesResults": False,
    }
    return compact


def _select_mapping_fields(
    value: dict[str, Any],
    keys: tuple[str, ...],
) -> dict[str, Any]:
    return {key: value[key] for key in keys if key in value}


@mcp.tool()
def propose_deep_research_records(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate focused deep-research records for later acceptance; does not persist them."""
    return _research_memory_service_with_graph().validate_deep_research_records(payload)


@mcp.tool()
def propose_research_fragments(
    payload: dict[str, Any],
    dedupe_query_ref: str | None = None,
) -> dict[str, Any]:
    """Validate clean fragment proposals after query-before-propose dedupe; does not persist."""
    return _research_memory_service().validate_research_fragments(
        payload,
        dedupe_query_ref=dedupe_query_ref,
    )


@mcp.tool()
def append_evidence_to_fragment(
    fragment_id: str,
    source_case_refs: list[str],
    safe_evidence_refs: list[str],
    game_patch: str,
    passive_tree_version: str,
    pob_version_or_commit: str,
    visibility: str,
    split: str,
    knowledge_scope: str,
    confidence: str,
) -> dict[str, Any]:
    """Append safe evidence refs to an existing clean fragment without duplicating knowledge."""
    return _research_memory_service().append_evidence_to_fragment(
        fragment_id=fragment_id,
        source_case_refs=source_case_refs,
        safe_evidence_refs=safe_evidence_refs,
        game_patch=game_patch,
        passive_tree_version=passive_tree_version,
        pob_version_or_commit=pob_version_or_commit,
        visibility=visibility,
        split=split,
        knowledge_scope=knowledge_scope,
        confidence=confidence,
    )


@mcp.tool()
def propose_semantic_edges(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate semantic edge proposals; acceptance is the only durable writer."""
    return _research_memory_service_with_graph().validate_semantic_edges(payload)


@mcp.tool()
def propose_build_patterns(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate build observations and patterns for a later safe-review acceptance."""
    return _research_memory_service_with_graph().validate_build_patterns(payload)


@mcp.tool()
def submit_revalidation_result(
    target_kind: str,
    target_id: str,
    outcome: str,
    new_version_context: dict[str, str],
    safe_evidence_refs: list[str],
    affected_component_keys: list[str],
) -> dict[str, Any]:
    """Submit a Phase 4 patch revalidation result for a fragment, semantic edge, or build pattern."""
    return _research_memory_service().submit_revalidation_result(
        target_kind=target_kind,
        target_id=target_id,
        outcome=outcome,
        new_version_context=new_version_context,
        safe_evidence_refs=safe_evidence_refs,
        affected_component_keys=affected_component_keys,
    )


@mcp.tool()
def inspect_rejected_research_proposals(limit: int = 20) -> dict[str, Any]:
    """Return safe summaries of rejected Phase 4 research proposals."""
    con = research_memory.mature_learning.connect()
    try:
        rows = con.execute(
            """
            SELECT rejection_id, error_code, visibility, split, knowledge_scope, retry_count,
                   caveats, suggested_repair, first_seen_at, last_seen_at
            FROM research_rejected_proposals
            ORDER BY last_seen_at DESC, rejection_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        rejected = [
            {
                "rejectionId": row["rejection_id"],
                "errorCode": row["error_code"],
                "visibility": row["visibility"],
                "split": row["split"],
                "knowledgeScope": row["knowledge_scope"],
                "retryCount": row["retry_count"],
                "caveats": json.loads(row["caveats"]),
                "suggestedRepair": row["suggested_repair"],
                "firstSeenAt": row["first_seen_at"],
                "lastSeenAt": row["last_seen_at"],
            }
            for row in rows
        ]
    finally:
        con.close()
    return {
        "status": "known",
        "rejected": rejected,
        "noRawQuery": True,
        "noRawMatureBuildMaterial": True,
    }


# --------------------------------------------------------------------------------------
# Live ops (network: prices, data freshness, corpus updates)
# --------------------------------------------------------------------------------------
@mcp.tool()
def get_prices(
    query: str = "",
    kind: str = "currency",
    category: str | None = None,
    league: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Look up live Path of Exile 2 market prices (poe2scout.com).

    `kind` is "currency" or "unique". `query` filters by name (e.g. "divine", "mageblood").
    Defaults to the current challenge league; prices are in the league's base currency.
    """
    return live_prices.get_prices(
        query=query, kind=kind, category=category, league=league, limit=limit
    )


@mcp.tool()
def list_price_leagues() -> list[dict[str, Any]]:
    """List Path of Exile 2 leagues available for pricing (with the current one flagged)."""
    return live_prices.list_leagues()


@mcp.tool()
def get_meta_builds(league: str | None = None, limit: int = 15) -> dict[str, Any]:
    """Live ascendancy popularity from poe.ninja's ladder snapshot — CONTEXT, not a target.

    Returns the most-played ascendancies for a league (default the current challenge league)
    with each one's share % and a rising/falling/flat trend, plus the sample size. This is
    *popularity among logged ladder characters, not a recommendation* — popular is not the same
    as optimal or right for the player's goal. Use it to inform, not dictate: build to the
    user's stated goal, and only steer toward the meta when they explicitly ask for the
    "strongest"/"popular"/"meta" option. Covers ascendancy distribution only (no skill/item
    meta). Returns {ok: false} if poe.ninja is unreachable.
    """
    try:
        return live_meta.get_meta_builds(league=league, limit=limit)
    except live_meta.MetaError as e:
        return {"ok": False, "error": f"meta data unavailable: {e}"}


@mcp.tool()
def get_meta_archetype_trends(league: str | None = None, limit: int = 10) -> dict[str, Any]:
    """Live aggregate build-archetype trend adapter from poe.ninja when available.

    This is intentionally conservative: if the live payload lacks build-level skill/archetype
    samples, it returns `ok:false` with `unavailableReason` instead of inferring trends from
    ascendancy popularity. Use available rows as discovery context only, then verify with PoB.
    """
    try:
        return live_meta.get_archetype_trends(league=league, limit=limit)
    except live_meta.MetaError as e:
        return {
            "ok": False,
            "source": "poe.ninja",
            "kind": "archetype_trends",
            "league": league,
            "archetypes": [],
            "error": f"archetype trend data unavailable: {e}",
            "unavailableReason": f"archetype trend data unavailable: {e}",
            "evidenceTags": ["live-meta", "unavailable"],
        }


@mcp.tool()
def lookup_mechanic(topic: str) -> dict[str, Any]:
    """Fetch a concise mechanic/skill/item explanation LIVE from the PoE2 Wiki (live — network).

    The long-tail escape hatch: use this only when `explain_mechanic`/`search_mechanics` don't
    have the topic in the bundled corpus. Returns a short lead extract + source link, attributed
    (PoE2 Wiki, CC BY-NC-SA 3.0 — cite it). Time-sensitive and may be outdated; the engine
    remains the source of truth for any number. Returns {available: false} if the wiki is
    unreachable. Single, user-triggered, read-only — it never sends your build anywhere.
    """
    return live_wiki.lookup_mechanic(topic)


@mcp.tool()
def get_freshness_report(force_refresh: bool = False) -> dict[str, Any]:
    """Return the strict cross-source freshness gate used before claiming a current-season build.

    This is a live cross-source gate over the local validated release, official GGG patch/tree
    data, poe.ninja snapshots, and PoB compatibility evidence. Missing or conflicting sources
    block current-season verification. Pass force_refresh=True to ask live providers to refresh
    their caches now, subject to provider safety throttles.
    """
    return freshness_service.get_freshness_report(force_refresh=force_refresh)


@mcp.tool()
def check_data_version() -> dict[str, Any]:
    """Compatibility wrapper around the strict freshness report plus the legacy corpus probe.

    The RePoE timestamp only describes one legacy corpus input. The top-level recommendation is
    the strict live freshness decision, while the old probe is nested for compatibility.
    """
    freshness = freshness_service.get_freshness_report()
    return {
        "recommendation": freshness["decision"],
        "freshness": freshness,
        "legacy_corpus_probe": live_version.check_data_version(),
    }


@mcp.tool()
def update_corpus(rebuild_from_source: bool = False) -> dict[str, Any]:
    """Rebuild the game-data corpus locally from RePoE (power-user / offline path).

    Most users don't need this — the server auto-updates from validated releases. Pass
    rebuild_from_source=true to re-fetch RePoE and rebuild the corpus right now.
    """
    return live_version.update_corpus(rebuild_from_source=rebuild_from_source)


@mcp.tool()
def check_for_updates() -> dict[str, Any]:
    """Check whether a newer validated release (engine + corpus) is available to install."""
    return live_update.check_for_updates()


@mcp.tool()
def apply_updates() -> dict[str, Any]:
    """Download and install the latest validated release (engine + corpus) now."""
    return live_update.apply_updates(
        install_context=_runtime_install_context,
        validate_engine=_validate_staged_engine,
    )


# ---------------------------------------------------------------------------
# Prompts — ready-made workflow entry points the client can surface to users.
# Each returns guidance that steers the assistant through the right tool sequence;
# the actual numbers always come from the compute engine, never from the prompt.
# ---------------------------------------------------------------------------


@mcp.prompt()
def start_build_session(opening: str = "") -> str:
    """Start a Path of Exile 2 build session — orients the assistant to drive the poe2-build tools."""
    tail = f"\n\nThe player's opening request:\n{opening}" if opening.strip() else ""
    return (
        "You're now in a Path of Exile 2 build session. Use the poe2-build tools as the source of "
        "truth for this whole conversation: every DPS / EHP / resistance / defense figure must come "
        "from the compute engine (e.g. get_build_stats, get_defenses, compare_to, solve_for) — don't "
        "answer build math from memory, and lean on build_advice / explain_mechanic for principles "
        "and mechanics.\n\n"
        "What you can do here:\n"
        "- Analyze a build: import_build (a PoB code, pobb.in/pastebin link, or XML), then get_build "
        "/ get_defenses / get_build_stats, and suggest engine-validated improvements.\n"
        "- Build from scratch: set_class → set_level → set_skill → optimize_supports (best support "
        "set) → allocate the ascendancy + optimize_passives → gear with plan_gear / optimize_item "
        "(goals) / optimize_jewel → apply_combat_profile + gate, validating each step on the engine.\n"
        "- Solve toward a goal: solve_for, evaluate_build, optimize_passives.\n"
        "- Look things up: items, gems, mods, uniques, passives, ascendancies; check live prices.\n\n"
        "If the player hasn't said what they want, ask whether they'd like to analyze an existing "
        "build, create one from a goal, or get advice — then go."
        f"{tail}"
    )


@mcp.prompt()
def analyze_build(source: str) -> str:
    """Import a PoB build and produce a grounded analysis with improvement ideas."""
    return (
        f"Import this Path of Exile 2 build and analyze it:\n\n{source}\n\n"
        "Steps: call import_build, then get_build, get_defenses, and get_build_stats to see "
        "where it stands. Identify the biggest weaknesses (offense, survivability, resist caps). "
        "Find concrete improvements (rank_upgrades for the highest-gain gear slot, optimize_supports "
        "for the support set, optimize_item/optimize_jewel for crafts, search_*/explain_mechanic for "
        "options), then VALIDATE each suggestion on the engine (mutate and re-read stats, or "
        "compare_to) before recommending it. Distinguish PoB-computed numbers from corpus facts, and "
        "never state a number the engine didn't produce."
    )


@mcp.prompt()
def build_from_goal(goal: str, character_class: str = "") -> str:
    """Create a verified build from a natural-language goal (create → validate → cost → present)."""
    cls = f" Start from the {character_class} class." if character_class else ""
    return (
        f"Create a Path of Exile 2 build for this goal:\n\n{goal}\n{cls}\n\n"
        "Follow create → validate → cost → present: set_class → set_level → set_skill → for an "
        "attack skill equip a weapon FIRST (equip_item) so DPS computes → optimize_supports for the "
        "best support set → allocate the ascendancy (often the build's biggest multiplier) + "
        "optimize_passives (metric='balanced' to raise offense AND defense) → gear it: plan_gear for "
        "a whole-set first pass (auto-bases empty slots; pass min_ehp for a survivability floor), or "
        "optimize_item per slot with goals={'TotalDPS':..,'TotalEHP':..} for blends, optimize_jewel "
        "for jewels, rank_upgrades for the next slot → check relevant_uniques for build-defining "
        "uniques + unique jewels (the leap past the ~100k rare-only ceiling; verify each on the "
        "engine) → apply_combat_profile for the realistic fight.\n\n"
        "Commit to a dominant multiplier and an archetype the ENGINE CAN MODEL, early: pinnacle DPS "
        "comes from a committed multiplier (crit, ailment/DoT, minions, '+levels', a 'more'/penetration "
        "stack), not slot-by-slot tuning — a half-built lane reads weak per slot, so judge it once "
        "stacked across tree + several gear pieces. IMPORTANT: the engine does NOT model energy-based "
        "meta TRIGGERS (Cast on Critical, the Invocations) — a socketed spell computes as a weak "
        "SELF-CAST (tools flag `engineLimitation`), so don't build toward or cost a trigger-meta "
        "archetype; pick a directly cast/attacked skill and tell the player about the gap.\n\n"
        "A build is NOT done until it clears a real bar (see build_advice('targets')): resists "
        "capped, a full gear set, a meaningful hit pool, DPS that clears the player's content, and "
        "sustain. CONFIRM with get_defenses + evaluate_build against explicit goals; sanity-check "
        "with build_advice('red flags') and, if you have one, compare_to a known-good build. Check "
        "cost with get_prices and present with export_build. If the build is a partial skeleton or "
        "fails the goal, say so plainly — never present a draft or a failing build as finished."
    )


@mcp.prompt()
def audit_defenses() -> str:
    """Audit the active build's survivability and propose fixes."""
    return (
        "Audit the active build's defenses. Call get_defenses and report life/ES, EHP, and "
        "elemental + chaos resistances with over-cap. Remember PoB's default endgame resistance "
        "penalty makes fresh resists deeply negative — that's expected; the target is the 75% "
        "cap. Identify the weakest defensive layer and propose specific, engine-validated fixes — "
        "recraft slots with optimize_item goals (or plan_gear to re-cap the whole set while keeping "
        "damage), gear mods via search_mods, uniques, or passives — confirming each with the engine."
    )


@mcp.prompt()
def research_mature_build_case(
    packet_json: str = "",
    current_patch: str = "",
    passive_tree_version: str = "",
    user_language: str = "zh-CN",
) -> str:
    """Drive an external Phase 4 Researcher Agent through tool-based mature-build extraction."""
    if packet_json.strip():
        try:
            packet = json.loads(packet_json)
        except json.JSONDecodeError as exc:
            return (
                "The supplied packet_json is not valid JSON. Call build_research_packet first, then "
                f"pass its packet object as JSON here. JSON error: {exc.msg}"
            )
    else:
        return (
            "Call build_research_packet first with the quarantine-only mature case, then rerun "
            "research_mature_build_case with the returned packet object serialized as packet_json. "
            "Do not start Researcher extraction without a real transient packet."
        )
    if not isinstance(packet, dict):
        return "packet_json must decode to a JSON object. Call build_research_packet and pass its packet object."
    return research_prompt.render_researcher_prompt(
        packet,
        current_patch=current_patch or None,
        passive_tree_version=passive_tree_version or None,
        user_language=user_language,
    )


def main() -> None:
    research_packet.cleanup_expired_packets()

    # Best-effort, throttled auto-update in the background; never blocks startup.
    def _auto_update() -> None:
        live_update.auto_update(
            install_context=_runtime_install_context,
            validate_engine=_validate_staged_engine,
        )

    threading.Thread(target=_auto_update, daemon=True).start()
    mcp.run()


if __name__ == "__main__":
    main()
