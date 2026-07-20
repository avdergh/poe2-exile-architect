"""Snapshot-isolated, reproducible passive-tree optimization."""

from __future__ import annotations

from typing import Any

from .engine import PobEngine, PobEngineError
from .state import build_state_hash, canonical_payload_hash


OPTIMIZER_VERSION = "greedy_v2"


def optimize_passives(
    engine: PobEngine,
    *,
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
    """Optimize an immutable snapshot, then optionally commit it with compare-and-swap."""

    input_xml = engine.get_xml()
    input_hash = build_state_hash(input_xml)
    if expected_state_hash is not None and expected_state_hash != input_hash:
        return {
            "ok": False,
            "errorCode": "build_state_conflict",
            "error": "the active build changed after it was read; refresh state and retry",
            "expectedStateHash": expected_state_hash,
            "actualStateHash": input_hash,
        }

    request = {
        "optimizerVersion": OPTIMIZER_VERSION,
        "metric": metric,
        "points": points,
        "nodeType": node_type,
        "candidates": candidates,
        "goals": goals,
        # Required-node order remains meaningful in v2 and is therefore part of the request hash.
        "require": require,
        "reset": reset,
    }
    request_hash = canonical_payload_hash(request, prefix="passive-request")

    rpc_params = {
        "metric": metric,
        "points": points,
        "node_type": node_type,
        "candidates": candidates,
        "goals": goals,
        "require": require,
        "reset": reset,
        "optimizerVersion": OPTIMIZER_VERSION,
    }
    execution_mode = "isolated_engine"
    already_committed = False

    try:
        isolated = PobEngine(
            luajit=engine.luajit,
            src_dir=engine.src_dir,
            script=engine.script,
        )
    except PobEngineError as exc:
        if "process limit reached" not in str(exc).casefold():
            return _engine_error(exc, input_hash=input_hash, request_hash=request_hash)
        # The session pool normally reserves a process for optimizer/Judge work. If an explicit
        # deployment setting consumes every slot, keep the operation available by running under the
        # active engine's transaction lock and restoring the input for previews/errors.
        execution_mode = "active_snapshot_fallback"
        try:
            fallback = _run_active_snapshot(
                engine,
                input_xml=input_xml,
                input_hash=input_hash,
                preview=preview,
                rpc_params=rpc_params,
            )
        except (OSError, PobEngineError) as fallback_exc:
            return _engine_error(
                fallback_exc,
                input_hash=input_hash,
                request_hash=request_hash,
            )
        if fallback.get("ok") is False:
            return fallback
        raw = fallback["raw"]
        output_xml = fallback["outputXml"]
        tree_version = fallback["treeVersion"]
        already_committed = not preview
    except OSError as exc:
        return _engine_error(exc, input_hash=input_hash, request_hash=request_hash)
    else:
        try:
            isolated.load_build_xml(input_xml, name=f"passive-preview-{request_hash[-12:]}")
            raw = isolated.call("optimize_passives", **rpc_params)
            output_xml = isolated.get_xml()
            tree_version = isolated.get_build().get("treeVersion") or isolated.info.get(
                "treeVersion"
            )
        except (OSError, PobEngineError) as exc:
            return _engine_error(exc, input_hash=input_hash, request_hash=request_hash)
        finally:
            isolated.close()

    output_hash = build_state_hash(output_xml)
    result = dict(raw) if isinstance(raw, dict) else {}
    result_hash = canonical_payload_hash(
        {
            "allocated": result.get("allocated"),
            "allocatedNodeIds": result.get("allocatedNodeIds"),
            "metrics": result.get("metrics"),
            "pointsUsed": result.get("pointsUsed"),
            "pointsRemaining": result.get("pointsRemaining"),
        },
        prefix="passive-result",
    )
    result.update(
        {
            "ok": True,
            "optimizerVersion": OPTIMIZER_VERSION,
            "inputStateHash": input_hash,
            "requestHash": request_hash,
            "resultHash": result_hash,
            "outputStateHash": output_hash,
            "treeVersion": tree_version,
            "executionMode": execution_mode,
            "preview": preview,
            "committed": False,
            "determinismStatus": "replayable_snapshot_bound",
        }
    )
    if preview:
        return result

    if already_committed:
        result["committed"] = True
        result["committedStateHash"] = output_hash
        return result

    commit = engine.compare_and_load_xml(
        expected_state_hash=input_hash,
        xml=output_xml,
        name=f"passive-commit-{request_hash[-12:]}",
    )
    if not commit.get("ok"):
        result.update(commit)
        result["committed"] = False
        return result
    result["committed"] = True
    result["committedStateHash"] = commit["stateHash"]
    return result


def _run_active_snapshot(
    engine: PobEngine,
    *,
    input_xml: str,
    input_hash: str,
    preview: bool,
    rpc_params: dict[str, Any],
) -> dict[str, Any]:
    with engine.transaction_lock():
        current_xml = engine.get_xml()
        current_hash = build_state_hash(current_xml)
        if current_hash != input_hash:
            return {
                "ok": False,
                "errorCode": "build_state_conflict",
                "error": "the active build changed before optimization could start",
                "expectedStateHash": input_hash,
                "actualStateHash": current_hash,
            }
        try:
            raw = engine.call("optimize_passives", **rpc_params)
            output_xml = engine.get_xml()
            tree_version = engine.get_build().get("treeVersion") or engine.info.get("treeVersion")
            if preview:
                engine.load_build_xml(input_xml, name="passive-preview-restore")
                if build_state_hash(engine.get_xml()) != input_hash:
                    raise PobEngineError("active snapshot preview did not restore the input state")
        except Exception:
            try:
                engine.load_build_xml(input_xml, name="passive-fallback-rollback")
            except Exception:
                pass
            raise
        return {
            "ok": True,
            "raw": raw,
            "outputXml": output_xml,
            "treeVersion": tree_version,
        }


def _engine_error(
    exc: BaseException,
    *,
    input_hash: str,
    request_hash: str,
) -> dict[str, Any]:
    return {
        "ok": False,
        "errorCode": "optimizer_engine_unavailable",
        "error": str(exc),
        "optimizerVersion": OPTIMIZER_VERSION,
        "inputStateHash": input_hash,
        "requestHash": request_hash,
    }
