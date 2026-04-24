"""Google Sheets mirror access (service account).

Environment:
- ``GOOGLE_SHEETS_SPREADSHEET_ID`` (required): spreadsheet document ID from the Sheet URL.
- ``GOOGLE_SHEETS_CREDENTIALS_PATH`` (optional): path to service account JSON. If unset,
  ``GOOGLE_APPLICATION_CREDENTIALS`` is used when set; otherwise defaults to ``credentials.json``
  in the process working directory (typically ``backend/``).
"""

from __future__ import annotations

import os
from pathlib import Path

import gspread
from oauth2client.service_account import ServiceAccountCredentials

_BLOCKED_TAB_TITLE = "Blocked HRs"

_TAB_DEFAULTS: dict[str, tuple[int, int]] = {
    "Replies": (3000, 12),
    "Failures": (3000, 12),
    "Bounces": (2000, 12),
    _BLOCKED_TAB_TITLE: (2000, 6),
}


def _spreadsheet_id() -> str:
    sid = (os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID") or "").strip()
    if not sid:
        raise RuntimeError(
            "GOOGLE_SHEETS_SPREADSHEET_ID is not set. "
            "Set it to your Google Sheet document ID (from the URL). "
            "Do not commit credentials or IDs you consider private—use env / secrets manager."
        )
    return sid


def _credentials_path() -> str:
    raw = (
        (os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH") or "").strip()
        or (os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
        or "credentials.json"
    )
    return raw if raw else "credentials.json"


def _authorize_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    path = Path(_credentials_path())
    if not path.is_file():
        raise FileNotFoundError(
            f"Google Sheets service account file not found: {path.resolve()}. "
            "Set GOOGLE_SHEETS_CREDENTIALS_PATH or GOOGLE_APPLICATION_CREDENTIALS, "
            "or place credentials.json in the working directory."
        )
    creds = ServiceAccountCredentials.from_json_keyfile_name(str(path), scope)
    return gspread.authorize(creds)


def _open_spreadsheet():
    return _authorize_client().open_by_key(_spreadsheet_id())


def open_spreadsheet():
    """Return the configured gspread Spreadsheet (single workbook for multi-tab operations)."""
    return _open_spreadsheet()


def get_worksheet(title: str, *, rows: int | None = None, cols: int | None = None):
    """Open or create a worksheet by title (used for exports)."""
    ss = _open_spreadsheet()
    r, c = _TAB_DEFAULTS.get(title, (2000, 10))
    if rows is not None:
        r = rows
    if cols is not None:
        c = cols
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows=r, cols=c)
        return ws


def get_sheet(tab_title: str | None = None):
    """
    Spreadsheet access. Pass tab title for named tabs; default uses first sheet
    for backward compatibility with legacy callers.
    """
    if tab_title:
        return get_worksheet(tab_title)
    return _open_spreadsheet().sheet1


def get_blocked_sheet():
    """Second tab for blocked / bounced HR emails (created if missing)."""
    return get_worksheet(_BLOCKED_TAB_TITLE)
