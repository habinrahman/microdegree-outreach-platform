"""
Synthetic HR audit + CI fixture regression (SQLite in-memory, no DATABASE_URL).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database.config import Base
from app.models import Assignment, Campaign, EmailCampaign, HRContact, Student
from app.services.synthetic_hr_audit import (
    count_orphan_assignments,
    count_synthetic_hr_contacts,
    run_synthetic_hr_audit,
)
from app.services.synthetic_hr_cleanup import is_synthetic_hr


@pytest.fixture()
def memory_db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    db = S()
    try:
        yield db
    finally:
        db.close()
        eng.dispose()


def test_ci_safe_hr_profiles_json_never_synthetic() -> None:
    """Curated CI-safe HR profiles must remain non-synthetic (regression guard)."""
    path = Path(__file__).resolve().parent / "fixtures" / "ci_safe_hr_profiles.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for row in data:
        if "email" not in row:
            continue
        assert not is_synthetic_hr(
            email=row["email"],
            name=row.get("name", "N"),
            company=row.get("company", "C"),
        ), row


def test_fixture_db_starts_clean(memory_db):
    st = Student(
        id=uuid4(),
        name="Fixture Student",
        gmail_address="fixture.student@example.com",
        app_password="pw",
        status="active",
        is_demo=False,
        is_fixture_test_data=True,
    )
    hr = HRContact(
        id=uuid4(),
        name="Fixture Recruiter",
        company="Example Corp",
        email="fixture.recruiter@example.com",
        status="active",
        is_valid=True,
        is_demo=False,
        is_fixture_test_data=True,
    )
    memory_db.add_all([st, hr])
    memory_db.commit()
    memory_db.add(Assignment(student_id=st.id, hr_id=hr.id, status="active"))
    memory_db.commit()

    assert count_synthetic_hr_contacts(memory_db) == 0
    audit = run_synthetic_hr_audit(memory_db)
    assert audit.ok


def test_synthetic_hr_detected(memory_db):
    st = Student(
        id=uuid4(),
        name="Sam",
        gmail_address="s@example.com",
        app_password="pw",
        status="active",
        is_demo=False,
        is_fixture_test_data=True,
    )
    hr_good = HRContact(
        id=uuid4(),
        name="Good HR",
        company="RealCo",
        email="good@example.com",
        status="active",
        is_valid=True,
        is_demo=False,
        is_fixture_test_data=True,
    )
    hr_syn = HRContact(
        id=uuid4(),
        name="Seed",
        company="Talkdesk",
        email="tb0_seed@talkdesk.com",
        status="active",
        is_valid=True,
        is_demo=False,
        is_fixture_test_data=True,
    )
    memory_db.add_all([st, hr_good, hr_syn])
    memory_db.commit()
    memory_db.add(Assignment(student_id=st.id, hr_id=hr_good.id, status="active"))
    memory_db.add(Assignment(student_id=st.id, hr_id=hr_syn.id, status="active"))
    memory_db.commit()

    assert count_synthetic_hr_contacts(memory_db) == 1
    assert count_orphan_assignments(memory_db) == 0


def test_orphan_assignment_detected_when_hr_row_missing(memory_db):
    """Simulate a dangling assignment (FK not enforced for this row) to test the audit query."""
    st = Student(
        id=uuid4(),
        name="Pat",
        gmail_address="pat@example.com",
        app_password="pw",
        status="active",
        is_demo=False,
        is_fixture_test_data=True,
    )
    memory_db.add(st)
    memory_db.commit()
    ghost_hr = uuid4()
    aid = uuid4()
    memory_db.execute(text("PRAGMA foreign_keys = OFF"))
    memory_db.execute(
        text(
            "INSERT INTO assignments (id, student_id, hr_id, status) "
            "VALUES (:id, :sid, :hid, 'active')"
        ),
        {"id": str(aid), "sid": str(st.id), "hid": str(ghost_hr)},
    )
    memory_db.execute(text("PRAGMA foreign_keys = ON"))
    memory_db.commit()
    assert count_orphan_assignments(memory_db) == 1


def test_orphan_campaign_missing_student(memory_db):
    st_id = uuid4()
    camp = Campaign(id=uuid4(), name="Orphan camp", student_id=st_id, status="running")
    memory_db.add(camp)
    memory_db.commit()
    audit = run_synthetic_hr_audit(memory_db)
    assert audit.orphan_campaigns_missing_student == 1


def test_email_campaign_broken_campaign_fk(memory_db):
    st = Student(
        id=uuid4(),
        name="Sid",
        gmail_address="s2@example.com",
        app_password="pw",
        status="active",
        is_demo=False,
        is_fixture_test_data=True,
    )
    hr = HRContact(
        id=uuid4(),
        name="H",
        company="RealCo",
        email="h2@example.com",
        status="active",
        is_valid=True,
        is_demo=False,
        is_fixture_test_data=True,
    )
    memory_db.add_all([st, hr])
    memory_db.commit()
    fake_cid = uuid4()
    memory_db.add(
        EmailCampaign(
            student_id=st.id,
            hr_id=hr.id,
            campaign_id=fake_cid,
            sequence_number=1,
            email_type="initial",
            scheduled_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status="pending",
        )
    )
    memory_db.commit()
    audit = run_synthetic_hr_audit(memory_db)
    assert audit.email_campaigns_broken_campaign_fk == 1
