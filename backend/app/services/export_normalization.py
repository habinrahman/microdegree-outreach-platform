"""Export hardening: sanitize cells for Sheets/CSV so data stays rectangular."""

from __future__ import annotations

import re
from typing import Any

_WS_RE = re.compile(r"\s+")


def normalize_export_cell(value: Any, *, max_len: int | None = None) -> str:
    """
    Spreadsheet/CSV-safe scalar.

    - None -> ""
    - Newlines/tabs -> spaces
    - Collapse repeated whitespace
    - Trim
    - Optional truncation
    """
    if value is None:
        s = ""
    else:
        s = str(value)

    if not s:
        return ""

    # Prevent row breaks / column drift in CSV/Sheets exports.
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").replace("\t", " ")
    s = _WS_RE.sub(" ", s).strip()
    if max_len is not None and max_len > 0 and len(s) > max_len:
        s = s[: max_len]
    return s


def normalize_export_row(cells: list[Any], *, expected_len: int) -> list[str]:
    """
    Force fixed schema: identical ordered columns per row.
    Extra cells are dropped; missing cells are padded with blanks.
    """
    row = [normalize_export_cell(v) for v in (cells or [])]
    if len(row) < expected_len:
        row = row + [""] * (expected_len - len(row))
    elif len(row) > expected_len:
        row = row[:expected_len]
    return row

