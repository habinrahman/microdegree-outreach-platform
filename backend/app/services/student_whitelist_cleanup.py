"""
Whitelist-based student retention for safe purge of non-production students.

Matching: normalized display name (case-insensitive, collapsed whitespace) or UUID.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import not_
from sqlalchemy.orm import Session

# Default production students to KEEP (all others may be removed by the cleanup script).
DEFAULT_STUDENT_KEEP_NAMES: tuple[str, ...] = (
    "Manikantaraju",
    "Mallik Arjun",
    "Prathiksha",
    "Malhar Ashrit",
    "Rohit Patil",
    "Sumanth Hebbar",
    "Rakshit V",
    "Murali kumar s",
    "Lavanya AS",
    "Nagaraj Badiger",
)


def normalize_student_name(name: str) -> str:
    """Single canonical form for name equality (not for fuzzy suggestions)."""
    s = (name or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _is_uuid_token(token: str) -> bool:
    t = token.strip()
    if len(t) != 36:
        return False
    try:
        UUID(t)
    except ValueError:
        return False
    return True


def parse_keep_lines(lines: Iterable[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return out


def load_keep_tokens(
    *,
    use_builtin_defaults: bool,
    keep_file: str | None,
    keep_names: str | None,
) -> list[str]:
    """Merge ordered keep tokens from defaults, optional file, and comma-separated names."""
    tokens: list[str] = []
    if use_builtin_defaults:
        tokens.extend(DEFAULT_STUDENT_KEEP_NAMES)
    if keep_file:
        from pathlib import Path

        raw = Path(keep_file).read_text(encoding="utf-8")
        tokens.extend(parse_keep_lines(raw.splitlines()))
    if keep_names:
        for part in keep_names.replace(";", ",").split(","):
            p = part.strip()
            if p:
                tokens.append(p)
    return tokens


@dataclass
class KeepResolution:
    """Result of resolving keep tokens against ``students`` rows."""

    keep_student_ids: set[UUID] = field(default_factory=set)
    keep_students: list[tuple[UUID, str, str]] = field(default_factory=list)  # id, name, gmail
    unmatched_tokens: list[str] = field(default_factory=list)
    ambiguous_tokens: dict[str, list[tuple[UUID, str, str]]] = field(default_factory=dict)
    # token -> suggested students (weak match) when token had zero exact matches
    fuzzy_suggestions: dict[str, list[tuple[UUID, str, str]]] = field(default_factory=dict)

    @property
    def ok_to_apply(self) -> bool:
        return not self.unmatched_tokens and not self.ambiguous_tokens and bool(self.keep_student_ids)


def resolve_keep_students(db: Session, tokens: list[str]) -> KeepResolution:
    from app.models import Student

    out = KeepResolution()
    seen_ids: set[UUID] = set()
    students = db.query(Student).all()
    by_norm: dict[str, list[Student]] = {}
    for s in students:
        k = normalize_student_name(s.name)
        by_norm.setdefault(k, []).append(s)

    for token in tokens:
        t = token.strip()
        if not t:
            continue
        if _is_uuid_token(t):
            sid = UUID(t)
            row = db.query(Student).filter(Student.id == sid).first()
            if not row:
                out.unmatched_tokens.append(t)
                continue
            if row.id not in seen_ids:
                seen_ids.add(row.id)
                out.keep_student_ids.add(row.id)
                out.keep_students.append((row.id, row.name, row.gmail_address))
            continue

        key = normalize_student_name(t)
        hits = by_norm.get(key, [])
        if len(hits) == 0:
            out.unmatched_tokens.append(t)
            out.fuzzy_suggestions[t] = _fuzzy_suggest_students(students, t)
        elif len(hits) > 1:
            out.ambiguous_tokens[t] = [(h.id, h.name, h.gmail_address) for h in hits]
        else:
            h = hits[0]
            if h.id not in seen_ids:
                seen_ids.add(h.id)
                out.keep_student_ids.add(h.id)
                out.keep_students.append((h.id, h.name, h.gmail_address))

    out.keep_students.sort(key=lambda x: normalize_student_name(x[1]))
    return out


def _fuzzy_suggest_students(students: list[Any], token: str, *, min_sub: int = 4) -> list[tuple[UUID, str, str]]:
    """Weak hints for typos / partial names (preview only)."""
    nt = normalize_student_name(token)
    if len(nt) < min_sub:
        return []
    sug: list[tuple[UUID, str, str]] = []
    for s in students:
        ns = normalize_student_name(s.name)
        if nt in ns or ns in nt:
            sug.append((s.id, s.name, s.gmail_address))
    return sug[:15]


def students_to_remove(db: Session, keep_ids: set[UUID]) -> list[tuple[UUID, str, str]]:
    from app.models import Student

    if not keep_ids:
        return []
    rows = db.query(Student).filter(not_(Student.id.in_(keep_ids))).all()
    return [(r.id, r.name, r.gmail_address) for r in rows]
