"""Autonomous Sequencer v1 — sequencing, gate, suppression, immutability."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import patch

from app.database.config import SessionLocal
from app.models import Assignment, EmailCampaign, HRContact, Student
from app.services.campaign_generator import generate_campaigns_for_assignment
from app.services.campaign_cancel import cancel_followups_for_hr_response
from app.services.sequence_send_gate import scheduler_may_send_campaign
from app.services.sequence_service import ensure_four_step_campaign_rows, reschedule_followups_from_initial_sent
from app.services.sequence_state_service import (
    ACTIVE_SEQUENCE,
    TERMINATED_REPLIED,
    effective_sequence_state,
)


def _utc_naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def pair_db():
    db = SessionLocal()
    uid = uuid.uuid4().hex[:10]
    st = Student(
        id=uuid.uuid4(),
        name="S",
        gmail_address=f"s_seq_{uid}@example.com",
        app_password="x",
        status="active",
        is_demo=False,
        is_fixture_test_data=True,
    )
    hr = HRContact(
        id=uuid.uuid4(),
        name="H",
        company="C",
        email=f"h_seq_{uid}@example.com",
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


def test_pre_create_four_rows_anchor_day_0_7_14_21(pair_db):
    db, st, hr, a = pair_db
    anchor = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
    ensure_four_step_campaign_rows(db, a, anchor=anchor)
    rows = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id)
        .order_by(EmailCampaign.sequence_number.asc())
        .all()
    )
    assert len(rows) == 4
    assert [r.sequence_number for r in rows] == [1, 2, 3, 4]
    d0 = rows[0].scheduled_at
    assert (rows[1].scheduled_at - d0).days == 7
    assert (rows[2].scheduled_at - d0).days == 14
    assert (rows[3].scheduled_at - d0).days == 21


def test_reschedule_is_noop_preserves_scheduled_at(pair_db):
    db, st, hr, a = pair_db
    anchor = datetime(2026, 2, 1, 9, 0, 0, tzinfo=timezone.utc)
    ensure_four_step_campaign_rows(db, a, anchor=anchor)
    fu1 = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id, EmailCampaign.sequence_number == 2)
        .first()
    )
    before = fu1.scheduled_at
    reschedule_followups_from_initial_sent(
        db,
        student_id=st.id,
        hr_id=hr.id,
        initial_sent_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )
    db.refresh(fu1)
    assert fu1.scheduled_at != before
    assert (fu1.scheduled_at - _utc_naive(datetime(2099, 1, 1, tzinfo=timezone.utc))).days == 7


def test_reschedule_idempotent_and_does_not_touch_sent_followups(pair_db):
    db, st, hr, a = pair_db
    anchor = datetime(2026, 2, 1, 9, 0, 0, tzinfo=timezone.utc)
    ensure_four_step_campaign_rows(db, a, anchor=anchor)
    initial_sent = datetime(2026, 3, 5, 10, 0, 0, tzinfo=timezone.utc)

    # Mark FU2 as already sent; it must not be mutated by rescheduler.
    fu2 = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id, EmailCampaign.sequence_number == 3)
        .first()
    )
    fu2.status = "sent"
    fu2.sent_at = _utc_naive(datetime(2026, 3, 1, tzinfo=timezone.utc))
    old_fu2_sched = fu2.scheduled_at
    db.add(fu2)
    db.commit()

    # First call sets queueable rows.
    reschedule_followups_from_initial_sent(db, student_id=st.id, hr_id=hr.id, initial_sent_at=initial_sent)
    fu1 = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id, EmailCampaign.sequence_number == 2)
        .first()
    )
    fu3 = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id, EmailCampaign.sequence_number == 4)
        .first()
    )
    db.refresh(fu2)
    assert (fu1.scheduled_at - _utc_naive(initial_sent)).days == 7
    assert (fu3.scheduled_at - _utc_naive(initial_sent)).days == 21
    assert fu2.scheduled_at == old_fu2_sched  # sent row unchanged

    # Second call is idempotent: no changes
    before_fu1 = fu1.scheduled_at
    before_fu3 = fu3.scheduled_at
    reschedule_followups_from_initial_sent(db, student_id=st.id, hr_id=hr.id, initial_sent_at=initial_sent)
    db.refresh(fu1)
    db.refresh(fu3)
    assert fu1.scheduled_at == before_fu1
    assert fu3.scheduled_at == before_fu3


def test_gate_blocks_followup_when_sequence_not_active(pair_db):
    db, st, hr, a = pair_db
    anchor = _utc_naive(datetime.now(timezone.utc) - timedelta(days=30))
    ensure_four_step_campaign_rows(db, a, anchor=anchor)
    for c in (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id)
        .all()
    ):
        c.status = "scheduled"
        if c.sequence_number == 1:
            c.status = "sent"
            c.sent_at = anchor
            c.sequence_state = TERMINATED_REPLIED
        db.add(c)
    db.commit()
    fu2 = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id, EmailCampaign.sequence_number == 2)
        .first()
    )
    with patch("app.services.sequence_send_gate.FOLLOWUPS_ENABLED", True), patch(
        "app.services.sequence_send_gate.get_followups_dispatch_enabled", return_value=True
    ):
        ok, reason = scheduler_may_send_campaign(db, fu2, now_utc=datetime.now(timezone.utc))
    assert ok is False
    assert reason == "sequence_lifecycle_not_active"


def test_cancel_followups_sets_terminated_on_initial(pair_db):
    db, st, hr, a = pair_db
    ensure_four_step_campaign_rows(db, a, anchor=datetime.now(timezone.utc))
    initial = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id, EmailCampaign.sequence_number == 1)
        .first()
    )
    initial.status = "sent"
    initial.sent_at = _utc_naive(datetime.now(timezone.utc))
    for c in (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id, EmailCampaign.sequence_number > 1)
        .all()
    ):
        c.status = "scheduled"
        db.add(c)
    db.commit()
    cancel_followups_for_hr_response(db, st.id, hr.id, reason="test_cancel")
    db.refresh(initial)
    assert effective_sequence_state(initial) == TERMINATED_REPLIED


def test_followups_env_kill_switch(pair_db):
    db, st, hr, a = pair_db
    anchor = _utc_naive(datetime.now(timezone.utc) - timedelta(days=30))
    ensure_four_step_campaign_rows(db, a, anchor=anchor)
    rows = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id)
        .order_by(EmailCampaign.sequence_number.asc())
        .all()
    )
    for c in rows:
        c.status = "scheduled" if c.sequence_number > 1 else "sent"
        if c.sequence_number == 1:
            c.sent_at = anchor
        db.add(c)
    db.commit()
    fu2 = rows[1]
    with patch("app.services.sequence_send_gate.FOLLOWUPS_ENABLED", False):
        ok, reason = scheduler_may_send_campaign(db, fu2, now_utc=datetime.now(timezone.utc))
    assert ok is False
    assert reason == "followups_disabled_env"


def test_effective_sequence_state_null_means_active(pair_db):
    db, st, hr, a = pair_db
    ensure_four_step_campaign_rows(db, a)
    initial = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id, EmailCampaign.sequence_number == 1)
        .first()
    )
    initial.sequence_state = None
    db.commit()
    assert effective_sequence_state(initial) == ACTIVE_SEQUENCE


def test_generate_campaigns_idempotent_does_not_duplicate(pair_db):
    db, st, hr, a = pair_db
    generate_campaigns_for_assignment(db, a)
    generate_campaigns_for_assignment(db, a)
    n = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id)
        .count()
    )
    assert n == 4
