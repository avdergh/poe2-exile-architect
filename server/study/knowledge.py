"""Read-only adapters; no seed install, migration, semantic writes or query receipts."""

from __future__ import annotations

import json
import sqlite3

from server import paths
from server.knowledge import db, graph_tools, physical_graph, research_memory
from .storage import StudyError, fingerprint


def graph_service():
    manifest_path = paths.physical_graph_seed_manifest_path()
    manifest = json.loads(manifest_path.read_text("utf-8"))
    file = (manifest_path.parent / manifest["snapshotFile"]).resolve()
    if not file.is_relative_to(manifest_path.parent.resolve()):
        raise StudyError("study_graph_path_invalid")
    if fingerprint(file.read_bytes()) != manifest["sha256"]:
        raise StudyError("study_graph_hash_invalid")
    snapshot = physical_graph.load_snapshot(file)
    if snapshot.snapshot_id != manifest["snapshotId"]:
        raise StudyError("study_graph_identity_invalid")
    return graph_tools.GraphQueryService(snapshot)


def query(kind: str, payload: dict) -> dict:
    try:
        if kind == "graph":
            # The shared facade enforces the typed operation/payload contract.
            service = graph_service()
            return service.run_tool(payload.get("tool_name", ""), payload.get("payload", {}))
        if kind == "research":
            allowed = {
                "query",
                "component_keys",
                "limit",
                "detail_level",
                "record_ids",
                "primary_skill_key",
                "ascendancy_key",
                "game_patch",
                "build_family_keys",
                "record_kinds",
                "class_key",
                "passive_tree_version",
            }
            if set(payload) - allowed:
                raise StudyError("study_query_unknown_fields")
            path = paths.mature_learning_path()
            if not path.is_file():
                path = paths.mature_learning_release_seed_path()
            if not path.is_file():
                return {"status": "unavailable", "reason": "research_memory_missing"}
            service = research_memory.ResearchMemoryService(
                db_path=path,
                graph_service=graph_service(),
                initialize_store=False,
                read_only=True,
            )
            return service.query_research_memory(**payload, response_profile="full")
        if kind in {"gem", "item", "unique", "mechanic"}:
            if set(payload) != {"query"} or not isinstance(payload["query"], str):
                raise StudyError("study_query_requires_exact_name")
            if kind == "mechanic":
                from server.knowledge import mechanics

                result = mechanics.explain(payload["query"])
            else:
                result = {"gem": db.get_gem, "item": db.get_item, "unique": db.get_unique}[kind](
                    payload["query"]
                )
            return {"status": "available" if result else "not_found", "result": result}
        raise StudyError("study_query_kind_invalid")
    except (OSError, sqlite3.Error, KeyError, ValueError) as exc:
        if isinstance(exc, StudyError):
            raise
        return {"status": "unavailable", "reason": "study_knowledge_unavailable"}
