from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from server import paths
from server.compute.engine import _resolve_runtime_paths


def _write_runtime(root: Path, *, marker: str) -> None:
    (root / "PathOfBuilding-PoE2" / "src").mkdir(parents=True)
    (root / "PathOfBuilding-PoE2" / "runtime" / "lua").mkdir(parents=True)
    (root / "PathOfBuilding-PoE2" / "src" / "HeadlessWrapper.lua").write_text(
        marker, encoding="utf-8"
    )
    (root / "PathOfBuilding-PoE2" / "runtime" / "lua" / "dkjson.lua").write_text(
        marker, encoding="utf-8"
    )
    (root / "pob_headless.lua").write_text(marker, encoding="utf-8")


def _configure_roots(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    bundle = tmp_path / "bundle"
    user_data = tmp_path / "user-data"
    _write_runtime(bundle / "pob", marker="bundle")
    (bundle / "data").mkdir(parents=True)
    (bundle / "data" / "VERSION").write_text("0.1.59", encoding="utf-8")
    (bundle / "manifest.json").write_text(
        json.dumps({"version": "0.1.60"}), encoding="utf-8"
    )
    monkeypatch.setattr(paths, "BUNDLE_ROOT", bundle)
    monkeypatch.setattr(paths, "user_data_dir", lambda: user_data)
    return bundle, user_data


def _write_corpus(path: Path, *, built_at: str, schema_version: int = 4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.executemany(
            "INSERT INTO meta(key, value) VALUES(?, ?)",
            (
                ("schema_version", str(schema_version)),
                ("built_at", built_at),
            ),
        )


def test_old_user_runtime_falls_back_to_complete_bundle_pair(tmp_path, monkeypatch):
    bundle, user_data = _configure_roots(monkeypatch, tmp_path)
    _write_runtime(user_data / "pob", marker="old-user")
    (user_data / "installed.json").write_text(
        json.dumps(
            {
                "version": "0.1.39.2-local.20260710",
                "app_version": "0.1.39",
            }
        ),
        encoding="utf-8",
    )

    pair = paths.pob_runtime_pair()

    assert pair.source == "bundle"
    assert pair.src_dir == bundle / "pob" / "PathOfBuilding-PoE2" / "src"
    assert pair.headless_script == bundle / "pob" / "pob_headless.lua"
    assert paths.pob_src_dir() == pair.src_dir
    assert paths.pob_headless_script() == pair.headless_script


def test_old_user_corpus_does_not_shadow_new_bundle_seed(tmp_path, monkeypatch):
    bundle, user_data = _configure_roots(monkeypatch, tmp_path)
    bundled = bundle / "data" / "corpus.sqlite"
    updated = user_data / "corpus.sqlite"
    _write_corpus(bundled, built_at="2026-08-29T00:00:00+00:00")
    _write_corpus(updated, built_at="2026-06-26T00:00:00+00:00")

    assert paths.corpus_path() == bundled


def test_newer_same_schema_user_corpus_remains_selected(tmp_path, monkeypatch):
    bundle, user_data = _configure_roots(monkeypatch, tmp_path)
    bundled = bundle / "data" / "corpus.sqlite"
    updated = user_data / "corpus.sqlite"
    _write_corpus(bundled, built_at="2026-08-29T00:00:00+00:00")
    _write_corpus(updated, built_at="2026-08-30T00:00:00+00:00")

    assert paths.corpus_path() == updated


def test_incompatible_user_corpus_schema_falls_back_to_bundle(tmp_path, monkeypatch):
    bundle, user_data = _configure_roots(monkeypatch, tmp_path)
    bundled = bundle / "data" / "corpus.sqlite"
    updated = user_data / "corpus.sqlite"
    _write_corpus(bundled, built_at="2026-08-29T00:00:00+00:00", schema_version=4)
    _write_corpus(updated, built_at="2026-08-30T00:00:00+00:00", schema_version=5)

    assert paths.corpus_path() == bundled


def test_new_data_metadata_does_not_upgrade_an_old_engine(tmp_path, monkeypatch):
    bundle, user_data = _configure_roots(monkeypatch, tmp_path)
    _write_runtime(user_data / "pob", marker="old-engine-new-data")
    (user_data / "installed.json").write_text(
        json.dumps(
            {
                "version": "0.1.60.4",
                "app_version": "0.1.60",
                "engine_app_version": "0.1.39",
                "engine_contract": paths.POB_RUNTIME_CONTRACT,
            }
        ),
        encoding="utf-8",
    )

    pair = paths.pob_runtime_pair()

    assert pair.source == "bundle"
    assert pair.src_dir.is_relative_to(bundle)
    assert pair.headless_script.is_relative_to(bundle)


def test_compatible_user_runtime_is_selected_as_one_pair(tmp_path, monkeypatch):
    _, user_data = _configure_roots(monkeypatch, tmp_path)
    _write_runtime(user_data / "pob", marker="updated-user")
    (user_data / "installed.json").write_text(
        json.dumps(
            {
                "version": "0.1.60.4",
                "app_version": "0.1.60",
                "engine_app_version": "0.1.60",
                "engine_contract": paths.POB_RUNTIME_CONTRACT,
            }
        ),
        encoding="utf-8",
    )

    pair = paths.pob_runtime_pair()

    assert pair.source == "user-data"
    assert pair.src_dir == user_data / "pob" / "PathOfBuilding-PoE2" / "src"
    assert pair.headless_script == user_data / "pob" / "pob_headless.lua"


def test_incomplete_user_runtime_never_mixes_with_bundle(tmp_path, monkeypatch):
    bundle, user_data = _configure_roots(monkeypatch, tmp_path)
    (user_data / "pob").mkdir(parents=True)
    (user_data / "pob" / "pob_headless.lua").write_text("new bridge", encoding="utf-8")
    (user_data / "installed.json").write_text(
        json.dumps(
            {
                "app_version": "0.1.60",
                "engine_contract": paths.POB_RUNTIME_CONTRACT,
            }
        ),
        encoding="utf-8",
    )

    pair = paths.pob_runtime_pair()

    assert pair.source == "bundle"
    assert pair.src_dir.is_relative_to(bundle)
    assert pair.headless_script.is_relative_to(bundle)


def test_explicit_single_runtime_path_infers_its_sibling(tmp_path):
    root = tmp_path / "explicit" / "pob"
    script = root / "pob_headless.lua"
    src = root / "PathOfBuilding-PoE2" / "src"

    resolved_src, resolved_script = _resolve_runtime_paths(src_dir=None, script=script)
    assert (resolved_src, resolved_script) == (src, script)

    resolved_src, resolved_script = _resolve_runtime_paths(src_dir=src, script=None)
    assert (resolved_src, resolved_script) == (src, script)


def test_explicit_paths_from_same_runtime_are_accepted(tmp_path):
    root = tmp_path / "same" / "pob"
    script = root / "pob_headless.lua"
    src = root / "PathOfBuilding-PoE2" / "src"

    resolved_src, resolved_script = _resolve_runtime_paths(src_dir=src, script=script)

    assert (resolved_src, resolved_script) == (src, script)


def test_explicit_paths_from_different_runtimes_are_rejected(tmp_path):
    first = tmp_path / "first" / "pob"
    second = tmp_path / "second" / "pob"

    with pytest.raises(ValueError, match="must belong to the same runtime"):
        _resolve_runtime_paths(
            src_dir=first / "PathOfBuilding-PoE2" / "src",
            script=second / "pob_headless.lua",
        )
