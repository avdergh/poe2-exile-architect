"""An OS read/write lease protecting live compute from cross-domain runtime replacement.

Only a lock file is stored, never job metadata or build material. OS handle ownership
releases the lease on process exit. Lock ordering is runtime lease, then corpus guard.
"""

from __future__ import annotations

import sys
from typing import Any

from server import paths


class RuntimeLeaseBusy(RuntimeError):
    def __init__(self) -> None:
        super().__init__("compute_busy")


class RuntimeLease:
    def __init__(self, *, shared: bool) -> None:
        path = paths.user_data_dir() / "runtime" / ".compute-runtime.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("a+b")
        self._overlapped: Any = None
        try:
            if sys.platform == "win32":
                self._windows_acquire(shared)
            else:
                import fcntl
                try:
                    fcntl.flock(self._file.fileno(), (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise RuntimeLeaseBusy() from exc
        except BaseException:
            self._file.close()
            raise

    def _windows_acquire(self, shared: bool) -> None:
        import ctypes
        from ctypes import wintypes
        import msvcrt

        class Overlapped(ctypes.Structure):
            _fields_ = [
                ("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE),
            ]

        self._overlapped = Overlapped()
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        lock = kernel.LockFileEx
        lock.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                         wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
        lock.restype = wintypes.BOOL
        # LOCKFILE_FAIL_IMMEDIATELY; absence of LOCKFILE_EXCLUSIVE_LOCK is a true shared lock.
        flags = 1 | (0 if shared else 2)
        if not lock(msvcrt.get_osfhandle(self._file.fileno()), flags, 0, 1, 0, ctypes.byref(self._overlapped)):
            code = ctypes.get_last_error()
            if code in (32, 33):  # sharing/lock violation
                raise RuntimeLeaseBusy()
            raise ctypes.WinError(code)

    def close(self) -> None:
        if self._file.closed:
            return
        try:
            if sys.platform == "win32":
                import ctypes
                from ctypes import wintypes
                import msvcrt
                unlock = ctypes.WinDLL("kernel32", use_last_error=True).UnlockFileEx
                unlock.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.DWORD, ctypes.c_void_p]
                unlock.restype = wintypes.BOOL
                unlock(msvcrt.get_osfhandle(self._file.fileno()), 0, 1, 0, ctypes.byref(self._overlapped))
            else:
                import fcntl
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()

    def __enter__(self) -> RuntimeLease:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def runtime_read_lease() -> RuntimeLease:
    return RuntimeLease(shared=True)


def runtime_write_lease() -> RuntimeLease:
    return RuntimeLease(shared=False)
