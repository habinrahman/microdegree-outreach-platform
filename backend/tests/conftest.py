"""Pytest hooks — isolated DB + test profile before any ``app`` imports."""

import os

import pytest
from sqlalchemy import text

os.environ["PYTEST_RUNNING"] = "1"
os.environ["APP_ENV"] = "test"
os.environ["ENVIRONMENT"] = "test"
os.environ["ENV"] = "test"

if (os.environ.get("TEST_DATABASE_URL") or "").strip():
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"].strip()
else:
    os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"


def pytest_sessionstart(session):
    from app.database.config import init_db

    init_db()


@pytest.fixture(autouse=True)
def _reset_shared_in_memory_sqlite():
    """StaticPool in-memory SQLite is process-wide; clear rows between tests."""
    from app.database.config import DATABASE_URL, Base, engine

    if ":memory:" not in (DATABASE_URL or ""):
        yield
        return
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = OFF"))
        for tbl in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f'DELETE FROM "{tbl.name}"'))
        conn.execute(text("PRAGMA foreign_keys = ON"))
    yield
