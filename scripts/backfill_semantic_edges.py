"""Deterministic T1 semantic-edge backfill from existing Research Memory.

Derives advisory semantic edges from four proven source shapes that already carry
resolver-backed component keys and roles:

- transition_gate build patterns  -> requires_transition_gate
- mechanic_chain deep records     -> enables_mechanic (generator->payoff,
                                      unique_enabler->primary_damage/payoff)
- failure_mode deep records       -> creates_failure_risk_for
- modelability_caveat records     -> has_modelability_caveat

Writes only through ResearchMemoryService.propose_semantic_edges (the persisting,
resolver/copy-safety/conflict-gated path); never through raw SQL. Modes:
--dry-run (candidates + stats), --validate (validation-only pass),
--apply (persist, chunked). Idempotent: edge ids are deterministic and the
write path is ON CONFLICT(edge_id) DO UPDATE.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server import paths  # noqa: E402
from server.knowledge import graph_seed, graph_tools, mature_learning  # noqa: E402
from server.knowledge import physical_graph as pg  # noqa: E402
from server.knowledge import research_memory  # noqa: E402
from server.knowledge import research_models  # noqa: E402

SOURCE_TRANSITION_GATE = "transition_gate"
SOURCE_MECHANIC_CHAIN = "mechanic_chain"
SOURCE_FAILURE_MODE = "failure_mode"
SOURCE_MODELABILITY_CAVEAT = "modelability_caveat"
SOURCE_TYPES = (
    SOURCE_TRANSITION_GATE,
    SOURCE_MECHANIC_CHAIN,
    SOURCE_FAILURE_MODE,
    SOURCE_MODELABILITY_CAVEAT,
)

# target precedence for transition_gate patterns: the component the build must
# acquire/switch to before the gated setup works.
GATE_TARGET_ROLE_PRECEDENCE = (
    "transition_gate",
    "keystone_transformer",
    "unique_enabler",
    "weapon_base",
)
GATE_SOURCE_ROLE_PRECEDENCE = (
    "primary_damage",
    "payoff",
    "generator",
    "defensive_buff",
    "passive_anchor",
    "weapon_base",
    "gear_base",
)
FAILURE_SOURCE_ROLES = {"unique_enabler", "reservation", "generator", "trigger_host"}
FAILURE_TARGET_ROLES = {"primary_damage", "payoff", "defensive_buff", "defense_layer"}
CAVEAT_SOURCE_ROLES = {"primary_damage", "payoff"}
CAVEAT_TARGET_ROLES = {
    "support_modifier",
    "trigger_host",
    "secondary_skill",
    "reservation",
    "generator",
}
MECHANIC_PAIRS = (
    ("generator", "payoff"),
    ("unique_enabler", "primary_damage"),
    ("unique_enabler", "payoff"),
)
CHUNK_SIZE = 25
# The service's cycle guard seeds its walk from the candidate target at depth=1
# (already one directed edge) and expands while depth < 3, so it detects a path
# of up to three directed edges from the candidate target back to its source.
CYCLE_HOP_LIMIT = 3


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _role_map(component_mentions: str | None) -> dict[str, str]:
    roles: dict[str, str] = {}
    for mention in _loads(component_mentions, []) or []:
        if isinstance(mention, dict) and mention.get("component_key") and mention.get("role"):
            roles[str(mention["component_key"])] = str(mention["role"])
    return roles


def _first_priority(
    keys: list[str], roles: dict[str, str], precedence: tuple[str, ...]
) -> str | None:
    for role in precedence:
        for key in keys:
            if roles.get(key) == role:
                return key
    return None


def _fixed_context() -> list[dict[str, Any]]:
    return [
        {
            "context_type": "lifecycle_stage_requirement",
            "stages": ["endgame_mature"],
        },
        {
            "context_type": "verification_gate_requirement",
            "task": "该边为存量数据确定性回填推导，使用前以 PoB 读回与 Judge 复核。",
        },
    ]


class _Deriver:
    def __init__(
        self,
        con: sqlite3.Connection,
        nodes_by_key: dict[str, pg.GraphNode],
        snapshot_id: str,
        *,
        source_types: set[str] | None = None,
        limit_per_source: int | None = None,
    ):
        self._con = con
        self._nodes = nodes_by_key
        self._snapshot_id = snapshot_id
        self._source_types = source_types or set(SOURCE_TYPES)
        self._limit = limit_per_source
        self.candidates: list[dict[str, Any]] = []
        self.stats: dict[str, dict[str, int]] = {}

    # -- shared helpers ----------------------------------------------------

    def _evidence(self, key: str) -> dict[str, Any]:
        node = self._nodes[key]
        return {
            "tool_name": "resolve_graph_component",
            "status": "resolved",
            "stable_key": node.stable_key,
            "snapshot_id": self._snapshot_id,
            "evidence_path_nodes": [node.stable_key],
            "source_refs": list(node.source_refs),
        }

    def _envelope(self) -> dict[str, Any]:
        return {"schema_version": 4, "fragments": [], "semantic_edges": self.candidates}

    def _push(
        self,
        *,
        source_type: str,
        source_ref: str,
        title: str,
        source_key: str,
        target_key: str,
        edge_type: str,
        rationale_suffix: str,
        source_case_refs: list[str],
        safe_evidence_refs: list[str],
        game_patch: str,
        passive_tree_version: str,
        pob_version_or_commit: str,
        confidence: str,
        context_requirements: list[dict[str, Any]],
    ) -> None:
        if source_key == target_key:
            return
        self.candidates.append(
            {
                "source_key": source_key,
                "target_key": target_key,
                "source_resolution": self._evidence(source_key),
                "target_resolution": self._evidence(target_key),
                "edge_type": edge_type,
                "rationale": (
                    f"存量回填推导：{source_type} {source_ref}（{title}）"
                    f"的{rationale_suffix}关系。advisory，需 PoB/Judge 复核。"
                ),
                "source_case_refs": sorted(set(source_case_refs)),
                "safe_evidence_refs": sorted(set(safe_evidence_refs) | {f"backfill:{source_ref}"}),
                "game_patch": game_patch,
                "passive_tree_version": passive_tree_version,
                "pob_version_or_commit": pob_version_or_commit,
                "status": "valid",
                "confidence": confidence,
                "modelability": "partial",
                "copy_safety_state": "passed",
                "context_requirements": context_requirements,
                "affected_component_keys": sorted({source_key, target_key}),
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
                "directionality": "directional",
            }
        )

    def _bump(self, source_type: str, key: str) -> None:
        bucket = self.stats.setdefault(source_type, {})
        bucket[key] = bucket.get(key, 0) + 1

    # -- per-source derivations --------------------------------------------

    def derive_transition_gates(self) -> None:
        rows = self._con.execute(
            """
            SELECT pattern_id, title, component_keys, component_roles,
                   context_requirements, source_case_refs, safe_evidence_refs,
                   game_patch, passive_tree_version, pob_version_or_commit,
                   confidence_tier
            FROM research_build_patterns
            WHERE pattern_type = 'transition_gate' AND status = 'valid'
            ORDER BY pattern_id
            """
        ).fetchall()
        for row in rows:
            if (
                self._limit is not None
                and self.stats.get(SOURCE_TRANSITION_GATE, {}).get("candidates", 0) >= self._limit
            ):
                break
            keys = _loads(row["component_keys"], []) or []
            roles = _loads(row["component_roles"], {}) or {}
            if len(keys) < 2:
                self._bump(SOURCE_TRANSITION_GATE, "skipped_insufficient_keys")
                continue
            target = _first_priority(keys, roles, GATE_TARGET_ROLE_PRECEDENCE)
            source = _first_priority(keys, roles, GATE_SOURCE_ROLE_PRECEDENCE)
            if target is None or source is None or source == target:
                self._bump(SOURCE_TRANSITION_GATE, "skipped_no_gate_pair")
                continue
            if target not in self._nodes or source not in self._nodes:
                self._bump(SOURCE_TRANSITION_GATE, "skipped_endpoint_missing")
                continue
            self._push(
                source_type=SOURCE_TRANSITION_GATE,
                source_ref=str(row["pattern_id"]),
                title=str(row["title"] or ""),
                source_key=source,
                target_key=target,
                edge_type="requires_transition_gate",
                rationale_suffix=f"启用门槛（{roles[source]}→{roles[target]}）",
                source_case_refs=_loads(row["source_case_refs"], []) or [],
                safe_evidence_refs=_loads(row["safe_evidence_refs"], []) or [],
                game_patch=str(row["game_patch"] or ""),
                passive_tree_version=str(row["passive_tree_version"] or ""),
                pob_version_or_commit=str(row["pob_version_or_commit"] or ""),
                confidence="medium" if row["confidence_tier"] == "recurring_observation" else "low",
                context_requirements=_loads(row["context_requirements"], []) or _fixed_context(),
            )
            self._bump(SOURCE_TRANSITION_GATE, "candidates")

    def derive_mechanic_chains(self) -> None:
        rows = self._con.execute(
            """
            SELECT record_id, title, component_keys, component_mentions,
                   source_case_refs, safe_evidence_refs,
                   game_patch, passive_tree_version, pob_version_or_commit
            FROM deep_research_records
            WHERE record_kind = 'mechanic_chain' AND status = 'valid'
            ORDER BY record_id
            """
        ).fetchall()
        for row in rows:
            bucket = self.stats.get(SOURCE_MECHANIC_CHAIN, {})
            if self._limit is not None and bucket.get("candidates", 0) >= self._limit:
                break
            keys = _loads(row["component_keys"], []) or []
            roles = _role_map(row["component_mentions"])
            if len(keys) < 2:
                self._bump(SOURCE_MECHANIC_CHAIN, "skipped_insufficient_keys")
                continue
            emitted = 0
            for source_role, target_role in MECHANIC_PAIRS:
                if emitted >= 2:
                    break
                source = _first_priority(keys, roles, (source_role,))
                target = _first_priority(keys, roles, (target_role,))
                if source is None or target is None or source == target:
                    continue
                if source not in self._nodes or target not in self._nodes:
                    self._bump(SOURCE_MECHANIC_CHAIN, "skipped_endpoint_missing")
                    continue
                self._push(
                    source_type=SOURCE_MECHANIC_CHAIN,
                    source_ref=str(row["record_id"]),
                    title=str(row["title"] or ""),
                    source_key=source,
                    target_key=target,
                    edge_type="enables_mechanic",
                    rationale_suffix=f"因果链（{source_role}→{target_role}）",
                    source_case_refs=_loads(row["source_case_refs"], []) or [],
                    safe_evidence_refs=_loads(row["safe_evidence_refs"], []) or [],
                    game_patch=str(row["game_patch"] or ""),
                    passive_tree_version=str(row["passive_tree_version"] or ""),
                    pob_version_or_commit=str(row["pob_version_or_commit"] or ""),
                    confidence="low",
                    context_requirements=_fixed_context(),
                )
                emitted += 1
                self._bump(SOURCE_MECHANIC_CHAIN, "candidates")

    def derive_failure_modes(self) -> None:
        rows = self._con.execute(
            """
            SELECT record_id, title, component_keys, component_mentions,
                   source_case_refs, safe_evidence_refs,
                   game_patch, passive_tree_version, pob_version_or_commit
            FROM deep_research_records
            WHERE record_kind = 'failure_mode' AND status = 'valid'
            ORDER BY record_id
            """
        ).fetchall()
        for row in rows:
            if (
                self._limit is not None
                and self.stats.get(SOURCE_FAILURE_MODE, {}).get("candidates", 0) >= self._limit
            ):
                break
            keys = _loads(row["component_keys"], []) or []
            roles = _role_map(row["component_mentions"])
            if len(keys) < 2:
                self._bump(SOURCE_FAILURE_MODE, "skipped_insufficient_keys")
                continue
            source = next((key for key in keys if roles.get(key) in FAILURE_SOURCE_ROLES), None)
            target = next((key for key in keys if roles.get(key) in FAILURE_TARGET_ROLES), None)
            if source is None or target is None or source == target:
                self._bump(SOURCE_FAILURE_MODE, "skipped_no_risk_pair")
                continue
            if source not in self._nodes or target not in self._nodes:
                self._bump(SOURCE_FAILURE_MODE, "skipped_endpoint_missing")
                continue
            self._push(
                source_type=SOURCE_FAILURE_MODE,
                source_ref=str(row["record_id"]),
                title=str(row["title"] or ""),
                source_key=source,
                target_key=target,
                edge_type="creates_failure_risk_for",
                rationale_suffix=f"失效风险（{roles[source]}→{roles[target]}）",
                source_case_refs=_loads(row["source_case_refs"], []) or [],
                safe_evidence_refs=_loads(row["safe_evidence_refs"], []) or [],
                game_patch=str(row["game_patch"] or ""),
                passive_tree_version=str(row["passive_tree_version"] or ""),
                pob_version_or_commit=str(row["pob_version_or_commit"] or ""),
                confidence="low",
                context_requirements=_fixed_context(),
            )
            self._bump(SOURCE_FAILURE_MODE, "candidates")

    def derive_modelability_caveats(self) -> None:
        rows = self._con.execute(
            """
            SELECT record_id, title, component_keys, component_mentions,
                   source_case_refs, safe_evidence_refs,
                   game_patch, passive_tree_version, pob_version_or_commit
            FROM deep_research_records
            WHERE record_kind = 'modelability_caveat' AND status = 'valid'
            ORDER BY record_id
            """
        ).fetchall()
        for row in rows:
            if (
                self._limit is not None
                and self.stats.get(SOURCE_MODELABILITY_CAVEAT, {}).get("candidates", 0)
                >= self._limit
            ):
                break
            keys = _loads(row["component_keys"], []) or []
            roles = _role_map(row["component_mentions"])
            if len(keys) < 2:
                self._bump(SOURCE_MODELABILITY_CAVEAT, "skipped_insufficient_keys")
                continue
            source = _first_priority(keys, roles, CAVEAT_SOURCE_ROLES)
            targets = [
                key for key in keys if roles.get(key) in CAVEAT_TARGET_ROLES and key != source
            ][:3]
            if source is None or not targets:
                self._bump(SOURCE_MODELABILITY_CAVEAT, "skipped_no_caveat_pair")
                continue
            if source not in self._nodes:
                self._bump(SOURCE_MODELABILITY_CAVEAT, "skipped_endpoint_missing")
                continue
            for target in targets:
                if target not in self._nodes:
                    self._bump(SOURCE_MODELABILITY_CAVEAT, "skipped_endpoint_missing")
                    continue
                self._push(
                    source_type=SOURCE_MODELABILITY_CAVEAT,
                    source_ref=str(row["record_id"]),
                    title=str(row["title"] or ""),
                    source_key=source,
                    target_key=target,
                    edge_type="has_modelability_caveat",
                    rationale_suffix=f"可建模性提示（{roles[source]}→{roles[target]}）",
                    source_case_refs=_loads(row["source_case_refs"], []) or [],
                    safe_evidence_refs=_loads(row["safe_evidence_refs"], []) or [],
                    game_patch=str(row["game_patch"] or ""),
                    passive_tree_version=str(row["passive_tree_version"] or ""),
                    pob_version_or_commit=str(row["pob_version_or_commit"] or ""),
                    confidence="low",
                    context_requirements=_fixed_context(),
                )
                self._bump(SOURCE_MODELABILITY_CAVEAT, "candidates")

    # -- orchestration -------------------------------------------------------

    def derive(self) -> list[dict[str, Any]]:
        if SOURCE_TRANSITION_GATE in self._source_types:
            self.derive_transition_gates()
        if SOURCE_MECHANIC_CHAIN in self._source_types:
            self.derive_mechanic_chains()
        if SOURCE_FAILURE_MODE in self._source_types:
            self.derive_failure_modes()
        if SOURCE_MODELABILITY_CAVEAT in self._source_types:
            self.derive_modelability_caveats()
        self.candidates.sort(
            key=lambda edge: (edge["source_key"], edge["target_key"], edge["edge_type"])
        )
        return self.candidates


def _dedupe_by_identity(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Drop candidates that collapse to the same deterministic edge identity.

    Mirrors the write path's ON CONFLICT(edge_id) DO UPDATE so dry-run/validate
    counts report unique edges instead of identity duplicates.
    """
    output = research_models.ResearcherOutput.model_validate(
        {"schema_version": 4, "fragments": [], "semantic_edges": candidates}
    )
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    dropped = 0
    for edge in output.semantic_edges:
        edge_id = research_memory._edge_identity(edge)[0]
        if edge_id in seen:
            dropped += 1
            continue
        seen.add(edge_id)
        kept.append(edge.model_dump(exclude_none=True, exclude_defaults=True))
    return kept, dropped


