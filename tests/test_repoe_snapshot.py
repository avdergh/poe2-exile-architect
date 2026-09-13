import json
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import sys

import pytest

from pipeline import repoe_snapshot

COMMIT = "a" * 40


def source(monkeypatch):
    requests = []

    def read(url):
        requests.append(url)
        if url == repoe_snapshot.HEAD_URL:
            return json.dumps({"sha": COMMIT}).encode()
        assert f"/{COMMIT}/" in url
        if url.endswith("exported-version.txt"):
            return b"4.5.5.2\n"
        return json.dumps({url.rsplit("/", 1)[-1]: {"value": "static"}}).encode()

    monkeypatch.setattr(repoe_snapshot, "_read_url", read)
    return requests, read


def test_fetch_freezes_head_once_and_binds_every_file(monkeypatch, tmp_path):
    requests, _ = source(monkeypatch)
    result = repoe_snapshot.fetch_snapshot(tmp_path)
    assert requests.count(repoe_snapshot.HEAD_URL) == 1
    assert all(f"/{COMMIT}/" in url for url in requests[1:])
    assert result["sourceCommit"] == COMMIT
    assert result["exportedVersion"] == "4.5.5.2"
    assert repoe_snapshot.verify_snapshot(tmp_path) == result


def test_failed_download_preserves_prior_export(monkeypatch, tmp_path):
    _, read = source(monkeypatch)
    repoe_snapshot.fetch_snapshot(tmp_path, commit=COMMIT)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    def failed(url):
        if url.endswith("mods.json"):
            raise OSError("interrupted download")
        if url.endswith("exported-version.txt"):
            return read(url)
        return b'{"different": {}}'

    monkeypatch.setattr(repoe_snapshot, "_read_url", failed)
    with pytest.raises(OSError):
        repoe_snapshot.fetch_snapshot(tmp_path, commit=COMMIT)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


@pytest.mark.parametrize("change", ["bytes", "commit", "url", "duplicate", "version", "schema"])
def test_mixed_or_relabelled_inputs_fail_verification(monkeypatch, tmp_path, change):
    source(monkeypatch)
    manifest = repoe_snapshot.fetch_snapshot(tmp_path, commit=COMMIT)
    if change == "bytes":
        (tmp_path / repoe_snapshot.SOURCE_FILES[0]).write_text('{"altered": {}}')
    elif change == "commit":
        manifest["sourceCommit"] = "b" * 40
    elif change == "url":
        manifest["files"][0]["sourceUrl"] = "https://repoe-fork.github.io/poe2/base_items.min.json"
    elif change == "duplicate":
        manifest["files"][1] = manifest["files"][0]
    elif change == "version":
        manifest["exportedVersion"] = "4.5.6.0"
    else:
        manifest["schemaVersion"] = 3
    (tmp_path / repoe_snapshot.MANIFEST_NAME).write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        repoe_snapshot.verify_snapshot(tmp_path)


@pytest.mark.parametrize("initial", ["v2", "legacy", "no_manifest"])
def test_interrupted_publication_cannot_authorize_mixed_files(monkeypatch, tmp_path, initial):
    _, read = source(monkeypatch)
    if initial == "v2":
        repoe_snapshot.fetch_snapshot(tmp_path, commit=COMMIT)
    else:
        for name in repoe_snapshot.SOURCE_FILES:
            (tmp_path / name).write_bytes(b'{"old": {}}')
        if initial == "legacy":
            (tmp_path / repoe_snapshot.MANIFEST_NAME).write_text(json.dumps({"exportedVersion": "4.5.4.11"}))
    monkeypatch.setattr(repoe_snapshot, "_read_url", lambda url: read(url) if url.endswith(".txt") else b'{"changed": {}}')
    replace = Path.replace

    def interrupted(path, target):
        if path.name == repoe_snapshot.SOURCE_FILES[1]:
            raise OSError("interrupted publication")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", interrupted)
    with pytest.raises(OSError):
        repoe_snapshot.fetch_snapshot(tmp_path, commit=COMMIT)
    with pytest.raises(ValueError, match="publication interrupted"):
        repoe_snapshot.verify_snapshot(tmp_path)
    monkeypatch.setattr(Path, "replace", replace)
    repoe_snapshot.fetch_snapshot(tmp_path, commit=COMMIT)
    assert repoe_snapshot.verify_snapshot(tmp_path)["sourceCommit"] == COMMIT


def test_builder_rejects_pending_export_before_replacing_corpus(monkeypatch, tmp_path):
    from pipeline import build_corpus

    database = tmp_path / "corpus.sqlite"
    database.write_bytes(b"previous reviewed corpus")
    (tmp_path / repoe_snapshot.PENDING_NAME).write_text("{}")
    monkeypatch.setattr(build_corpus, "RAW_DIR", tmp_path)
    monkeypatch.setattr(build_corpus, "DB_PATH", database)
    with pytest.raises(ValueError, match="publication interrupted"):
        build_corpus.build()
    assert database.read_bytes() == b"previous reviewed corpus"


