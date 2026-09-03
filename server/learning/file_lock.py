"""Compatibility re-export for the shared runtime file lock."""

from server.runtime.file_lock import interprocess_file_lock

__all__ = ["interprocess_file_lock"]
