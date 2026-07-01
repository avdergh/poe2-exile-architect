"""Safe-call wrapper for dedicated judge engines."""

from __future__ import annotations

import threading
from typing import Any, Callable

from server.compute.engine import PobEngineError

from . import evaluator, models


def safe_evaluate_active_build(
    engine_factory: Callable[[], Any],
    *,
    snapshot_id: str,
    timeout_seconds: float | None = 900.0,
    source_context: str = "generated_candidate",
) -> dict[str, Any]:
    if timeout_seconds is not None:
        box: dict[str, Any] = {}

        def _run() -> None:
            try:
                engine = engine_factory()
                box["engine"] = engine
                if box.get("cancelled"):
                    _close_engine(engine)
                    return
                box["result"] = evaluator.evaluate_active_build(
                    engine,
                    snapshot_id,
                    source_context=source_context,
                )
            except (PobEngineError, EOFError, TimeoutError, OSError) as exc:
                box["error"] = exc
            except Exception as exc:  # noqa: BLE001 - prevent timed-out daemon worker noise.
                box["error"] = exc

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout_seconds)
        if thread.is_alive():
            box["cancelled"] = True
            _close_engine(box.get("engine"))
            return compute_failed_evaluation(
                snapshot_id,
                "TimeoutError",
            )
        if "error" in box:
            _close_engine(box.get("engine"))
            return compute_failed_evaluation(snapshot_id, type(box["error"]).__name__)
        return box["result"]
    engine = None
    try:
        engine = engine_factory()
        return evaluator.evaluate_active_build(engine, snapshot_id, source_context=source_context)
    except (PobEngineError, EOFError, TimeoutError, OSError) as exc:
        _close_engine(engine)
        return compute_failed_evaluation(snapshot_id, type(exc).__name__)
    except Exception as exc:  # noqa: BLE001 - factory/import failures must be sanitized.
        _close_engine(engine)
        return compute_failed_evaluation(snapshot_id, type(exc).__name__)


def compute_failed_evaluation(snapshot_id: str, error_kind: str) -> dict[str, Any]:
    return {
        "snapshotId": snapshot_id,
        "pass": False,
        "rewardEligible": False,
        "hardFailures": ["pob_compute_failed"],
        "physicalInvalidFailures": [],
        "caveats": ["engine_respawn_required"],
        "modelability": {
            "status": "not_modelable",
            "coreBlocked": True,
            "failureCodes": ["pob_compute_failed"],
            "caveats": [],
        },
        "scoreVector": {
            "offense": {"value": 0.0, "blocked": True},
            "defense": {"value": 0.0, "blocked": True},
            "recovery": {"value": 0.0, "blocked": True},
            "mobility": {"value": 0.0, "blocked": True},
        },
        "scoreBreakdown": {},
        "scoreScale": "0_to_1",
        "scenarioFit": {"mappingFit": 0.0, "bossingFit": 0.0, "hybridFit": 0.0},
        "qualityBand": "invalid",
        "aggregateScore": {
            "value": 0.0,
            "weightProfile": models.WEIGHT_PROFILE,
        },
        "levelBand": "unknown",
        "metricProvenance": {},
        "reproducibility": {"evaluatorVersion": models.EVALUATOR_VERSION},
        "errorKind": error_kind,
    }


def _close_engine(engine: Any) -> None:
    close = getattr(engine, "close", None)
    if callable(close):
        close()
