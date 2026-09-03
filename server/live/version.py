"""Corpus data-version checks and updates.

`check_data_version` compares the bundled corpus against the upstream RePoE data.
`update_corpus` can rebuild the corpus locally from source (works today) or download a
prebuilt corpus from a published release (wired up for when releases exist).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import urllib.request
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from .. import paths
from ..knowledge import db
from . import prices

REPOE_PROBE = "https://repoe-fork.github.io/poe2/base_items.min.json"
UA = {"User-Agent": "poe2-build-mcp/0.1"}


def _fetch(url: str, timeout: float = 60.0) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def _upstream_last_modified() -> str | None:
    try:
        req = urllib.request.Request(REPOE_PROBE, method="HEAD", headers=UA)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.headers.get("Last-Modified")
    except Exception:  # noqa: BLE001
        return None


def check_data_version() -> dict[str, Any]:
    """Report bundled corpus version vs upstream freshness and the current league."""
    local = db.corpus_info()
    upstream = _upstream_last_modified()
    try:
        league = prices.resolve_league()["name"]
    except Exception:  # noqa: BLE001
        league = None

    recommendation = "unknown"
    built_at = local.get("built_at")
    if upstream:
        try:
            up_dt = parsedate_to_datetime(upstream)
            if built_at:
                recommendation = (
                    "update_available" if up_dt > datetime.fromisoformat(built_at) else "up_to_date"
                )
        except Exception:  # noqa: BLE001
            pass

    return {
        "local": local,
        "upstream_last_modified": upstream,
        "current_league": league,
        "recommendation": recommendation,
    }


def update_corpus(
    rebuild_from_source: bool = False, release_url: str | None = None
) -> dict[str, Any]:
    """Update the bundled corpus.

    rebuild_from_source=True re-fetches RePoE and rebuilds the DB locally (works today).
    Otherwise, downloads a prebuilt corpus from `release_url` (a manifest JSON with
    {url, sha256, version}); without one configured, this is a no-op with guidance.
    """
    if rebuild_from_source:
        from pipeline import build_corpus

        build_corpus.fetch_all(refresh=True)
        counts = build_corpus.build()
        db.reset()
        return {"updated": True, "mode": "rebuild_from_source", "counts": counts}

    if not release_url:
        return {
            "updated": False,
            "mode": "download",
            "reason": (
                "No published corpus release configured yet. "
                "Pass rebuild_from_source=true to rebuild from RePoE locally."
            ),
        }

    manifest = json.loads(_fetch(release_url))
    blob = _fetch(manifest["url"])
    sha = manifest.get("sha256")
    if sha and hashlib.sha256(blob).hexdigest() != sha:
        return {"updated": False, "error": "checksum mismatch"}
    # `db.db_path()` is the active read selection and may resolve to the immutable bundled seed
    # when the existing user corpus is stale. Updates always belong in writable user data.
    dest = paths.user_data_dir() / "corpus.sqlite"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=dest.parent, suffix=".tmp") as tf:
        tf.write(blob)
        tmp = Path(tf.name)
    db.reset()
    shutil.move(str(tmp), str(dest))
    return {"updated": True, "mode": "download", "version": manifest.get("version")}
