"""Shared pytest fixtures.

The headless engine is expensive to start, so it's session-scoped and reused. The
`fireball` fixture resets to a known build (level-20 Fireball) before each test that needs it.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("POE2_RESEARCH_POB_READBACK", "0")
_MANAGED_TEST_USER_DATA = "POE2_MCP_DATA" not in os.environ
if _MANAGED_TEST_USER_DATA:
    os.environ["POE2_MCP_DATA"] = tempfile.mkdtemp(prefix="poe2-build-mcp-tests-")

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from server.compute.engine import PobEngine  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _isolated_user_data():
    yield
    if _MANAGED_TEST_USER_DATA:
        shutil.rmtree(os.environ["POE2_MCP_DATA"], ignore_errors=True)


@pytest.fixture(scope="session")
def engine():
    # Pin the engine to the REPO shim — paths.pob_headless_script() otherwise prefers an installed
    # user-data copy, which would shadow repo edits and make the suite test stale code.
    eng = PobEngine(script=_REPO_ROOT / "pob" / "pob_headless.lua")
    yield eng
    eng.close()


@pytest.fixture()
def fireball(engine):
    engine.new_build()
    engine.paste_skill("Fireball 20/0  1")
    return engine