def _existing_directional_edges(con: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """Existing directional rows exactly as the service conflict queries see them.

    The service's inverse/cycle queries filter visibility, split, knowledge_scope,
    directionality and planner_visible only (no status/copy-safety predicate), so
    the pre-check must use the same filter set or it could miss a conflict the
    service would reject at chunk level.
    """
    rows = con.execute(
        """
        SELECT source_key, target_key, edge_type FROM research_semantic_edges
        WHERE visibility = 'creator_visible' AND split = 'train_context'
          AND knowledge_scope = 'global_seed'
          AND planner_visible = 1 AND directionality = 'directional'
        """
    ).fetchall()
    return [(str(r[0]), str(r[1]), str(r[2])) for r in rows]


def _conflicts(
    candidates: list[dict[str, Any]],
    existing: list[tuple[str, str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Drop candidates that would create an inverse edge or a short directed cycle.

    Mirrors the service's _semantic_conflict contract (inverse pair plus the
    depth-bounded cycle walk over directional, planner-visible rows) against
    existing rows plus earlier candidates, so chunked writes do not trip
    whole-chunk rejections.
    """
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    accepted: list[tuple[str, str, str]] = list(existing)
    for edge in candidates:
        source = edge["source_key"]
        target = edge["target_key"]
        edge_type = edge["edge_type"]
        inverse = any(
            other_source == target and other_target == source and other_type == edge_type
            for other_source, other_target, other_type in accepted
        )
        if inverse:
            dropped.append(edge)
            continue
        frontier = {target}
        cyclic = False
        for _hop in range(CYCLE_HOP_LIMIT):
            next_frontier: set[str] = set()
            for other_source, other_target, _other_type in accepted:
                if other_source in frontier:
                    next_frontier.add(other_target)
            if source in next_frontier:
                cyclic = True
                break
            if not next_frontier:
                break
            frontier = next_frontier
        if cyclic:
            dropped.append(edge)
            continue
        accepted.append((source, target, edge_type))
        kept.append(edge)
    return kept, dropped


def derive_candidates(
    *,
    db_path: Path,
    nodes_by_key: dict[str, Any],
    snapshot_id: str,
    source_types: set[str] | None = None,
    limit_per_source: int | None = None,
) -> dict[str, Any]:
    con = mature_learning.connect(db_path)
    try:
        deriver = _Deriver(
            con,
            nodes_by_key,
            snapshot_id,
            source_types=source_types,
            limit_per_source=limit_per_source,
        )
        candidates = deriver.derive()
        existing = _existing_directional_edges(con)
    finally:
        con.close()
    candidates, deduped_count = _dedupe_by_identity(candidates)
    kept, dropped = _conflicts(candidates, existing)
    return {
        "candidates": kept,
        "conflictDropped": dropped,
        "deduplicated": deduped_count,
        "stats": deriver.stats,
        "existingEdgeCount": len(existing),
    }


def _chunks(values: list[Any], size: int) -> list[list[Any]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _run_mode(
    *,
    memory: research_memory.ResearchMemoryService,
    candidates: list[dict[str, Any]],
    mode: str,
    chunk_size: int,
    keep_going: bool,
) -> dict[str, Any]:
    method = memory.propose_semantic_edges if mode == "apply" else memory.validate_semantic_edges
    accepted_ids: list[str] = []
    errors: list[dict[str, Any]] = []
    for index, chunk in enumerate(_chunks(candidates, chunk_size)):
        payload = {"schema_version": 4, "fragments": [], "semantic_edges": chunk}
        result = method(payload)
        if str(result.get("status") or "") == "accepted":
            accepted_ids.extend(result.get("edgeIds") or result.get("candidateEdgeIds") or [])
        else:
            errors.append({"chunk": index, "errorCode": result.get("errorCode"), "result": result})
            if not keep_going:
                break
    return {"accepted": accepted_ids, "errors": errors}


def _graph_service(graph_snapshot_index: str | Path):
    index_path = Path(graph_snapshot_index)
    if not index_path.is_file():
        index_path = graph_seed.ensure_installed()
    return graph_tools.service_from_snapshot_index(str(index_path))


def _snapshot_copy(source: Path) -> Path:
    """Consistent read-only copy of the Research Memory DB for deterministic derivation.

    The running MCP servers may maintain the mutable store concurrently; deriving
    from a point-in-time copy keeps candidate generation deterministic. The copy is
    created with the SQLite backup API (safe under concurrent writers) and is
    deleted automatically.
    """
    directory = tempfile.mkdtemp(prefix="backfill-semantic-edges-")
    target = Path(directory) / "mature_build_learning.sqlite"
    try:
        source_uri = f"file:{source.as_posix()}?mode=ro"
        with (
            closing(sqlite3.connect(source_uri, uri=True)) as source_con,
            closing(sqlite3.connect(target)) as target_con,
        ):
            source_con.backup(target_con)
    except Exception:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            Path(directory).rmdir()
        except OSError:
            pass
        raise
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default=str(paths.mature_learning_path()),
        help="Research Memory SQLite (default: user-data mature_build_learning.sqlite)",
    )
    parser.add_argument(
        "--graph-snapshot-index",
        default=str(paths.user_data_dir() / "physical_graph" / "snapshot_index.sqlite"),
    )
    parser.add_argument(
        "--mode",
        choices=("dry-run", "validate", "apply"),
        default="dry-run",
    )
    parser.add_argument(
        "--source-types",
        default=",".join(SOURCE_TYPES),
        help="comma-separated subset of: " + ",".join(SOURCE_TYPES),
    )
    parser.add_argument(
        "--limit-per-source",
        type=int,
        default=None,
        help="Approximate cap: evaluated per source row (a modelability_caveat row can emit "
        "up to 3 edges), so the last row may overshoot the limit by a few edges.",
    )
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE)
    parser.add_argument("--keep-going", action="store_true")
    parser.add_argument("--output", default="", help="write candidates JSON for review")
    args = parser.parse_args(argv)

    source_types = {item.strip() for item in args.source_types.split(",") if item.strip()}
    unknown = source_types - set(SOURCE_TYPES)
    if unknown:
        parser.error(f"unknown source types: {', '.join(sorted(unknown))}")

    service = _graph_service(args.graph_snapshot_index)
    snapshot_id = str(service.snapshot.snapshot_id)
    nodes_by_key = getattr(service, "_nodes_by_key", {})

    source_db = Path(args.source)
    copy = _snapshot_copy(source_db)
    try:
        derived = derive_candidates(
            db_path=copy,
            nodes_by_key=nodes_by_key,
            snapshot_id=snapshot_id,
            source_types=source_types,
            limit_per_source=args.limit_per_source,
        )
    finally:
        try:
            copy.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            copy.parent.rmdir()
        except OSError:
            pass
    candidates = derived["candidates"]
    conflict_dropped = derived["conflictDropped"]
    stats = derived["stats"]

    report: dict[str, Any] = {
        "mode": args.mode,
        "snapshotId": snapshot_id,
        "existingEdgeCount": derived["existingEdgeCount"],
        "candidateCount": len(candidates),
        "deduplicatedCount": derived["deduplicated"],
        "conflictDroppedCount": len(conflict_dropped),
        "conflictDroppedSamples": [
            {
                "sourceKey": edge["source_key"],
                "targetKey": edge["target_key"],
                "edgeType": edge["edge_type"],
            }
            for edge in conflict_dropped[:5]
        ],
        "stats": stats,
    }

    if args.output:
        Path(args.output).write_text(
            json.dumps({"candidates": candidates}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        report["output"] = args.output

    if args.mode == "dry-run":
        report["samples"] = [
            {
                "sourceKey": edge["source_key"],
                "targetKey": edge["target_key"],
                "edgeType": edge["edge_type"],
                "confidence": edge["confidence"],
                "rationale": edge["rationale"],
            }
            for edge in candidates[:10]
        ]
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    memory = research_memory.ResearchMemoryService(graph_service=service)
    run = _run_mode(
        memory=memory,
        candidates=candidates,
        mode=args.mode,
        chunk_size=args.chunk_size,
        keep_going=args.keep_going,
    )
    report["acceptedCount"] = len(run["accepted"])
    report["errorCount"] = len(run["errors"])
    report["errors"] = run["errors"][:5]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if run["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
