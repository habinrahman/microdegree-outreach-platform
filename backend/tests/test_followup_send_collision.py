"""
Race simulation for manual follow-up send claim.

We validate the same atomic UPDATE pattern used by POST /followups/send:
only one session can transition pending|scheduled -> processing for a given row.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.database.config import SessionLocal, engine
from app.models import Assignment, EmailCampaign, HRContact, Student


def _utc_naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def test_second_claim_fails_after_first_claim_serial():
    """Any dialect: after one successful claim, a second claim must update 0 rows."""
    db0 = SessionLocal()
    try:
        st = Student(
            id=uuid.uuid4(),
            name="S2",
            gmail_address="s2@example.com",
            app_password="x",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr = HRContact(
            id=uuid.uuid4(),
            name="H2",
            company="C",
            email="h2@example.com",
            status="active",
            is_valid=True,
            is_demo=False,
            is_fixture_test_data=True,
        )
        db0.add(st)
        db0.add(hr)
        db0.commit()
        db0.add(Assignment(student_id=st.id, hr_id=hr.id, status="active"))
        db0.commit()

        c = EmailCampaign(
            student_id=st.id,
            hr_id=hr.id,
            sequence_number=2,
            email_type="followup_1",
            scheduled_at=_utc_naive(datetime.now(timezone.utc)),
            status="scheduled",
            subject="fu1",
            body="b",
        )
        db0.add(c)
        db0.commit()
        db0.refresh(c)
        cid = c.id
    finally:
        db0.close()

    def claim() -> int:
        db = SessionLocal()
        try:
            now_claim = datetime.now(timezone.utc).replace(tzinfo=None)
            n = (
                db.execute(
                    text(
                        """
                        UPDATE email_campaigns
                        SET status = 'processing',
                            processing_started_at = :ts,
                            processing_lock_acquired_at = :ts
                        WHERE id = :id
                          AND status IN ('pending', 'scheduled')
                        """
                    ),
                    {"id": str(cid), "ts": now_claim},
                ).rowcount
            )
            db.commit()
            return int(n or 0)
        finally:
            db.close()

    assert claim() == 1
    assert claim() == 0


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="True concurrent claim race validated on Postgres; serial test above covers all dialects.",
)
def test_two_operators_cannot_claim_same_followup_row():
    db0 = SessionLocal()
    try:
        st = Student(
            id=uuid.uuid4(),
            name="S",
            gmail_address="s@example.com",
            app_password="x",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr = HRContact(
            id=uuid.uuid4(),
            name="H",
            company="C",
            email="h@example.com",
            status="active",
            is_valid=True,
            is_demo=False,
            is_fixture_test_data=True,
        )
        db0.add(st)
        db0.add(hr)
        db0.commit()

        db0.add(Assignment(student_id=st.id, hr_id=hr.id, status="active"))
        db0.commit()

        c = EmailCampaign(
            student_id=st.id,
            hr_id=hr.id,
            sequence_number=2,
            email_type="followup_1",
            scheduled_at=_utc_naive(datetime.now(timezone.utc)),
            status="scheduled",
            subject="fu1",
            body="b",
        )
        db0.add(c)
        db0.commit()
        db0.refresh(c)
        cid = c.id
    finally:
        db0.close()

    barrier = threading.Barrier(2)
    results: dict[str, int] = {}

    def worker(name: str):
        db = SessionLocal()
        try:
            barrier.wait()
            now_claim = datetime.now(timezone.utc).replace(tzinfo=None)
            n = (
                db.execute(
                    text(
                        """
                        UPDATE email_campaigns
                        SET status = 'processing',
                            processing_started_at = :ts,
                            processing_lock_acquired_at = :ts
                        WHERE id = :id
                          AND status IN ('pending', 'scheduled')
                        """
                    ),
                    {"id": str(cid), "ts": now_claim},
                ).rowcount
            )
            db.commit()
            results[name] = int(n or 0)
        finally:
            db.close()

    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert sorted(results.values()) == [0, 1]

    dbv = SessionLocal()
    try:
        row = dbv.execute(
            text("SELECT status FROM email_campaigns WHERE id = :id"),
            {"id": str(cid)},
        ).scalar()
        assert str(row).lower() == "processing"
    finally:
        dbv.close()
