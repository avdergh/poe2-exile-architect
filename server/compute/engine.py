"""Python client for the headless PoB-PoE2 calculation engine.

Spawns LuaJIT running ``pob/pob_headless.lua`` as a long-lived subprocess and talks to
it over a line-delimited JSON-RPC protocol on stdin/stdout. The engine loads its (large)
game data exactly once at startup, then answers many calls cheaply — which is why it's a
persistent process rather than a per-call invocation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from .. import paths
from .skilltext import normalize_skill_text

_LUAJIT_FALLBACKS = (
    r"C:\msys64\ucrt64\bin\luajit.exe",
    r"C:\msys64\mingw64\bin\luajit.exe",
)
try:
    _MAX_ENGINE_PROCESSES = max(1, int(os.environ.get("POE2_MCP_MAX_ENGINES", "5")))
except ValueError:
    _MAX_ENGINE_PROCESSES = 5
_ENGINE_CAPACITY = threading.BoundedSemaphore(_MAX_ENGINE_PROCESSES)
_ENGINE_CAPACITY_LOCK = threading.Lock()
_ACTIVE_ENGINE_PROCESSES = 0


class PobEngineError(RuntimeError):
    """Raised when the engine fails to start or returns an error for a call."""


def available_engine_slots() -> int:
    with _ENGINE_CAPACITY_LOCK:
        return max(0, _MAX_ENGINE_PROCESSES - _ACTIVE_ENGINE_PROCESSES)


def max_engine_processes() -> int:
    return _MAX_ENGINE_PROCESSES


def _acquire_engine_slot() -> None:
    global _ACTIVE_ENGINE_PROCESSES
    if not _ENGINE_CAPACITY.acquire(blocking=False):
        raise PobEngineError(
            f"PoB engine process limit reached ({_MAX_ENGINE_PROCESSES}); retry after another "
            "compute operation or MCP session finishes"
        )
    with _ENGINE_CAPACITY_LOCK:
        _ACTIVE_ENGINE_PROCESSES += 1


def _release_engine_slot() -> None:
    global _ACTIVE_ENGINE_PROCESSES
    with _ENGINE_CAPACITY_LOCK:
        if _ACTIVE_ENGINE_PROCESSES <= 0:
            return
        _ACTIVE_ENGINE_PROCESSES -= 1
    _ENGINE_CAPACITY.release()


def _find_luajit() -> str:
    # Only honor POB_LUAJIT if it points at a real file. A manifest user-config like
    # "${user_config.luajit_path}" arrives as an empty/literal string when left blank, which
    # must NOT shadow the bundled binary (that caused WinError 2 on installed bundles).
    override = os.environ.get("POB_LUAJIT")
    if override and Path(override).exists():
        return override
    bundled = paths.bundled_luajit()
    if bundled:
        return str(bundled)
    found = shutil.which("luajit")
    if found:
        return found
    for cand in _LUAJIT_FALLBACKS:
        if Path(cand).exists():
            return cand
    raise FileNotFoundError("luajit not found on PATH; set the POB_LUAJIT environment variable.")


class PobEngine:
    """A long-lived headless PoB engine process."""

    def __init__(
        self,
        luajit: str | None = None,
        src_dir: str | os.PathLike[str] | None = None,
        script: str | os.PathLike[str] | None = None,
        show_engine_logs: bool = False,
    ) -> None:
        _acquire_engine_slot()
        self._slot_acquired = True
        self._closed = False
        try:
            self._start(
                luajit=luajit,
                src_dir=src_dir,
                script=script,
                show_engine_logs=show_engine_logs,
            )
        except BaseException:
            try:
                self._terminate_failed_start()
            except Exception:
                pass
            finally:
                self._release_slot()
            raise

    def _start(
        self,
        *,
        luajit: str | None,
        src_dir: str | os.PathLike[str] | None,
        script: str | os.PathLike[str] | None,
        show_engine_logs: bool,
    ) -> None:
        self.luajit = luajit or _find_luajit()
        self.src_dir = Path(src_dir) if src_dir else paths.pob_src_dir()
        self.script = Path(script) if script else paths.pob_headless_script()
        if not self.src_dir.is_dir():
            raise FileNotFoundError(f"PoB src dir not found: {self.src_dir}")
        if not self.script.is_file():
            raise FileNotFoundError(f"headless script not found: {self.script}")

        stderr = None if show_engine_logs else subprocess.DEVNULL
        self.proc = subprocess.Popen(
            [self.luajit, str(self.script)],
            cwd=str(self.src_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._next_id = 0
        self._lock = threading.Lock()
        ready = self._read_frame()
        if not ready.get("ready"):
            raise PobEngineError(f"engine failed to initialise: {ready}")
        self.info: dict[str, Any] = ready

    # -- low-level I/O -------------------------------------------------------
    def _read_frame(self) -> dict[str, Any]:
        assert self.proc.stdout is not None
        while True:
            line = self.proc.stdout.readline()
            if line == "":
                code = self.proc.poll()
                raise PobEngineError(f"engine exited (code={code}) before responding")
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                # Defensive: skip any stray non-JSON line on stdout.
                continue

    def call(self, method: str, **params: Any) -> Any:
        if self.proc.poll() is not None:
            raise PobEngineError(f"engine is not running (code={self.proc.returncode})")
        assert self.proc.stdin is not None
        # One request/response pair must not interleave with another.
        with self._lock:
            self._next_id += 1
            req_id = self._next_id
            request = {"id": req_id, "method": method, "params": params}
            self.proc.stdin.write(json.dumps(request) + "\n")
            self.proc.stdin.flush()
            # Read until THIS request's response arrives. Calls are serialized by the lock, so
            # the only valid frame is the one whose id matches; any other frame (a stray engine
            # emit, or a leftover from an earlier desync) must be skipped. Without this, a single
            # extra line would shift every later response onto the wrong call.
            for _ in range(10000):
                resp = self._read_frame()
                if resp.get("id") == req_id:
                    break
                # A non-matching frame means a desync (stray/leftover emit); skip it but surface it
                # on stderr rather than silently swallowing what could be a real protocol problem.
                sys.stderr.write(
                    f"[pob-engine] skipped stray frame id={resp.get('id')!r} "
                    f"while awaiting id={req_id}\n"
                )
            else:
                raise PobEngineError(f"no response for request id={req_id} (engine desync)")
        if not resp.get("ok"):
            raise PobEngineError(resp.get("error", "unknown engine error"))
        return resp["result"]

    # -- convenience wrappers ------------------------------------------------
    def ping(self) -> dict[str, Any]:
        return self.call("ping")

    def new_build(self) -> dict[str, Any]:
        return self.call("new_build")

    def set_class(self, class_name: str, ascendancy: str | None = None) -> dict[str, Any]:
        return self.call("set_class", **{"class": class_name, "ascendancy": ascendancy})

    def set_level(self, level: int) -> dict[str, Any]:
        return self.call("set_level", level=level)

    def load_build_xml(self, xml: str, name: str = "imported") -> dict[str, Any]:
        return self.call("load_build_xml", xml=xml, name=name)

    def paste_skill(self, text: str) -> dict[str, Any]:
        return self.call("paste_skill", text=normalize_skill_text(text))

    def add_skill_group(self, text: str, include_in_full_dps: bool = False) -> dict[str, Any]:
        return self.call(
            "add_skill_group",
            text=normalize_skill_text(text),
            includeInFullDPS=include_in_full_dps,
        )

    def list_jewel_sockets(self) -> dict[str, Any]:
        return self.call("list_jewel_sockets")

    def equip_jewel(
        self, raw: str, socket: int | None = None, keys: list[str] | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"raw": raw}
        if socket is not None:
            params["socket"] = socket
        if keys is not None:
            params["keys"] = keys
        return self.call("equip_jewel", **params)

    def get_stats(self, keys: list[str] | None = None) -> dict[str, Any]:
        r = self.call("get_stats", keys=keys)
        # An empty Lua stats table serializes to JSON [] (array), not {}. Normalize to a dict so
        # callers can always treat stats as a mapping — otherwise an uncomputable build (e.g. an
        # attack skill with no weapon equipped yet) returns stats=[] and crashes optimize_item /
        # evaluate_build / compare_to with "'list' object has no attribute 'get'".
        if isinstance(r, dict) and isinstance(r.get("stats"), list):
            r["stats"] = {}
        return r

    def set_config(
        self,
        options: dict[str, Any] | None = None,
        custom_mods: str | None = None,
        keys: list[str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if options:
            params["options"] = options
        if custom_mods is not None:
            params["customMods"] = custom_mods
        if keys is not None:
            params["keys"] = keys
        return self.call("set_config", **params)

    def add_item(
        self, raw: str, slot: str | None = None, keys: list[str] | None = None
    ) -> dict[str, Any]:
        return self.call("add_item", raw=raw, slot=slot, keys=keys)

    def eval_items(
        self, slot: str, items: list[str], keys: list[str] | None = None
    ) -> dict[str, Any]:
        """Batch-evaluate candidate items in a slot; returns each one's `keys` stats. Restores."""
        return self.call("eval_items", slot=slot, items=items, keys=keys)

    def crafting_options(self, slot: str) -> dict[str, Any]:
        """PoB's own crafting data (runes/soul cores, corrupted implicits, essence mods) applicable to
        the item in `slot`, as ready item-text lines. Used by the crafting optimizer."""
        return self.call("crafting_options", slot=slot)

    def search_passives(
        self, query: str = "", node_type: str | None = None, limit: int = 30
    ) -> dict[str, Any]:
        return self.call("search_passives", query=query, node_type=node_type, limit=limit)

    def get_passive(self, node: str | int) -> dict[str, Any]:
        return self.call("get_passive", node=node)

    def alloc_passive(self, node: str | int) -> dict[str, Any]:
        return self.call("alloc_passive", node=node)

    def dealloc_passive(self, node: str | int) -> dict[str, Any]:
        return self.call("dealloc_passive", node=node)

    def optimize_passives(
        self,
        metric: str = "TotalDPS",
        points: int = 0,
        node_type: str = "Notable",
        candidates: int = 50,
        goals: dict[str, float] | None = None,
        require: list[str | int] | None = None,
        reset: bool = False,
    ) -> dict[str, Any]:
        return self.call(
            "optimize_passives",
            metric=metric,
            points=points,
            node_type=node_type,
            candidates=candidates,
            goals=goals,
            require=require,
            reset=reset,
        )

    def get_xml(self) -> str:
        return self.call("get_xml")["xml"]

    def get_build(self) -> dict[str, Any]:
        return self.call("get_build")

    def get_defenses(self) -> dict[str, Any]:
        return self.call("get_defenses")

    def unequip_item(self, slot: str) -> dict[str, Any]:
        return self.call("unequip_item", slot=slot)

    def list_config_options(self, query: str = "", limit: int = 60) -> dict[str, Any]:
        return self.call("list_config_options", query=query, limit=limit)

    def load_build_code(self, code: str, name: str = "imported") -> dict[str, Any]:
        """Import a PoB share code (inflated to XML in Python, then loaded)."""
        from .pob_code import decode_code

        return self.load_build_xml(decode_code(code), name=name)

    def load_build_link(self, url: str, name: str = "imported") -> dict[str, Any]:
        """Import a pobb.in / pastebin build link (network)."""
        from .pob_code import to_xml

        return self.load_build_xml(to_xml(url), name=name)

    # -- lifecycle -----------------------------------------------------------
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        finally:
            self._release_slot()

    def _release_slot(self) -> None:
        if self._slot_acquired:
            self._slot_acquired = False
            _release_engine_slot()

    def _terminate_failed_start(self) -> None:
        proc = getattr(self, "proc", None)
        if proc is None or proc.poll() is not None:
            return
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    def __enter__(self) -> "PobEngine":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
