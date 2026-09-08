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
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

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


def _resolve_runtime_paths(
    *,
    src_dir: str | os.PathLike[str] | None,
    script: str | os.PathLike[str] | None,
) -> tuple[Path, Path]:
    """Resolve a source tree and bridge from one runtime root.

    Explicit callers may provide both paths.  If they provide only one, infer its sibling from the
    packaged PoB layout rather than combining it with an independently selected default.
    """

    if src_dir is None and script is None:
        pair = paths.pob_runtime_pair()
        return pair.src_dir, pair.headless_script
    if script is not None:
        resolved_script = Path(script)
        resolved_src = (
            Path(src_dir)
            if src_dir is not None
            else resolved_script.parent / "PathOfBuilding-PoE2" / "src"
        )
    else:
        resolved_src = Path(src_dir)  # type: ignore[arg-type]
        resolved_script = resolved_src.parents[1] / "pob_headless.lua"

    expected_src = resolved_script.parent / "PathOfBuilding-PoE2" / "src"
    if resolved_src.resolve() != expected_src.resolve():
        raise ValueError("PoB src directory and headless bridge must belong to the same runtime")
    return resolved_src, resolved_script


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
        self.src_dir, self.script = _resolve_runtime_paths(src_dir=src_dir, script=script)
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
        # Re-entrant so a typed transaction can hold the engine across several RPC frames while the
        # individual calls keep using the same serialization primitive.
        self._lock = threading.RLock()
        ready = self._read_frame()
        if not ready.get("ready"):
            raise PobEngineError(f"engine failed to initialise: {ready}")
        if ready.get("runtimeContract") != paths.POB_RUNTIME_CONTRACT:
            raise PobEngineError(
                "headless engine runtime contract is incompatible with this server"
            )
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

    @contextmanager
    def transaction_lock(self) -> Iterator[None]:
        """Serialize a multi-RPC read/check/mutate sequence on this engine."""

        with self._lock:
            yield

    def compare_and_load_xml(
        self,
        *,
        expected_state_hash: str,
        xml: str,
        name: str = "transaction-commit",
    ) -> dict[str, Any]:
        """Atomically load XML only if the active build still matches the observed snapshot."""

        from .state import build_state_hash

        with self._lock:
            before_xml = self.get_xml()
            actual = build_state_hash(before_xml)
            if actual != expected_state_hash:
                return {
                    "ok": False,
                    "errorCode": "build_state_conflict",
                    "error": "the active build changed before the result could be committed",
                    "expectedStateHash": expected_state_hash,
                    "actualStateHash": actual,
                }
            expected_output = build_state_hash(xml)
            try:
                self.load_build_xml(xml, name=name)
            except Exception:
                try:
                    self.load_build_xml(before_xml, name="transaction-exception-rollback")
                except Exception:
                    pass
                raise
            committed = build_state_hash(self.get_xml())
            if committed != expected_output:
                self.load_build_xml(before_xml, name="transaction-rollback")
                return {
                    "ok": False,
                    "errorCode": "build_state_commit_mismatch",
                    "error": "PoB did not preserve the planned state; the original build was restored",
                    "expectedOutputStateHash": expected_output,
                    "actualOutputStateHash": committed,
                }
            return {"ok": True, "stateHash": committed}

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
        return self.call("paste_skill", text=normalize_skill_text(text, default_level=None))

    def probe_regular_skill_group(
        self,
        *,
        group_index: int,
        group_xml: str,
        active_skill_index: int,
        expected_skill_name: str,
        keys: list[str],
        objective_keys: list[str],
        expected_effect_id: str | None = None,
    ) -> dict[str, Any]:
        """Probe one group; index is a hint, exact effect/name controls output selection.

        The caller owns the complete restore guard and must handle requiresFullRebuild before
        consuming measurements: that result deliberately has no statistics or capability proof.
        """
        return self.call(
            "probe_regular_skill_group",
            index=group_index,
            groupXml=group_xml,
            activeSkillIndex=active_skill_index,
            expectedSkillName=expected_skill_name,
            keys=keys,
            objectiveKeys=objective_keys,
            expectedEffectId=expected_effect_id,
        )

    def add_skill_group(self, text: str, include_in_full_dps: bool = False) -> dict[str, Any]:
        return self.call(
            "add_skill_group",
            text=normalize_skill_text(text, default_level=None),
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
        self,
        slot: str,
        items: list[str],
        keys: list[str] | None = None,
        *,
        isolate_each_item: bool = False,
        replacement_context: bool = False,
    ) -> dict[str, Any]:
        """Batch-evaluate candidate items in a slot; returns each one's `keys` stats. Restores."""
        params = {"isolateEachItem": True} if isolate_each_item else {}
        if replacement_context:
            params["replacementContext"] = True
        return self.call("eval_items", slot=slot, items=items, keys=keys, **params)

    def inspect_item_replacement_context(
        self, expected_context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Inspect/verify the exact PoB output and owning skill group for item probes."""
        params = {"expectedContext": expected_context} if expected_context is not None else {}
        return self.call("item_replacement_context", **params)

    def gem_level_requirements(self, gem_name: str) -> dict[str, Any]:
        """Read-only per-level requirements of a gem (levelRequirement per gem level).

        PoB owns the real level-requirement curve (the corpus only has crafting metadata); the
        leveled-build kernel uses this to decide skill usability at a character level. Never
        mutates the build.
        """
        return self.call("gem_level_requirements", gem_name=gem_name)

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

    def list_reallocation_candidates(self, limit: int | None = 12) -> dict[str, Any]:
        if limit is None:
            return self.call("list_reallocation_candidates")
        return self.call("list_reallocation_candidates", limit=limit)

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

    def select_judge_skill(
        self,
        *,
        offense_skill_group_index: int,
        expected_skill_name: str,
    ) -> dict[str, Any]:
        return self.call(
            "select_judge_skill",
            offenseSkillGroupIndex=offense_skill_group_index,
            expectedSkillName=expected_skill_name,
        )

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
