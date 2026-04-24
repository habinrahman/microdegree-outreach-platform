"""Gmail API inbox monitor — disabled.

Reply detection uses IMAP + Message-ID matching in ``app.services.reply_tracker``.
This module keeps ``run_gmail_monitor_job`` so the scheduler and admin routes keep working.
"""


def run_gmail_monitor_job(*, max_students: int = 25, max_history: int = 50) -> dict:
    """No-op: Gmail API / OAuth are not used in SMTP+IMAP mode."""
    return {
        "ok": True,
        "skipped": True,
        "reason": "gmail_api_disabled",
        "students_scanned": 0,
        "replies_recorded": 0,
        "errors": [],
    }