def test_input_reader_holds_one_complete_snapshot_during_publication(monkeypatch, tmp_path):
    source(monkeypatch)
    repoe_snapshot.fetch_snapshot(tmp_path, commit=COMMIT)
    before = (tmp_path / repoe_snapshot.SOURCE_FILES[0]).read_bytes()
    downloaded = threading.Event()

    def replacement(url):
        if url.endswith(".txt"):
            return b"4.5.6.0\n"
        if url.endswith("mods.json"):
            downloaded.set()
        return b'{"new": {}}'

    monkeypatch.setattr(repoe_snapshot, "_read_url", replacement)
    with ThreadPoolExecutor(max_workers=1) as worker:
        with repoe_snapshot.snapshot_guard(tmp_path):
            future = worker.submit(repoe_snapshot.fetch_snapshot, tmp_path, commit="b" * 40)
            assert downloaded.wait(5)
            assert not future.done()
            assert (tmp_path / repoe_snapshot.SOURCE_FILES[0]).read_bytes() == before
            assert repoe_snapshot.verify_snapshot(tmp_path)["sourceCommit"] == COMMIT
        assert future.result(timeout=5)["sourceCommit"] == "b" * 40


def test_legacy_cache_does_not_gain_immutable_source_claims(tmp_path):
    (tmp_path / repoe_snapshot.MANIFEST_NAME).write_text(json.dumps({"exportedVersion": "4.5.5.2"}))
    assert repoe_snapshot.verify_snapshot(tmp_path) is None


def _mock_transport(monkeypatch):
    """Exercise Request/urlopen and the real snapshot publication, without network I/O."""
    requests = []

    class Response:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self): return self.body

    def transport(request, *, timeout):
        assert timeout == 120
        url = request.full_url
        requests.append(url)
        if url == repoe_snapshot.HEAD_URL:
            return Response(json.dumps({"sha": "b" * 40}).encode())
        if url.endswith("exported-version.txt"):
            return Response(b"4.5.5.2\n")
        assert url.startswith(repoe_snapshot.REPOSITORY + "/")
        return Response(json.dumps({"source": {"url": url}}).encode())

    monkeypatch.setattr(repoe_snapshot, "urlopen", transport)
    return requests, transport


def _builder_inputs(monkeypatch, tmp_path):
    from pipeline import build_corpus

    raw_dir = tmp_path / "raw"
    certificate = tmp_path / "corpus.json"
    certificate.write_text(json.dumps({"repoeSourceCommit": COMMIT}))
    database = tmp_path / "corpus.sqlite"
    database.write_bytes(b"previous reviewed corpus")
    monkeypatch.setattr(build_corpus, "RAW_DIR", raw_dir)
    monkeypatch.setattr(build_corpus, "DB_PATH", database)
    monkeypatch.setattr(build_corpus, "REVIEWED_SOURCE_PATH", certificate)
    monkeypatch.setattr(build_corpus.wiki, "fetch_all", lambda **_kwargs: 0)
    return build_corpus, raw_dir, certificate, database


@pytest.mark.parametrize("cache", ["absent", "matching", "wrong_commit", "legacy", "damaged"])
def test_reviewed_fetch_is_pinned_at_transport_boundary_and_replaces_wrong_cache(monkeypatch, tmp_path, cache):
    build_corpus, raw_dir, _certificate, _database = _builder_inputs(monkeypatch, tmp_path)
    requests, _ = _mock_transport(monkeypatch)
    if cache != "absent":
        repoe_snapshot.fetch_snapshot(raw_dir, commit="b" * 40 if cache == "wrong_commit" else COMMIT)
        if cache == "legacy":
            (raw_dir / repoe_snapshot.MANIFEST_NAME).unlink()
        elif cache == "damaged":
            (raw_dir / repoe_snapshot.SOURCE_FILES[0]).write_text('{"corrupt": {}}')
        requests.clear()
    build_corpus.fetch_all(expected_commit=build_corpus.reviewed_source_commit())
    assert repoe_snapshot.HEAD_URL not in requests
    assert len(requests) == (0 if cache == "matching" else len(repoe_snapshot.SOURCE_FILES) + 1)
    assert all(f"/{COMMIT}/" in url for url in requests)
    assert repoe_snapshot.verify_snapshot(raw_dir)["sourceCommit"] == COMMIT
    for name in repoe_snapshot.SOURCE_FILES:
        assert f"/{COMMIT}/" in (raw_dir / name).read_text()


def test_plain_refresh_still_resolves_latest_upstream_head(monkeypatch, tmp_path):
    build_corpus, raw_dir, _certificate, _database = _builder_inputs(monkeypatch, tmp_path)
    requests, _ = _mock_transport(monkeypatch)
    repoe_snapshot.fetch_snapshot(raw_dir, commit=COMMIT)
    requests.clear()
    build_corpus.fetch_all(refresh=True)
    assert requests.count(repoe_snapshot.HEAD_URL) == 1
    assert repoe_snapshot.verify_snapshot(raw_dir)["sourceCommit"] == "b" * 40


