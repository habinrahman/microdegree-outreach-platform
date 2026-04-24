"""Tests for ``fixture_column_bootstrap`` (SQLite + verify-only)."""

from __future__ import annotations

from app.database.config import engine
from app.database.fixture_column_bootstrap import ensure_fixture_columns_bootstrap, verify_fixture_columns


def test_verify_fixture_columns_sqlite_reports_presence():
    v = verify_fixture_columns(engine)
    assert v["dialect"].startswith("sqlite")
    assert v.get("fixture_columns_present") is True


def test_ensure_fixture_columns_idempotent_on_sqlite():
    ensure_fixture_columns_bootstrap(engine, verify_only=False, strict=True)
    r2 = ensure_fixture_columns_bootstrap(engine, verify_only=False, strict=True)
    assert r2.get("changed") is False
    assert verify_fixture_columns(engine).get("fixture_columns_present") is True


def test_verify_only_mode_returns_without_ddl():
    out = ensure_fixture_columns_bootstrap(engine, verify_only=True, strict=True)
    assert out.get("verify_only") is True
    assert out.get("changed") is False
