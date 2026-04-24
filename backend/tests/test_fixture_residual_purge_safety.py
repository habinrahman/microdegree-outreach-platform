"""Safety checks for residual fixture purge planning."""

from __future__ import annotations

import uuid

from app.database.config import SessionLocal
from app.models import Student
from app.services.fixture_residual_purge import student_is_purge_candidate


def test_imported_like_student_without_tag_or_taxonomy_not_purge_candidate():
    db = SessionLocal()
    try:
        st = Student(
            id=uuid.uuid4(),
            name="Acme Lead",
            gmail_address=f"recruiter.{uuid.uuid4().hex[:8]}@acme.com",
            app_password="x",
            status="active",
            is_demo=False,
            is_fixture_test_data=False,
        )
        db.add(st)
        db.commit()
        assert student_is_purge_candidate(st) is False
    finally:
        db.close()
