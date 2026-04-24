"""
Post-remediation verification: cleanup removes every blocked-prefix synthetic row
and leaves no orphan assignments / email_campaigns / responses.

Uses the same isolated DB as the rest of the suite (see tests/conftest.py).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.database.config import SessionLocal
from app.database.fixture_email_guard import (
    ALWAYS_BLOCKED_SYNTHETIC_EMAIL_LOCAL_PREFIXES,
    DISPOSABLE_DOMAIN_BLOCKED_LOCAL_PREFIXES,
)
from app.models import Assignment, EmailCampaign, HRContact, Student
from app.scripts.cleanup_test_fixture_pollution import (
    _build_preview,
    _scan_fixture_targets,
    build_fixture_pollution_audit_report,
)
from app.scripts.cleanup_demo_data import run_delete


def _naive_utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_cleanup_removes_all_prefix_variants_and_preserves_control_rows():
    db = SessionLocal()
    try:
        uid = uuid.uuid4().hex[:12]
        prefixes = (*ALWAYS_BLOCKED_SYNTHETIC_EMAIL_LOCAL_PREFIXES, *DISPOSABLE_DOMAIN_BLOCKED_LOCAL_PREFIXES)
        synthetic_pairs: list[tuple[Student, HRContact]] = []
        for p in prefixes:
            st = Student(
                id=uuid.uuid4(),
                name="Synth",
                gmail_address=f"{p}audit_{uid}@example.com",
                app_password="x",
                status="active",
                is_demo=False,
                is_fixture_test_data=True,
            )
            hr = HRContact(
                id=uuid.uuid4(),
                name="SynthHR",
                company="Co",
                email=f"{p}audit_h_{uid}@example.com",
                status="active",
                is_valid=True,
                is_demo=False,
                is_fixture_test_data=True,
            )
            db.add(st)
            db.add(hr)
            synthetic_pairs.append((st, hr))

        keep_st = Student(
            id=uuid.uuid4(),
            name="Real",
            gmail_address=f"real_keep_{uid}@example.com",
            app_password="x",
            status="active",
            is_demo=False,
            is_fixture_test_data=False,
        )
        keep_hr = HRContact(
            id=uuid.uuid4(),
            name="RealHR",
            company="Co",
            email=f"real_keep_h_{uid}@example.com",
            status="active",
            is_valid=True,
            is_demo=False,
            is_fixture_test_data=False,
        )
        db.add(keep_st)
        db.add(keep_hr)
        db.commit()

        for st, hr in synthetic_pairs:
            a = Assignment(student_id=st.id, hr_id=hr.id, status="active")
            db.add(a)
            db.add(
                EmailCampaign(
                    student_id=st.id,
                    hr_id=hr.id,
                    sequence_number=1,
                    email_type="initial",
                    scheduled_at=_naive_utc_now(),
                    status="scheduled",
                    subject="s",
                    body="b",
                )
            )
        db.commit()

        before = build_fixture_pollution_audit_report(db)
        assert before["synthetic_students_total"] == len(prefixes)
        assert before["synthetic_hr_contacts_total"] == len(prefixes)
        for p in prefixes:
            assert before["synthetic_students_by_prefix"][p] == 1
            assert before["synthetic_hr_contacts_by_prefix"][p] == 1
        assert before["orphan_assignments"] == 0
        assert before["orphan_email_campaigns"] == 0

        s_ids, h_ids, sr, hr_r = _scan_fixture_targets(db)
        preview = _build_preview(db, s_ids, h_ids, sr, hr_r)
        run_delete(db, preview, clean_blocked_hrs=False, clean_audit_logs=False)
        db.commit()

        after = build_fixture_pollution_audit_report(db)
        assert after["synthetic_students_total"] == 0
        assert after["synthetic_hr_contacts_total"] == 0
        for p in prefixes:
            assert after["synthetic_students_by_prefix"][p] == 0
            assert after["synthetic_hr_contacts_by_prefix"][p] == 0
        assert after["orphan_assignments"] == 0
        assert after["orphan_email_campaigns"] == 0
        assert after["orphan_responses"] == 0

        assert db.query(Student).filter(Student.id == keep_st.id).count() == 1
        assert db.query(HRContact).filter(HRContact.id == keep_hr.id).count() == 1
    finally:
        db.close()


def test_representative_leak_pattern_tests_run_under_pytest_sqlite_memory():
    """Guarantee conftest still pins DATABASE_URL for SessionLocal-based tests."""
    import os

    assert os.environ.get("PYTEST_RUNNING") == "1"
    url = (os.environ.get("DATABASE_URL") or "").lower()
    if (os.environ.get("TEST_DATABASE_URL") or "").strip():
        assert "postgresql" in url or "postgres" in url
    else:
        assert "sqlite" in url and ":memory:" in url
