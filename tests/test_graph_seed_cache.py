from dataclasses import replace
from datetime import timedelta
import hashlib
import json
from pathlib import Path

import pytest

from server import paths
from server.knowledge import graph_seed, physical_graph as pg
from scripts.package_physical_graph_seed import package_graph_seed
from test_release_seed_packaging import _graph_snapshot


def graph_fixture(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    snapshot = _graph_snapshot("physical-graph-cache-test")
    file = source / "snapshot.json"
    pg.save_snapshot(snapshot, file)
    pg.register_snapshot(source / "snapshot_index.sqlite", snapshot, file)
    bundle = tmp_path / "bundle"
    output = bundle / "data" / "physical_graph"
    package_graph_seed(source_dir=source, output_dir=output)
    monkeypatch.setattr(paths, "BUNDLE_ROOT", bundle)
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path / "user")
    graph_seed._ensure_validated.cache_clear()
    index = graph_seed.ensure_installed()
    graph_seed._ensure_validated.cache_clear()
    return index, output, snapshot


def test_stable_graph_does_not_repeat_full_validation(tmp_path, monkeypatch):
    index, _, _ = graph_fixture(tmp_path, monkeypatch)
    calls = []
    original = pg.load_snapshot

    def measured(path):
        calls.append(str(path))
        return original(path)

    monkeypatch.setattr(pg, "load_snapshot", measured)
    assert graph_seed.ensure_installed() == index
    count = len(calls)
    assert count > 0
    for _ in range(4):
        assert graph_seed.ensure_installed() == index
    assert len(calls) == count


def test_registry_change_revalidates_and_preserves_newer_user_graph(tmp_path, monkeypatch):
    index, _, snapshot = graph_fixture(tmp_path, monkeypatch)
    graph_seed.ensure_installed()
    newer = replace(
        snapshot,
        snapshot_id="physical-graph-newer-user",
        created_at=snapshot.created_at + timedelta(days=1),
    )
    file = index.parent / "newer.json"
    pg.save_snapshot(newer, file)
    pg.register_snapshot(index, newer, file)
    assert graph_seed.ensure_installed() == index
    assert pg.load_latest_snapshot(index).snapshot_id == newer.snapshot_id


def test_updated_bundle_replaces_older_installed_graph(tmp_path, monkeypatch):
    index, output, snapshot = graph_fixture(tmp_path, monkeypatch)
    graph_seed.ensure_installed()
    newer = replace(
        snapshot,
        snapshot_id="physical-graph-newer-bundle",
        created_at=snapshot.created_at + timedelta(days=1),
    )
    file = output / "snapshots" / "new.json"
    pg.save_snapshot(newer, file)
    (output / "seed.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "snapshotId": newer.snapshot_id,
                "snapshotFile": "snapshots/new.json",
                "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
            }
        )
    )
    assert graph_seed.ensure_installed() == index
    assert pg.load_latest_snapshot(index).snapshot_id == newer.snapshot_id


@pytest.mark.parametrize("which", ["installed", "bundled"])
def test_changed_or_corrupt_snapshot_cannot_hit_previous_validation_cache(
    tmp_path, monkeypatch, which
):
    index, output, _ = graph_fixture(tmp_path, monkeypatch)
    graph_seed.ensure_installed()
    manifest = json.loads((output / "seed.json").read_text())
    file = (
        (output / manifest["snapshotFile"])
        if which == "bundled"
        else Path(pg.list_registered_snapshots(index)[0]["snapshot_path"])
    )
    file.write_bytes(b"corrupt snapshot")
    with pytest.raises((OSError, ValueError)):
        graph_seed.ensure_installed()
