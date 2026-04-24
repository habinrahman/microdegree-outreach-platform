"""
Export JSONL snapshots for operator recovery (students / HR / campaigns / email sends).

  python -m app.scripts.export_operator_snapshot --out ./exports/snapshot_20260101

Secrets (app_password, refresh tokens) are omitted.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")
            n += 1
    return n


def _student_public_dict(s: Any) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "name": s.name,
        "gmail_address": s.gmail_address,
        "experience_years": int(s.experience_years or 0),
        "skills": s.skills,
        "resume_drive_file_id": s.resume_drive_file_id,
        "resume_file_name": s.resume_file_name,
        "resume_path": s.resume_path,
        "domain": s.domain,
        "linkedin_url": s.linkedin_url,
        "gmail_connected": bool(s.gmail_connected),
        "status": s.status,
        "email_health_status": getattr(s, "email_health_status", None),
        "is_demo": bool(getattr(s, "is_demo", False)),
        "is_fixture_test_data": bool(getattr(s, "is_fixture_test_data", False)),
        "emails_sent_today": int(getattr(s, "emails_sent_today", 0) or 0),
        "last_sent_at": s.last_sent_at.isoformat() if s.last_sent_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def _hr_public_dict(h: Any) -> dict[str, Any]:
    return {c.name: getattr(h, c.name) for c in h.__table__.columns}


def _campaign_dict(c: Any) -> dict[str, Any]:
    return {col.name: getattr(c, col.name) for col in c.__table__.columns}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(description="Export operator JSONL snapshots (no secrets).")
    p.add_argument("--out", type=str, required=True, help="Output directory (created).")
    args = p.parse_args(argv)

    try:
        from app.database.config import SessionLocal
        from app.models import Campaign, EmailCampaign, HRContact, Student
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    root = Path(args.out).resolve()
    root.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        sn = _write_jsonl(root / "students.jsonl", (_student_public_dict(s) for s in db.query(Student).all()))
        hn = _write_jsonl(root / "hr_contacts.jsonl", (_hr_public_dict(h) for h in db.query(HRContact).all()))
        cn = _write_jsonl(root / "campaigns.jsonl", (_campaign_dict(c) for c in db.query(Campaign).all()))
        en = _write_jsonl(root / "email_campaigns.jsonl", (_campaign_dict(e) for e in db.query(EmailCampaign).all()))
        manifest = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "counts": {
                "students": sn,
                "hr_contacts": hn,
                "campaigns": cn,
                "email_campaigns": en,
            },
            "note": "Secrets omitted from students export. Restore full credentials from secure vault / OAuth re-link.",
        }
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=2))
        return 0
    except Exception:
        logger.exception("export failed")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
