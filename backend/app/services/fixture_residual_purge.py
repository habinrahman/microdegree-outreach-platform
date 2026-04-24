"""
Residual fixture purge planning, auditing, and post-delete integrity checks.

Safety model (preview-first):
- A row is a purge **candidate** only if ``is_fixture_test_data`` is true **or**
  ``email_matches_blocked_fixture_taxonomy`` is true for its email field.
- Rows matching neither are never selected (imported leads must not be touched).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.database.fixture_email_guard import (
    ALWAYS_BLOCKED_SYNTHETIC_EMAIL_LOCAL_PREFIXES,
    DISPOSABLE_DOMAIN_BLOCKED_LOCAL_PREFIXES,
    email_matches_blocked_fixture_taxonomy,
)
from app.scripts.cleanup_test_fixture_pollution import (
    _build_preview,
    build_fixture_pollution_audit_report,
)


def _all_prefixes_ordered() -> tuple[str, ...]:
    merged = (*ALWAYS_BLOCKED_SYNTHETIC_EMAIL_LOCAL_PREFIXES, *DISPOSABLE_DOMAIN_BLOCKED_LOCAL_PREFIXES)
    return tuple(sorted(merged, key=len, reverse=True))


def longest_fixture_prefix_for_local(local: str) -> str | None:
    lp = local.strip().lower()
    for p in _all_prefixes_ordered():
        if lp.startswith(p):
            return p
    return None


def student_purge_reasons(s) -> list[str]:
    rs: list[str] = []
    if getattr(s, "is_fixture_test_data", False):
        rs.append("fixture_tag")
    if email_matches_blocked_fixture_taxonomy(s.gmail_address):
        rs.append("email_taxonomy")
    return rs


def hr_purge_reasons(h) -> list[str]:
    rs: list[str] = []
    if getattr(h, "is_fixture_test_data", False):
        rs.append("fixture_tag")
    if email_matches_blocked_fixture_taxonomy(h.email):
        rs.append("email_taxonomy")
    return rs


def student_is_purge_candidate(s) -> bool:
    return bool(student_purge_reasons(s))


def hr_is_purge_candidate(h) -> bool:
    return bool(hr_purge_reasons(h))


@dataclass
class FixturePurgeCandidate:
    kind: str  # student | hr_contact
    id: UUID
    email: str
    reasons: list[str]
    prefix_bucket: str | None


def list_purge_candidates(db: Session) -> list[FixturePurgeCandidate]:
    from app.models import HRContact, Student

    out: list[FixturePurgeCandidate] = []
    for s in db.query(Student).all():
        reasons = student_purge_reasons(s)
        if not reasons:
            continue
        local = (s.gmail_address or "").split("@", 1)[0] if "@" in (s.gmail_address or "") else ""
        out.append(
            FixturePurgeCandidate(
                kind="student",
                id=s.id,
                email=str(s.gmail_address),
                reasons=reasons,
                prefix_bucket=longest_fixture_prefix_for_local(local),
            )
        )
    for h in db.query(HRContact).all():
        reasons = hr_purge_reasons(h)
        if not reasons:
            continue
        local = (h.email or "").split("@", 1)[0] if "@" in (h.email or "") else ""
        out.append(
            FixturePurgeCandidate(
                kind="hr_contact",
                id=h.id,
                email=str(h.email),
                reasons=reasons,
                prefix_bucket=longest_fixture_prefix_for_local(local),
            )
        )
    return out


def count_tagged_fixture_rows(db: Session) -> dict[str, int]:
    from app.models import HRContact, Student

    st = sum(1 for s in db.query(Student).all() if getattr(s, "is_fixture_test_data", False))
    hr = sum(1 for h in db.query(HRContact).all() if getattr(h, "is_fixture_test_data", False))
    return {"tagged_students": st, "tagged_hr_contacts": hr}


def rows_by_fixture_prefix(db: Session) -> dict[str, dict[str, int]]:
    """Counts by longest matching prefix bucket (students + HRs separately)."""
    from app.models import HRContact, Student

    prefixes = _all_prefixes_ordered()
    st_counts = {p: 0 for p in prefixes}
    hr_counts = {p: 0 for p in prefixes}
    st_other = 0
    hr_other = 0

    for s in db.query(Student).all():
        if not student_is_purge_candidate(s):
            continue
        local = (s.gmail_address or "").split("@", 1)[0] if "@" in (s.gmail_address or "") else ""
        b = longest_fixture_prefix_for_local(local)
        if b and b in st_counts:
            st_counts[b] += 1
        else:
            st_other += 1

    for h in db.query(HRContact).all():
        if not hr_is_purge_candidate(h):
            continue
        local = (h.email or "").split("@", 1)[0] if "@" in (h.email or "") else ""
        b = longest_fixture_prefix_for_local(local)
        if b and b in hr_counts:
            hr_counts[b] += 1
        else:
            hr_other += 1

    return {
        "students_by_prefix": {**st_counts, "_tag_only_or_exact_no_prefix_bucket": st_other},
        "hr_contacts_by_prefix": {**hr_counts, "_tag_only_or_exact_no_prefix_bucket": hr_other},
    }


def build_extended_audit(db: Session) -> dict[str, Any]:
    base = build_fixture_pollution_audit_report(db)
    tagged = count_tagged_fixture_rows(db)
    prefix_rows = rows_by_fixture_prefix(db)
    cands = list_purge_candidates(db)
    preview = _build_preview(
        db,
        [c.id for c in cands if c.kind == "student"],
        [c.id for c in cands if c.kind == "hr_contact"],
        {str(c.id): c.reasons for c in cands if c.kind == "student"},
        {str(c.id): c.reasons for c in cands if c.kind == "hr_contact"},
    )
    safety = {
        "candidates_total": len(cands),
        "taxonomy_only_candidates": sum(1 for c in cands if c.reasons == ["email_taxonomy"]),
        "tag_only_candidates": sum(1 for c in cands if c.reasons == ["fixture_tag"]),
        "both_reasons": sum(1 for c in cands if len(c.reasons) > 1),
        "longest_prefix_matching": True,
    }
    return {
        "base_pollution_audit": base,
        "tagged_fixture_rows": tagged,
        "purge_candidates_by_prefix": prefix_rows,
        "projected_deletions": {
            "student_ids": len(preview.student_ids),
            "hr_ids": len(preview.hr_ids),
            "linked_assignments": preview.assignment_count,
            "linked_email_campaigns": preview.email_campaign_count,
            "linked_responses": preview.response_count,
            "orphan_campaign_entities": len(preview.orphan_campaign_ids),
        },
        "safety_summary": safety,
    }


def post_purge_integrity_audit(db: Session) -> dict[str, Any]:
    base = build_fixture_pollution_audit_report(db)
    tagged = count_tagged_fixture_rows(db)
    cands = list_purge_candidates(db)
    audit_ok = (
        base["synthetic_students_total"] == 0
        and base["synthetic_hr_contacts_total"] == 0
        and base["orphan_assignments"] == 0
        and base["orphan_email_campaigns"] == 0
        and base["orphan_responses"] == 0
        and tagged["tagged_students"] == 0
        and tagged["tagged_hr_contacts"] == 0
        and len(cands) == 0
    )
    return {"audit_ok": audit_ok, "pollution": base, "tagged_fixture_rows": tagged, "remaining_candidates": len(cands)}


def candidates_to_serializable(cands: list[FixturePurgeCandidate]) -> list[dict[str, Any]]:
    return [
        {
            "kind": c.kind,
            "id": str(c.id),
            "email": c.email,
            "reasons": c.reasons,
            "prefix_bucket": c.prefix_bucket,
        }
        for c in cands
    ]
