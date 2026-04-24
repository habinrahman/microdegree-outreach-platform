"""
Backfill missing EmailCampaign.thread_id for already-sent campaigns.

If EmailCampaign.status == "sent" and thread_id is NULL but message_id exists,
set thread_id = message_id. This enables reply matching logic that relies on
EmailCampaign.thread_id.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

from app.database.config import SessionLocal
from app.models import EmailCampaign


def main() -> None:
    db = SessionLocal()
    try:
        q = (
            db.query(EmailCampaign)
            .filter(EmailCampaign.status == "sent")
            .filter(EmailCampaign.thread_id.is_(None))
            .filter(EmailCampaign.message_id.isnot(None))
        )
        rows = q.all()
        for c in rows:
            c.thread_id = c.message_id
        if rows:
            db.commit()
        print(f"Backfilled thread_id for {len(rows)} EmailCampaign rows.")
    finally:
        db.close()


if __name__ == "__main__":
    main()

