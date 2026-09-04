"""Canonical stable component keys shared by Research and Create."""

from __future__ import annotations


_SUPPORT_METADATA_PREFIXES = (
    "Metadata/Items/Gem/",
    "Metadata/Items/Gems/",
)


def canonical_support_component_key(metadata_id: str) -> str:
    """Return a Support stable key while preserving the complete Metadata path."""

    metadata = str(metadata_id or "").strip()
    if metadata.startswith("support:"):
        metadata = metadata.removeprefix("support:")
    if not any(
        metadata.startswith(prefix) and len(metadata) > len(prefix)
        for prefix in _SUPPORT_METADATA_PREFIXES
    ):
        raise ValueError("support metadata id must contain a complete Metadata item path")
    return f"support:{metadata}"
