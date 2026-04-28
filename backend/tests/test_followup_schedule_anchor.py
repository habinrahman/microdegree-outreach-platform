from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.database.config import SessionLocal
from app.models import Assignment, EmailCampaign, HRContact, Student
from app.services.sequence_service import ensure_four_step_campaign_rows, reschedule_followups_from_initial_sent
from app.services.sequence_send_gate import scheduler_may_send_campaign


def _utc_naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def pair_db():
    db = SessionLocal()
    uid = uuid.uuid4().hex[:10]
    st = Student(
        id=uuid.uuid4(),
        name="S",
        gmail_address=f"s_anchor_{uid}@example.com",
        app_password="x",
        status="active",
        is_demo=False,
        is_fixture_test_data=True,
    )
    hr = HRContact(
        id=uuid.uuid4(),
        name="H",
        company="C",
        email=f"h_anchor_{uid}@example.com",
        status="active",
        is_valid=True,
        is_demo=False,
        is_fixture_test_data=True,
    )
    db.add(st)
    db.add(hr)
    db.commit()
    a = Assignment(student_id=st.id, hr_id=hr.id, status="active")
    db.add(a)
    db.commit()
    db.refresh(a)
    yield db, st, hr, a
    db.close()


def test_initial_delayed_send_reschedules_followups_exactly_from_sent_at(pair_db):
    """
    Launch-blocking regression: follow-ups must anchor to initial.sent_at, not row creation.
    """
    db, st, hr, a = pair_db
    # Campaign rows were created far in the past (simulating early assignment).
    creation_anchor = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    ensure_four_step_campaign_rows(db, a, anchor=creation_anchor)

    # Initial is actually sent much later (e.g., scheduler downtime / operator delay).
    initial_sent = datetime(2026, 2, 10, 10, 0, 0, tzinfo=timezone.utc)
    initial = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id, EmailCampaign.sequence_number == 1)
        .first()
    )
    initial.status = "sent"
    initial.sent_at = _utc_naive(initial_sent)
    db.add(initial)
    db.commit()

    reschedule_followups_from_initial_sent(db, student_id=st.id, hr_id=hr.id, initial_sent_at=initial.sent_at)

    fu1 = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id, EmailCampaign.sequence_number == 2)
        .first()
    )
    fu2 = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id, EmailCampaign.sequence_number == 3)
        .first()
    )
    fu3 = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id, EmailCampaign.sequence_number == 4)
        .first()
    )
    base = _utc_naive(initial_sent)
    assert fu1.scheduled_at == base + timedelta(days=7)
    assert fu2.scheduled_at == base + timedelta(days=14)
    assert fu3.scheduled_at == base + timedelta(days=21)


def test_reply_suppression_rows_never_mutate(pair_db):
    db, st, hr, a = pair_db
    ensure_four_step_campaign_rows(db, a, anchor=datetime(2026, 1, 1, tzinfo=timezone.utc))
    # Simulate cancellation from reply suppression
    fu1 = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id, EmailCampaign.sequence_number == 2)
        .first()
    )
    old = fu1.scheduled_at
    fu1.status = "cancelled"
    db.add(fu1)
    db.commit()

    reschedule_followups_from_initial_sent(
        db,
        student_id=st.id,
        hr_id=hr.id,
        initial_sent_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    db.refresh(fu1)
    assert fu1.scheduled_at == old


def test_outage_catchup_due_followup_becomes_sendable_after_reschedule(pair_db):
    """
    Scheduler-down scenario: if initial was sent 10 days ago, FU1 should be due now.
    We don't run SMTP; we prove scheduler gate would allow it (when follow-ups enabled + dispatch on).
    """
    db, st, hr, a = pair_db
    ensure_four_step_campaign_rows(db, a, anchor=datetime(2026, 1, 1, tzinfo=timezone.utc))
    initial_sent = datetime.now(timezone.utc) - timedelta(days=10)
    base = _utc_naive(initial_sent)

    initial = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id, EmailCampaign.sequence_number == 1)
        .first()
    )
    initial.status = "sent"
    initial.sent_at = base
    db.add(initial)

    fu1 = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id, EmailCampaign.sequence_number == 2)
        .first()
    )
    fu1.status = "scheduled"
    db.add(fu1)
    db.commit()

    reschedule_followups_from_initial_sent(db, student_id=st.id, hr_id=hr.id, initial_sent_at=base)
    db.refresh(fu1)
    assert fu1.scheduled_at <= _utc_naive(datetime.now(timezone.utc))

    # Gate: patch follow-ups enabled + dispatch enabled.
    from unittest.mock import patch

    with patch("app.services.sequence_send_gate.FOLLOWUPS_ENABLED", True), patch(
        "app.services.sequence_send_gate.get_followups_dispatch_enabled", return_value=True
    ):
        ok, reason = scheduler_may_send_campaign(db, fu1, now_utc=datetime.now(timezone.utc))
    assert ok is True
    assert reason is None

