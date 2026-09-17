from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys

import pytest

from server.runtime.compute_runtime_lock import RuntimeLeaseBusy, runtime_read_lease, runtime_write_lease


@pytest.fixture(autouse=True)
def private_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path / "runtime-data"))


@contextmanager
def child_reader():
    code = (
        "from server.runtime.compute_runtime_lock import runtime_read_lease; "
        "import sys; "
        "lease=runtime_read_lease(); print('ready',flush=True); "
        "sys.stdin.readline(); lease.close()"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        assert child.stdout.readline().strip() == "ready"
        yield child
    finally:
        if child.poll() is None:
            child.communicate("\n", timeout=5)
        assert child.returncode == 0


def test_os_shared_readers_coexist_across_processes_and_writer_is_busy():
    with child_reader(), child_reader(), runtime_read_lease():
        with pytest.raises(RuntimeLeaseBusy):
            with runtime_write_lease():
                pytest.fail("writer acquired while cross-process readers were active")
    with runtime_write_lease():
        with pytest.raises(RuntimeLeaseBusy):
            runtime_read_lease()


def test_os_process_exit_releases_lease():
    code = (
        "from server.runtime.compute_runtime_lock import runtime_read_lease; "
        "import os; lease=runtime_read_lease(); os._exit(0)"
    )
    child = subprocess.run(
        [sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], timeout=5,
        capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert child.returncode == 0
    with runtime_write_lease():
        pass


def test_release_install_refuses_cross_domain_active_reader_before_replacing_files(monkeypatch):
    from server.live import update

    monkeypatch.setattr(update, "_fetch_manifest", lambda: {"version": "9.9.9", "app_version": "9.9.9"})
    target = Path(os.environ["POE2_MCP_DATA"]) / "installed.json"
    with child_reader():
        result = update.apply_updates(force=True)
        assert result["errorCode"] == "compute_busy" and result["updated"] is False
        assert not target.exists()
    assert update.apply_updates(force=True)["updated"] is True
    assert target.is_file()


def test_legacy_corpus_download_also_refuses_active_reader(monkeypatch):
    from server.live import version

    monkeypatch.setattr(version, "_fetch", lambda url: (
        b'{"url":"https://example.test/corpus","version":"test"}'
        if url.endswith("manifest") else b"fake corpus"
    ))
    with child_reader():
        result = version.update_corpus(release_url="https://example.test/manifest")
        assert result["errorCode"] == "compute_busy"
        assert not (Path(os.environ["POE2_MCP_DATA"]) / "corpus.sqlite").exists()