def test_reviewed_fetch_failure_keeps_prior_raw_and_database(monkeypatch, tmp_path):
    build_corpus, raw_dir, _certificate, database = _builder_inputs(monkeypatch, tmp_path)
    _requests, transport = _mock_transport(monkeypatch)
    repoe_snapshot.fetch_snapshot(raw_dir, commit="b" * 40)
    before = {path.name: path.read_bytes() for path in raw_dir.iterdir()}

    def failed(request, *, timeout):
        if request.full_url.endswith("mods.json"):
            raise OSError("incomplete reviewed download")
        return transport(request, timeout=timeout)

    monkeypatch.setattr(repoe_snapshot, "urlopen", failed)
    with pytest.raises(OSError, match="incomplete reviewed"):
        build_corpus.fetch_all(expected_commit=COMMIT)
    assert {path.name: path.read_bytes() for path in raw_dir.iterdir()} == before
    assert database.read_bytes() == b"previous reviewed corpus"


def test_build_rechecks_expected_commit_under_lock_after_fetch_before_touching_db(monkeypatch, tmp_path):
    build_corpus, raw_dir, _certificate, database = _builder_inputs(monkeypatch, tmp_path)
    _mock_transport(monkeypatch)
    build_corpus.fetch_all(expected_commit=COMMIT)
    # Another publisher wins between CLI fetch and build; a bound, coherent snapshot
    # is insufficient when it is no longer the reviewed source requested by this build.
    repoe_snapshot.fetch_snapshot(raw_dir, commit="b" * 40)
    real_guard = repoe_snapshot.snapshot_guard
    real_verify = repoe_snapshot.verify_snapshot
    locked = False

    @contextmanager
    def guarded(path):
        nonlocal locked
        with real_guard(path):
            locked = True
            try:
                yield
            finally:
                locked = False

    def verified(path):
        assert locked
        return real_verify(path)

    monkeypatch.setattr(repoe_snapshot, "snapshot_guard", guarded)
    monkeypatch.setattr(repoe_snapshot, "verify_snapshot", verified)
    monkeypatch.setattr(build_corpus, "_load", lambda _name: pytest.fail("must reject before loading inputs"))
    with pytest.raises(ValueError, match="does not match the reviewed"):
        build_corpus.build(expected_commit=COMMIT)
    assert database.read_bytes() == b"previous reviewed corpus"


@pytest.mark.parametrize("certificate", [{}, {"repoeSourceCommit": "master"}, {"repoeSourceCommit": "a" * 39},
                                          {"repoeSourceCommit": "a" * 41}, {"repoeSourceCommit": None}, []])
def test_reviewed_cli_rejects_missing_or_nonimmutable_certificate_before_io(monkeypatch, tmp_path, certificate):
    build_corpus, _raw_dir, cert_path, database = _builder_inputs(monkeypatch, tmp_path)
    cert_path.write_text(json.dumps(certificate))
    requests, _ = _mock_transport(monkeypatch)
    with pytest.raises(ValueError, match="full immutable SHA"):
        build_corpus.main(["--reviewed-source"])
    assert not requests
    assert database.read_bytes() == b"previous reviewed corpus"


@pytest.mark.parametrize("argv,refresh,expected", [([], False, None), (["--refresh"], True, None),
                                                 (["--reviewed-source"], False, COMMIT)])
def test_cli_passes_the_same_fixed_commit_to_fetch_and_build(monkeypatch, tmp_path, argv, refresh, expected):
    build_corpus, _raw_dir, _cert_path, _database = _builder_inputs(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(sys, "argv", ["build_corpus", "--refresh"])
    monkeypatch.setattr(build_corpus, "fetch_all", lambda **kwargs: calls.append(("fetch", kwargs)))
    monkeypatch.setattr(build_corpus, "build", lambda **kwargs: calls.append(("build", kwargs)) or {})
    assert build_corpus.main(argv) == 0
    assert calls == [("fetch", {"refresh": refresh, "expected_commit": expected}),
                     ("build", {"expected_commit": expected})]


@pytest.mark.parametrize("argv", [["--refresh", "--reviewed-source"], ["--reviewed-soruce"]])
def test_cli_rejects_ambiguous_or_misspelled_source_selection(monkeypatch, tmp_path, argv):
    build_corpus, _raw_dir, _cert_path, database = _builder_inputs(monkeypatch, tmp_path)
    requests, _ = _mock_transport(monkeypatch)
    with pytest.raises(SystemExit) as raised:
        build_corpus.main(argv)
    assert raised.value.code == 2
    assert not requests
    assert database.read_bytes() == b"previous reviewed corpus"
