"""Unit tests for whitelist student cleanup helpers (no database)."""

from uuid import uuid4

from app.services.student_whitelist_cleanup import (
    DEFAULT_STUDENT_KEEP_NAMES,
    normalize_student_name,
    parse_keep_lines,
)


def test_normalize_collapses_space_and_case():
    assert normalize_student_name("  Mallik   Arjun  ") == "mallik arjun"
    assert normalize_student_name("Lavanya AS") == "lavanya as"


def test_default_keep_list_nonempty():
    assert len(DEFAULT_STUDENT_KEEP_NAMES) >= 10
    assert "Nagaraj Badiger" in DEFAULT_STUDENT_KEEP_NAMES


def test_parse_keep_lines_skips_comments_and_blank():
    raw = """
# header
Manikantaraju

Prathiksha
""".splitlines()
    assert parse_keep_lines(raw) == ["Manikantaraju", "Prathiksha"]


def test_uuid_token_length():
    u = str(uuid4())
    assert len(u) == 36
