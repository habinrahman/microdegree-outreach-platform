"""Regression: pytest must not use the dev DB; fixture emails must not flush outside test runtimes."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def test_pytest_pins_isolated_database_url():
    assert os.environ.get("PYTEST_RUNNING") == "1"
    url = (os.environ.get("DATABASE_URL") or "").lower()
    explicit = (os.environ.get("TEST_DATABASE_URL") or "").strip()
    if explicit:
        assert url == explicit.lower()
    else:
        assert "sqlite" in url and ":memory:" in url


def test_fixture_prefix_flush_rejected_when_not_test_runtime(monkeypatch):
    monkeypatch.delenv("PYTEST_RUNNING", raising=False)
    for k in ("APP_ENV", "ENVIRONMENT", "ENV"):
        monkeypatch.setenv(k, "development")

    from app.database.config import Base
    from app.models import Student
    from app.database.fixture_email_guard import email_matches_blocked_fixture_taxonomy

    assert email_matches_blocked_fixture_taxonomy("inv_deadbeef@gmail.com") is True

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()
    try:
        db.add(
            Student(
                id=uuid.uuid4(),
                name="X",
                gmail_address="inv_deadbeef@gmail.com",
                app_password="x",
                status="active",
                is_demo=False,
                is_fixture_test_data=True,
            )
        )
        with pytest.raises(ValueError, match="Refusing to persist"):
            db.commit()
    finally:
        db.close()
