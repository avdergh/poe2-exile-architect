"""Read only the local documents reachable through a published skill's links."""

from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


def read_skill_documents(skill_dir: Path) -> dict[str, str]:
    root = skill_dir.resolve()
    documents: dict[str, str] = {}

    def visit(path: Path) -> None:
        resolved = path.resolve()
        relative = resolved.relative_to(root).as_posix()
        if relative in documents:
            return
        text = resolved.read_text(encoding="utf-8")
        documents[relative] = text
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            parsed = urlsplit(target)
            if parsed.scheme or not parsed.path:
                continue
            linked = resolved.parent / unquote(parsed.path)
            assert linked.is_file(), f"Broken skill link in {relative}: {target}"
            if linked.suffix.lower() == ".md":
                visit(linked)

    visit(root / "SKILL.md")
    return documents
