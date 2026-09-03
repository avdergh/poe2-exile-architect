"""Skill-equivalence matching layer for Build Family identity.

Deterministic equivalence comes from bundled gem data (display name -> internal skill id,
and one gem granting multiple skill variants such as ammunition/direct-hit pairs). Model-
confirmed extra equivalences (renames, cross-version aliases) are persisted in the
``skill_equivalence`` table. Fuzzy candidates are a separate residual channel; nothing here
authorizes semantic edges or knowledge writes on its own.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

_RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
_SKILLS_FILE = _RAW_DIR / "skills.min.json"
_GEMS_FILE = _RAW_DIR / "skill_gems.min.json"

_ROMAN_SUFFIX = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5"}

_EQUIVALENCE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS skill_equivalence (
    key_a TEXT NOT NULL,
    key_b TEXT NOT NULL,
    method TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    game_patch TEXT,
    status TEXT NOT NULL DEFAULT 'valid',
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (key_a, key_b)
);
"""


_ROMAN_TOKEN = re.compile(r"^[ivx]+$")


def normalize_name(name: str) -> str:
    """Normalize a skill display name for deterministic comparison.

    Strips whitespace/punctuation, lowercases, and folds standalone roman version
    tokens (``II`` -> ``2``) so ``Magnified Area II`` and ``magnified area 2`` compare
    equal. Only whole-word tokens are folded; roman letters inside a word (``Explosive``)
    are left untouched.
    """
    text = str(name or "").strip().lower()
    words = [re.sub(r"[\s\-_'’/()\[\].,:;]+", "", word) for word in re.split(r"\s+", text)]
    parts: list[str] = []
    for word in words:
        if not word:
            continue
        if _ROMAN_TOKEN.fullmatch(word):
            parts.append(_ROMAN_SUFFIX.get(word, word))
        else:
            parts.append(word)
    return "".join(parts)


