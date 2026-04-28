"""Reply export helpers (CSV-safe, fixed schema)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, TextIO

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models import EmailCampaign, HRContact, Student
from app.services.export_normalization import normalize_export_cell


REPLY_EXPORT_COLUMNS: list[str] = [
    "student_name",
    "company",
    "hr_email",
    "campaign_id",
    "subject",
    "status",
    "email_type",
    "reply_status",
    "reply_preview_truncated",
    "reply_preview",
    "reply_received_at",
    "reply_detected_at",
    "sequence_number",
    "outbound_message_id",
    "sent_at",
    "reply_from_header",
    "suppression_reason",
    "terminal_outcome",
    "audit_notes",
]


def write_reply_export_csv(fp: TextIO, rows: Iterable[dict[str, Any]]) -> int:
    """
    Strict CSV writer:
    - uses DictWriter (no manual CSV building)
    - fixed column ordering
    - always writes every column (missing keys -> blank)
    """
    w = csv.DictWriter(
        fp,
        fieldnames=REPLY_EXPORT_COLUMNS,
        extrasaction="ignore",
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\n",
    )
    w.writeheader()
    n = 0
    for r in rows:
        # Ensure rectangular output even if upstream forgot a key.
        out = {k: normalize_export_cell(r.get(k)) for k in REPLY_EXPORT_COLUMNS}
        w.writerow(out)
        n += 1
    return n


def _has_inbound_reply_body() -> Any:
    return or_(
        and_(EmailCampaign.reply_text.isnot(None), func.length(func.trim(EmailCampaign.reply_text)) > 0),
        and_(EmailCampaign.reply_snippet.isnot(None), func.length(func.trim(EmailCampaign.reply_snippet)) > 0),
    )


def _reply_export_predicate() -> Any:
    normalized_reply = and_(
        EmailCampaign.reply_status.isnot(None),
        EmailCampaign.reply_status.notin_(("BOUNCED", "BLOCKED", "TEMP_FAIL", "BOUNCE")),
        _has_inbound_reply_body(),
    )
    legacy_reply = and_(
        EmailCampaign.reply_status.is_(None),
        EmailCampaign.status == "replied",
        EmailCampaign.replied.is_(True),
        _has_inbound_reply_body(),
    )
    return and_(
        or_(EmailCampaign.replied.is_(True), EmailCampaign.status == "replied"),
        or_(normalized_reply, legacy_reply),
    )


def _audit_notes(c: EmailCampaign) -> str:
    parts = [
        f"status={c.status or ''}",
        f"delivery={c.delivery_status or ''}",
        f"failure_type={c.failure_type or ''}",
    ]
    err = normalize_export_cell(c.error or "", max_len=400)
    if err:
        parts.append(f"error={err}")
    return normalize_export_cell(" | ".join(parts), max_len=1500)


def iter_reply_export_rows(db: Session, *, include_demo: bool = False, limit: int = 5000) -> Iterable[dict[str, Any]]:
    """
    Generator of normalized dict rows for CSV export.
    Deduped by EmailCampaign.id.
    """
    pred = _reply_export_predicate()
    q = (
        db.query(EmailCampaign, Student, HRContact)
        .join(Student, EmailCampaign.student_id == Student.id)
        .join(HRContact, EmailCampaign.hr_id == HRContact.id)
        .filter(pred)
    )
    if not include_demo:
        q = q.filter(Student.is_demo.is_(False), HRContact.is_demo.is_(False))

    rows = q.order_by(
        func.coalesce(EmailCampaign.reply_received_at, EmailCampaign.replied_at, EmailCampaign.reply_detected_at).desc().nullslast(),
        EmailCampaign.created_at.desc(),
    ).limit(int(limit)).all()

    seen: set[str] = set()
    for c, st, hr in rows:
        cid = str(c.id)
        if cid in seen:
            continue
        seen.add(cid)

        raw = c.reply_text or c.reply_snippet or ""
        preview = normalize_export_cell(raw, max_len=2000)
        preview_trunc = normalize_export_cell(raw, max_len=300)
        yield {
            "student_name": st.name,
            "company": hr.company,
            "hr_email": hr.email,
            "campaign_id": cid,
            "subject": normalize_export_cell(c.subject or "", max_len=500),
            "status": c.status or "",
            "email_type": c.email_type or "",
            "reply_status": c.reply_status or "",
            "reply_preview_truncated": preview_trunc,
            "reply_preview": preview,
            "reply_received_at": c.reply_received_at or c.replied_at or "",
            "reply_detected_at": c.reply_detected_at or "",
            "sequence_number": c.sequence_number or "",
            "outbound_message_id": c.message_id or "",
            "sent_at": c.sent_at or "",
            "reply_from_header": normalize_export_cell(c.reply_from or "", max_len=500),
            "suppression_reason": normalize_export_cell(c.suppression_reason or "", max_len=500),
            "terminal_outcome": normalize_export_cell(c.terminal_outcome or "", max_len=64),
            "audit_notes": _audit_notes(c),
        }

