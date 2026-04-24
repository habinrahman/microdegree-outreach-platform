"""Append new BlockedHR rows to the spreadsheet tab (no duplicate exports)."""

import logging

from sqlalchemy.orm import Session

from app.models import BlockedHR
from app.services.google_sheets import get_blocked_sheet
from app.services.sheet_sync import append_rows_batched_with_retry

logger = logging.getLogger(__name__)


def remove_blocked_email_from_sheet(email: str) -> int:
    """
    Delete rows on the Blocked HRs tab whose first column matches email (case-insensitive).
    Returns number of rows removed. Does not change the DB.
    """
    target = (email or "").strip().lower()
    if not target:
        return 0
    sheet = get_blocked_sheet()
    rows = sheet.get_all_values()
    to_delete: list[int] = []
    for i, row in enumerate(rows, start=1):
        if not row:
            continue
        cell = (row[0] or "").strip().lower()
        if cell == target:
            to_delete.append(i)
    removed = 0
    for row_idx in sorted(to_delete, reverse=True):
        try:
            sheet.delete_rows(row_idx)
            removed += 1
        except Exception:
            logger.exception("blocked sheet: failed to delete row %s for %s", row_idx, email)
    if removed:
        logger.info("blocked sheet: removed %s row(s) for %s", removed, email)
    return removed


def sync_blocked_hrs(db: Session) -> None:
    sheet = get_blocked_sheet()

    rows = (
        db.query(BlockedHR)
        .filter(BlockedHR.exported_to_sheet.is_(False))
        .all()
    )

    if rows:
        batch = [
            [
                r.email,
                r.company or "",
                r.reason or "bounce",
                str(r.created_at) if r.created_at else "",
            ]
            for r in rows
        ]
        logger.info("blocked_hr_sync: exporting %s row(s) (batched append + retry)", len(batch))
        append_rows_batched_with_retry(sheet, batch)
        for r in rows:
            r.exported_to_sheet = True
            db.add(r)

    db.commit()
