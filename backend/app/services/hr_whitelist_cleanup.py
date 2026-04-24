"""
HR whitelist cleanup: resolve explicit keep tokens (email / UUID) plus optional
anchor HRs linked to configured \"real\" students (same defaults as student whitelist).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable
from uuid import UUID

from sqlalchemy import not_
from sqlalchemy.orm import Session

# Optional built-in explicit HR keeps (emails). Usually empty — prefer student anchor + --keep-emails.
DEFAULT_HR_KEEP_EMAILS: tuple[str, ...] = ()


def normalize_hr_email(email: str) -> str:
    return (email or "").strip().lower()


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
    return list(dict.fromkeys(out))


def load_explicit_hr_keep_tokens(
    *,
    use_builtin_hr_emails: bool,
    keep_file: str | None,
    keep_emails: str | None,
) -> list[str]:
    tokens: list[str] = []
    if use_builtin_hr_emails:
        tokens.extend(DEFAULT_HR_KEEP_EMAILS)
    if keep_file:
        from pathlib import Path

        raw = Path(keep_file).read_text(encoding="utf-8")
        tokens.extend(parse_keep_lines(raw.splitlines()))
    if keep_emails:
        for part in keep_emails.replace(";", ",").split(","):
            p = part.strip()
            if p:
                tokens.append(p)
    return list(dict.fromkeys(tokens))


def hr_ids_for_student_outreach(db: Session, student_ids: set[UUID]) -> set[UUID]:
    """Distinct HR ids appearing in assignments, email campaigns, or responses for given students."""
    from app.models import Assignment, EmailCampaign, Response

    if not student_ids:
        return set()
    out: set[UUID] = set()
    ids = list(student_ids)
    for i in range(0, len(ids), 400):
        chunk = ids[i : i + 400]
        out |= {r[0] for r in db.query(Assignment.hr_id).filter(Assignment.student_id.in_(chunk)).distinct().all()}
        out |= {r[0] for r in db.query(EmailCampaign.hr_id).filter(EmailCampaign.student_id.in_(chunk)).distinct().all()}
        out |= {r[0] for r in db.query(Response.hr_id).filter(Response.student_id.in_(chunk)).distinct().all()}
    return out


def _fuzzy_email_suggest(db: Session, token: str, *, limit: int = 12) -> list[tuple[UUID, str, str, str]]:
    from app.models import HRContact

    nt = normalize_hr_email(token)
    if len(nt) < 4:
        return []
    hits = db.query(HRContact).filter(HRContact.email.ilike(f"%{nt}%")).limit(limit).all()
    return [(h.id, h.email, h.name, h.company) for h in hits]


@dataclass
class HRKeepResolution:
    keep_hr_ids: set[UUID] = field(default_factory=set)
    keep_hrs: list[tuple[UUID, str, str, str]] = field(default_factory=list)  # id, email, name, company
    anchor_hr_ids: set[UUID] = field(default_factory=set)
    explicit_hr_ids: set[UUID] = field(default_factory=set)
    anchor_student_ids: set[UUID] = field(default_factory=set)
    unmatched_explicit_tokens: list[str] = field(default_factory=list)
    fuzzy_suggestions: dict[str, list[tuple[UUID, str, str, str]]] = field(default_factory=dict)

    @property
    def ok_to_apply(self) -> bool:
        return not self.unmatched_explicit_tokens and bool(self.keep_hr_ids)


def resolve_keep_hrs(
    db: Session,
    *,
    explicit_tokens: list[str],
    anchor_student_ids: set[UUID],
) -> HRKeepResolution:
    from app.models import HRContact

    out = HRKeepResolution()
    out.anchor_student_ids = set(anchor_student_ids)
    out.anchor_hr_ids = hr_ids_for_student_outreach(db, anchor_student_ids) if anchor_student_ids else set()

    by_email: dict[str, HRContact] = {}
    for h in db.query(HRContact).all():
        by_email[normalize_hr_email(h.email)] = h

    explicit_ids: set[UUID] = set()
    for token in explicit_tokens:
        t = token.strip()
        if not t:
            continue
        if _is_uuid_token(t):
            hid = UUID(t)
            row = db.query(HRContact).filter(HRContact.id == hid).first()
            if not row:
                out.unmatched_explicit_tokens.append(t)
                out.fuzzy_suggestions[t] = []
            else:
                explicit_ids.add(row.id)
            continue

        key = normalize_hr_email(t)
        row = by_email.get(key)
        if not row:
            out.unmatched_explicit_tokens.append(t)
            out.fuzzy_suggestions[t] = _fuzzy_email_suggest(db, t)
        else:
            explicit_ids.add(row.id)

    out.explicit_hr_ids = set(explicit_ids)
    out.keep_hr_ids = set(out.anchor_hr_ids) | set(explicit_ids)

    seen: set[UUID] = set()
    for hid in sorted(out.keep_hr_ids, key=str):
        h = db.query(HRContact).filter(HRContact.id == hid).first()
        if h and h.id not in seen:
            seen.add(h.id)
            out.keep_hrs.append((h.id, h.email, h.name, h.company))
    out.keep_hrs.sort(key=lambda x: normalize_hr_email(x[1]))
    return out


def hrs_to_remove(db: Session, keep_hr_ids: set[UUID]) -> list[tuple[UUID, str, str, str]]:
    from app.models import HRContact

    if not keep_hr_ids:
        return []
    rows = db.query(HRContact).filter(not_(HRContact.id.in_(keep_hr_ids))).all()
    return [(r.id, r.email, r.name, r.company) for r in rows]
