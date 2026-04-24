import gspread
from oauth2client.service_account import ServiceAccountCredentials

_SPREADSHEET_KEY = "18IqQHoeDPomovXUBXZXPh4ybHSBg67Mx33t0fZN5Vh0"
_BLOCKED_TAB_TITLE = "Blocked HRs"

_TAB_DEFAULTS: dict[str, tuple[int, int]] = {
    "Replies": (3000, 12),
    "Failures": (3000, 12),
    "Bounces": (2000, 12),
    _BLOCKED_TAB_TITLE: (2000, 6),
}


def _authorize_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        "credentials.json",
        scope,
    )
    return gspread.authorize(creds)


def _open_spreadsheet():
    return _authorize_client().open_by_key(_SPREADSHEET_KEY)


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
