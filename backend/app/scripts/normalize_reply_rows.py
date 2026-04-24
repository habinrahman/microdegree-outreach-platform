"""
Normalize reply data on ``email_campaigns`` (body in ``reply_text``; API concept: reply_message).

* Cleans threads / quoted blocks
* Overwrites ``reply_status`` with canonical labels (no INITIAL)
* Never deletes rows; optional ``--dry-run`` skips commit

Run from backend root::

    python -m app.scripts.normalize_reply_rows
    python -m app.scripts.normalize_reply_rows --dry-run
    python -m app.scripts.normalize_reply_rows --limit 500

Verify::

    SELECT DISTINCT reply_status FROM email_campaigns;
    -- expect: INTERESTED, INTERVIEW, REJECTED, AUTO_REPLY, BOUNCE, OOO, UNKNOWN, OTHER
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from app.database.config import SessionLocal
from app.models.email_campaign import EmailCampaign
from app.services.reply_utils import clean_reply, classify_reply

logger = logging.getLogger(__name__)


def normalize_row(c: EmailCampaign) -> bool:
    """
    Apply clean + classify. Maps logical reply_message → ORM ``reply_text``.
    Returns True if any field changed.
    """
    raw = c.reply_text if c.reply_text is not None else ""
    cleaned = clean_reply(raw)
    rtype = classify_reply(cleaned)

    snippet = cleaned[:500]

    changed = False
    if c.reply_text != cleaned:
        c.reply_text = cleaned
        changed = True
    if c.reply_status != rtype:
        c.reply_status = rtype
        changed = True
    if c.replied is not True:
        c.replied = True
        changed = True
    if c.reply_snippet != snippet:
        c.reply_snippet = snippet
        changed = True
    return changed


def run(*, dry_run: bool, limit: int | None) -> dict[str, int]:
    db = SessionLocal()
    stats = {"scanned": 0, "updated": 0, "errors": 0}
    try:
        q = db.query(EmailCampaign).filter(EmailCampaign.status == "replied")
        if limit is not None:
            q = q.limit(limit)
        rows = q.all()

        for c in rows:
            stats["scanned"] += 1
            try:
                if normalize_row(c):
                    stats["updated"] += 1
                    if not dry_run:
                        db.add(c)
            except Exception:
                stats["errors"] += 1
                logger.exception("Failed to normalize campaign id=%s", c.id)

        if dry_run:
            db.rollback()
            logger.info("Dry-run: rolled back; no changes committed.")
        elif stats["updated"]:
            db.commit()
            logger.info("Committed %s updated row(s).", stats["updated"])
        else:
            db.commit()

    finally:
        db.close()

    logger.info(
        "normalize_reply_rows finished: scanned=%s updated=%s errors=%s dry_run=%s",
        stats["scanned"],
        stats["updated"],
        stats["errors"],
        dry_run,
    )
    return stats


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    p = argparse.ArgumentParser(
        description="Clean and standardize reply fields on EmailCampaign (status=replied only)."
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute changes but do not commit.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N rows (for testing).",
    )
    args = p.parse_args()

    logger.info(
        "Starting normalize_reply_rows dry_run=%s limit=%r",
        args.dry_run,
        args.limit,
    )
    stats = run(dry_run=args.dry_run, limit=args.limit)
    # Human-readable summary on stdout
    print(
        {
            "scanned": stats["scanned"],
            "updated": stats["updated"],
            "errors": stats["errors"],
            "dry_run": args.dry_run,
        }
    )
    print("Done at", datetime.now(timezone.utc).isoformat())
    print("Verify: SELECT DISTINCT reply_status FROM email_campaigns;")


if __name__ == "__main__":
    main()
