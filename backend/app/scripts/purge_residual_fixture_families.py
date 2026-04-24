"""
Targeted purge for residual synthetic fixture families (preview-first, idempotent apply).

Safety:
- Selects only rows with ``is_fixture_test_data`` **or** ``email_matches_blocked_fixture_taxonomy``.
- Never deletes rows that fail both checks (imported leads).

Usage:
  python -m app.scripts.purge_residual_fixture_families --audit
  python -m app.scripts.purge_residual_fixture_families --dry-run
  python -m app.scripts.purge_residual_fixture_families --apply --i-understand
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from sqlalchemy.orm import Session

from app.database.config import SessionLocal
from app.scripts.cleanup_demo_data import CleanupPreview, run_delete
from app.scripts.cleanup_test_fixture_pollution import _build_preview
from app.services.fixture_residual_purge import (
    build_extended_audit,
    candidates_to_serializable,
    hr_purge_reasons,
    list_purge_candidates,
    post_purge_integrity_audit,
    hr_is_purge_candidate,
    student_is_purge_candidate,
    student_purge_reasons,
)

logger = logging.getLogger(__name__)


def _scan_preview(db: Session) -> CleanupPreview:
    from app.models import HRContact, Student

    s_ids: list = []
    h_ids: list = []
    sr: dict[str, list[str]] = {}
    hr: dict[str, list[str]] = {}
    for s in db.query(Student).all():
        if student_is_purge_candidate(s):
            s_ids.append(s.id)
            sr[str(s.id)] = student_purge_reasons(s)
    for h in db.query(HRContact).all():
        if hr_is_purge_candidate(h):
            h_ids.append(h.id)
            hr[str(h.id)] = hr_purge_reasons(h)
    return _build_preview(db, s_ids, h_ids, sr, hr)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audit", action="store_true", help="Full extended audit JSON (read-only).")
    p.add_argument("--dry-run", action="store_true", help="Explicit dry-run flag (optional; default without --apply).")
    p.add_argument("--apply", action="store_true", help="Perform deletion.")
    p.add_argument("--i-understand", action="store_true", help="Required with --apply.")
    args = p.parse_args(argv)

    if args.apply and not args.i_understand:
        print("Refusing --apply without --i-understand", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        if args.audit:
            print(json.dumps(build_extended_audit(db), indent=2, default=str))
            return 0

        audit = build_extended_audit(db)
        cands = list_purge_candidates(db)
        preview = _scan_preview(db)

        print("=== Residual fixture purge (preview) ===")
        print(
            json.dumps(
                {
                    "extended_audit": audit,
                    "purge_candidates": candidates_to_serializable(cands),
                    "preview_counts": {
                        "student_ids": len(preview.student_ids),
                        "hr_ids": len(preview.hr_ids),
                        "assignments": preview.assignment_count,
                        "email_campaigns": preview.email_campaign_count,
                        "responses": preview.response_count,
                    },
                },
                indent=2,
                default=str,
            )
        )

        if not args.apply:
            print("\nDry run only. Pass --apply --i-understand to delete.")
            return 0

        run_delete(db, preview, clean_blocked_hrs=False, clean_audit_logs=False)
        db.commit()

        integrity = post_purge_integrity_audit(db)
        print("\n=== POST-PURGE INTEGRITY ===")
        print(json.dumps(integrity, indent=2, default=str))
        if not integrity.get("audit_ok"):
            print("WARNING: integrity audit did not pass cleanly.", file=sys.stderr)
            return 3
        print("\nApply completed; integrity OK.")
        return 0
    except Exception:
        db.rollback()
        logger.exception("purge_residual_fixture_families failed")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