def _load_json(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _load_gems_from_corpus() -> dict[str, dict[str, Any]]:
    """Rebuild the identity subset from the packaged corpus when raw RePoE files are absent."""

    try:
        from . import db

        rows = db._conn().execute("SELECT id, name, grants FROM gems").fetchall()
    except Exception:
        return {}
    payload: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            grants = json.loads(row["grants"] or "[]")
        except (TypeError, ValueError):
            grants = []
        payload[str(row["id"])] = {
            "base_item": {"display_name": str(row["name"] or "")},
            "grants_skills": grants if isinstance(grants, list) else [],
        }
    return payload


class SkillEquivalenceIndex:
    """Deterministic display-name -> skill-id index over bundled gem data."""

    _CACHE: "SkillEquivalenceIndex | None" = None

    def __init__(self, *, raw_dir: Path | None = None) -> None:
        self._raw_dir = Path(raw_dir) if raw_dir is not None else _RAW_DIR
        self._skills: dict[str, dict] | None = None
        self._gems: dict[str, dict] | None = None
        self._skill_to_gem_name: dict[str, str] | None = None
        self._skill_to_gem_ids: dict[str, list[str]] | None = None
        self._gem_grants: dict[str, list[str]] | None = None
        self._gem_ids_by_name: dict[str, list[str]] | None = None
        self._display_by_skill: dict[str, str] | None = None

    @classmethod
    def shared(cls) -> "SkillEquivalenceIndex":
        if cls._CACHE is None:
            cls._CACHE = cls()
        return cls._CACHE

    def _ensure_index(self) -> None:
        if self._skills is not None:
            return
        self._skills = _load_json(self._raw_dir / "skills.min.json")
        self._gems = _load_json(self._raw_dir / "skill_gems.min.json")
        if not self._gems:
            self._gems = _load_gems_from_corpus()
        skill_to_gem: dict[str, str] = {}
        skill_to_gem_ids: dict[str, list[str]] = {}
        gem_grants: dict[str, list[str]] = {}
        gem_ids_by_name: dict[str, list[str]] = {}
        for gem_id, gem in self._gems.items():
            display = str((gem.get("base_item") or {}).get("display_name") or "").strip()
            if not display:
                continue
            gem_ids_by_name.setdefault(normalize_name(display), []).append(str(gem_id))
            grants = [str(item) for item in (gem.get("grants_skills") or []) if str(item)]
            if not grants:
                continue
            gem_grants.setdefault(display, []).extend(grants)
            for skill_id in grants:
                skill_to_gem.setdefault(skill_id, display)
                skill_to_gem_ids.setdefault(skill_id, []).append(str(gem_id))
        self._skill_to_gem_name = skill_to_gem
        self._skill_to_gem_ids = {
            name: sorted(set(items)) for name, items in skill_to_gem_ids.items()
        }
        self._gem_grants = {name: sorted(set(items)) for name, items in gem_grants.items()}
        self._gem_ids_by_name = {
            name: sorted(set(items)) for name, items in gem_ids_by_name.items()
        }

    def gem_ids(self, gem_name: str) -> tuple[str, ...]:
        """Return metadata ids for one exact normalized gem display name."""

        self._ensure_index()
        return tuple((self._gem_ids_by_name or {}).get(normalize_name(gem_name), ()))

    def gem_ids_for_skill_key(self, skill_key: str) -> tuple[str, ...]:
        """Return metadata ids of gems that grant one active-skill key."""

        self._ensure_index()
        skill_id = self._strip_prefix(skill_key)
        return tuple((self._skill_to_gem_ids or {}).get(skill_id, ()))

    def display_name(self, skill_key: str) -> str:
        self._ensure_index()
        skill_id = self._strip_prefix(skill_key)
        item = self._skills.get(skill_id)
        if item is not None:
            display = str((item.get("active_skill") or {}).get("display_name") or "").strip()
            if display:
                return display
        return skill_id

    def gem_name(self, skill_key: str) -> str | None:
        self._ensure_index()
        return self._skill_to_gem_name.get(self._strip_prefix(skill_key))

    def canonical_key(self, skill_key: str) -> str:
        """Return the canonical token for a skill key.

        Prefers the granting gem's display name (so ammunition/direct-hit variants of one
        gem compare equal), falls back to the skill display name, then the key itself.
        """
        if not skill_key or not skill_key.startswith("skill:"):
            return normalize_name(skill_key)
        self._ensure_index()
        gem_name = self.gem_name(skill_key)
        if gem_name:
            return "gem:" + normalize_name(gem_name)
        display = self.display_name(skill_key)
        if display and display != self._strip_prefix(skill_key):
            return "skill:" + normalize_name(display)
        return "key:" + normalize_name(skill_key)

    def equivalent_keys(self, skill_key: str) -> frozenset[str]:
        """Return all skill keys deterministically equivalent to ``skill_key``.

        The equivalence class is the set of skills granted by the same gem (e.g.
        ``ExplosiveShotAmmoPlayer`` and ``ExplosiveShotPlayer`` both come from the
        ``Explosive Shot`` gem). Without a gem match the class contains only the key.
        """
        if not skill_key.startswith("skill:"):
            return frozenset({skill_key})
        self._ensure_index()
        gem_name = self.gem_name(skill_key)
        if gem_name is None:
            return frozenset({skill_key})
        granted = self._gem_grants.get(gem_name) or []
        return frozenset({"skill:" + item for item in granted if item})

    def canonical_set(self, skill_keys: Iterable[str]) -> frozenset[str]:
        """Canonical-normalize a set of skill keys for identity comparison."""
        return frozenset({self.canonical_key(key) for key in skill_keys})

    def display_names_by_skill(self) -> dict[str, str]:
        """Map skill ids (without ``skill:`` prefix) to their display names.

        Built lazily once and cached on the shared index (the skills payload has ~48k
        entries, so rebuilding per query is wasteful).
        """
        self._ensure_index()
        if self._display_by_skill is None:
            self._display_by_skill = {
                skill_id: str((item.get("active_skill") or {}).get("display_name") or "").strip()
                for skill_id, item in self._skills.items()
                if str((item.get("active_skill") or {}).get("display_name") or "").strip()
            }
        return self._display_by_skill

    def granted_skills_by_gem(self) -> dict[str, list[str]]:
        """Map gem display names to the list of skill ids they grant."""
        self._ensure_index()
        return dict(self._gem_grants or {})

    @staticmethod
    def _strip_prefix(skill_key: str) -> str:
        return skill_key.split(":", 1)[-1] if skill_key.startswith("skill:") else skill_key


def canonical_identity_set(
    con: Any,
    skill_keys: Iterable[str],
    *,
    index: SkillEquivalenceIndex | None = None,
) -> frozenset[str]:
    """Apply the existing deterministic and accepted model equivalences to one skill set."""

    idx = index or SkillEquivalenceIndex.shared()
    canon = idx.canonical_set(skill_keys)
    if not canon:
        return canon
    rows = con.execute(
        "SELECT key_a, key_b FROM skill_equivalence WHERE status = 'valid'"
    ).fetchall()
    if not rows:
        return canon
    parent: dict[str, str] = {}

    def find(token: str) -> str:
        while parent.get(token, token) != token:
            token = parent[token]
        return token

    def union(a: str, b: str) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)

    for key_a, key_b in rows:
        token_a = idx.canonical_key(str(key_a))
        token_b = idx.canonical_key(str(key_b))
        if token_a.startswith("key:") or token_b.startswith("key:"):
            continue
        union(token_a, token_b)
    return frozenset({find(token) for token in canon})


class ModelEquivalenceStore:
    """Persisted model-confirmed skill equivalences (renames, cross-version aliases)."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = db_path

    def _connect(self):
        from . import mature_learning

        path = self._db_path or mature_learning.mature_learning_path()
        con = mature_learning.connect(path)
        con.execute(_EQUIVALENCE_SCHEMA_SQL)
        con.commit()
        return con

    def add_equivalence(
        self,
        *,
        key_a: str,
        key_b: str,
        method: str = "model_review",
        rationale: str = "",
        game_patch: str | None = None,
        now: str | None = None,
    ) -> None:
        from datetime import datetime, timezone

        ts = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
        con = self._connect()
        try:
            con.execute(
                """
                INSERT INTO skill_equivalence(
                    key_a, key_b, method, rationale, game_patch, status, created_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, 'valid', ?, ?)
                ON CONFLICT(key_a, key_b) DO UPDATE SET
                    method = excluded.method,
                    rationale = excluded.rationale,
                    status = 'valid',
                    last_seen_at = excluded.last_seen_at
                """,
                (key_a, key_b, method, rationale, game_patch, ts, ts),
            )
            con.commit()
        finally:
            con.close()

    def valid_pairs(self) -> list[tuple[str, str]]:
        con = self._connect()
        try:
            rows = con.execute(
                "SELECT key_a, key_b FROM skill_equivalence WHERE status = 'valid'"
            ).fetchall()
            return [(str(a), str(b)) for a, b in rows]
        finally:
            con.close()
