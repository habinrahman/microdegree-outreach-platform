from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_last_trigger_at_utc: str | None = None


def trigger_sheet_sync_async(*, reason: str) -> None:
    """
    Fire-and-forget Google Sheets sync.

    Why: `sync_new_replies()` can block (network + retries + sleeps). This helper ensures we never
    block API request handlers or SMTP send hot paths waiting for Sheets.
    """

    def _run() -> None:
        from app.database.config import SessionLocal
        from app.services.sheet_sync import sync_new_replies

        db = SessionLocal()
        try:
            sync_new_replies(db)
        except Exception:
            logger.warning("sheet_sync async failed reason=%s", reason, exc_info=True)
        finally:
            db.close()

    global _last_trigger_at_utc
    _last_trigger_at_utc = datetime.now(timezone.utc).isoformat()
    try:
        t = threading.Thread(target=_run, name="sheet-sync", daemon=True)
        t.start()
    except Exception:
        logger.warning("sheet_sync async spawn failed reason=%s", reason, exc_info=True)


def sheet_sync_trigger_status() -> dict:
    return {"last_trigger_at_utc": _last_trigger_at_utc}

