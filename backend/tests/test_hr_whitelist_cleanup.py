"""Unit tests for HR whitelist cleanup helpers (no database)."""

from uuid import uuid4

from app.services.hr_whitelist_cleanup import normalize_hr_email, parse_keep_lines


def test_normalize_email():
    assert normalize_hr_email("  HR@Example.COM ") == "hr@example.com"


def test_parse_keep_lines():
    u = str(uuid4())
    assert parse_keep_lines(["# x", "", " a@b.com ", u]) == ["a@b.com", u]
