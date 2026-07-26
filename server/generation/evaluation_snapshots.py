"""Process-local immutable XML snapshots for Phase 5 artifact handoff.

Trusted receipts remain raw-free. The exact Agent-generated XML evaluated by Judge is retained only
in memory long enough for ``save_final_build_artifact`` to persist the accepted snapshot. This
avoids treating PoB's derived-output refreshes as build mutations without creating another durable
raw-XML store.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock

from server.compute.state import build_state_hash
from server.judge.evaluator import compute_source_hash


_MAX_SNAPSHOTS = 32
_SNAPSHOT_TTL = timedelta(hours=2)
_LOCK = RLock()


@dataclass(frozen=True)
class EvaluationSnapshot:
    run_id: str
    attempt_index: int
    candidate_id: str
    source_hash: str
    semantic_state_hash: str
    xml: str
    created_at: datetime


_SNAPSHOTS: OrderedDict[tuple[str, int], EvaluationSnapshot] = OrderedDict()


def remember(
    *,
    run_id: str,
    attempt_index: int,
    candidate_id: str,
    source_hash: str,
    xml: str,
) -> EvaluationSnapshot:
    """Remember one exact Judge input without writing it to disk."""

    if compute_source_hash(xml) != source_hash:
        raise ValueError("evaluation snapshot source hash mismatch")
    snapshot = EvaluationSnapshot(
        run_id=run_id,
        attempt_index=attempt_index,
        candidate_id=candidate_id,
        source_hash=source_hash,
        semantic_state_hash=build_state_hash(xml),
        xml=xml,
        created_at=datetime.now(timezone.utc),
    )
    key = (run_id, attempt_index)
    with _LOCK:
        _evict_expired_locked()
        existing = _SNAPSHOTS.get(key)
        if existing is not None and existing != snapshot:
            raise ValueError("evaluation snapshot conflict")
        _SNAPSHOTS[key] = snapshot
        _SNAPSHOTS.move_to_end(key)
        while len(_SNAPSHOTS) > _MAX_SNAPSHOTS:
            _SNAPSHOTS.popitem(last=False)
    return snapshot


def read(
    *,
    run_id: str,
    attempt_index: int,
    candidate_id: str,
    source_hash: str,
) -> EvaluationSnapshot | None:
    """Return a still-live snapshot only when every trusted binding matches."""

    key = (run_id, attempt_index)
    with _LOCK:
        _evict_expired_locked()
        snapshot = _SNAPSHOTS.get(key)
        if (
            snapshot is None
            or snapshot.candidate_id != candidate_id
            or snapshot.source_hash != source_hash
        ):
            return None
        _SNAPSHOTS.move_to_end(key)
        return snapshot


def forget(*, run_id: str, attempt_index: int | None = None) -> None:
    """Discard one attempt or every transient snapshot for a completed run."""

    with _LOCK:
        if attempt_index is not None:
            _SNAPSHOTS.pop((run_id, attempt_index), None)
            return
        for key in [key for key in _SNAPSHOTS if key[0] == run_id]:
            _SNAPSHOTS.pop(key, None)


def _evict_expired_locked() -> None:
    cutoff = datetime.now(timezone.utc) - _SNAPSHOT_TTL
    for key in [key for key, value in _SNAPSHOTS.items() if value.created_at < cutoff]:
        _SNAPSHOTS.pop(key, None)
