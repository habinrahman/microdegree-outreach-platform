"""
Invariants: priority queue + follow-up eligibility must agree on actionable vs suppressed pairs
and expose a single opportunity per student–HR pair in the queue surface.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.database.config import SessionLocal
from app.models import Assignment, EmailCampaign, HRContact, Student
from app.services.priority_queue_engine import BUCKET_ORDER, compute_priority_queue


def _utc_naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _row(out: dict, st_id, hr_id) -> dict:
    return next(
        r
        for r in out["rows"]
        if str(r["student"]["id"]) == str(st_id) and str(r["hr"]["id"]) == str(hr_id)
    )


def test_invariant_replied_stopped_never_send_now_or_followup_due():
    db = SessionLocal()
    try:
        st = Student(
            id=uuid.uuid4(),
            name="Inv",
            gmail_address=f"inv_r_{uuid.uuid4().hex[:10]}@gmail.com",
            app_password="pw",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr = HRContact(
            id=uuid.uuid4(),
            name="H",
            company="C",
            email=f"inv_r_{uuid.uuid4().hex[:10]}@co.com",
            status="active",
            is_valid=True,
            is_fixture_test_data=True,
        )
        db.add_all([st, hr])
        db.commit()
        db.add(Assignment(student_id=st.id, hr_id=hr.id, status="active"))
        t0 = _utc_naive(datetime.now(timezone.utc) - timedelta(days=40))
        db.add(
            EmailCampaign(
                student_id=st.id,
                hr_id=hr.id,
                sequence_number=1,
                email_type="initial",
                scheduled_at=t0,
                sent_at=t0,
                status="replied",
                replied=True,
                reply_type="INTERESTED",
            )
        )
        db.commit()

        out = compute_priority_queue(db, student_id=st.id, limit=50)
        row = _row(out, st.id, hr.id)
        assert row["queue_bucket"] == "SUPPRESS"
        assert row["queue_bucket"] not in ("SEND_NOW", "FOLLOW_UP_DUE")
        assert row["followup_status"] == "REPLIED_STOPPED"
    finally:
        db.close()


def test_invariant_bounced_stopped_never_send_now_or_followup_due():
    db = SessionLocal()
    try:
        st = Student(
            id=uuid.uuid4(),
            name="InvB",
            gmail_address=f"inv_b_{uuid.uuid4().hex[:10]}@gmail.com",
            app_password="pw",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr = HRContact(
            id=uuid.uuid4(),
            name="H",
            company="C",
            email=f"inv_b_{uuid.uuid4().hex[:10]}@co.com",
            status="active",
            is_valid=True,
            is_fixture_test_data=True,
        )
        db.add_all([st, hr])
        db.commit()
        db.add(Assignment(student_id=st.id, hr_id=hr.id, status="active"))
        t0 = _utc_naive(datetime.now(timezone.utc) - timedelta(days=10))
        db.add(
            EmailCampaign(
                student_id=st.id,
                hr_id=hr.id,
                sequence_number=1,
                email_type="initial",
                scheduled_at=t0,
                sent_at=t0,
                status="sent",
                reply_status="BOUNCED",
                delivery_status="FAILED",
            )
        )
        db.commit()

        out = compute_priority_queue(db, student_id=st.id, limit=50)
        row = _row(out, st.id, hr.id)
        assert row["queue_bucket"] == "SUPPRESS"
        assert row["followup_status"] == "BOUNCED_STOPPED"
    finally:
        db.close()


def test_invariant_unique_student_hr_pair_per_queue_row():
    db = SessionLocal()
    try:
        st = Student(
            id=uuid.uuid4(),
            name="U",
            gmail_address=f"inv_u_{uuid.uuid4().hex[:10]}@gmail.com",
            app_password="pw",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        db.add(st)
        hrs = []
        for _ in range(3):
            hr = HRContact(
                id=uuid.uuid4(),
                name="H",
                company="C",
                email=f"inv_u_{uuid.uuid4().hex[:10]}@co.com",
                status="active",
                is_valid=True,
                is_fixture_test_data=True,
            )
            db.add(hr)
            hrs.append(hr)
        db.commit()
        for hr in hrs:
            db.add(Assignment(student_id=st.id, hr_id=hr.id, status="active"))
        db.commit()

        out = compute_priority_queue(db, student_id=st.id, limit=50)
        keys = [(str(r["student"]["id"]), str(r["hr"]["id"])) for r in out["rows"]]
        assert len(keys) == len(set(keys))
    finally:
        db.close()


def test_invariant_follow_up_due_ranks_before_send_now_bucket_order():
    assert BUCKET_ORDER["FOLLOW_UP_DUE"] < BUCKET_ORDER["SEND_NOW"]
    assert BUCKET_ORDER["WARM_LEAD_PRIORITY"] < BUCKET_ORDER["LOW_PRIORITY"]


def test_invariant_same_pair_followup_due_beats_due_scheduled_initial_bucket():
    """When both signals exist, branch order assigns FOLLOW_UP_DUE (not SEND_NOW)."""
    db = SessionLocal()
    try:
        st = Student(
            id=uuid.uuid4(),
            name="Both",
            gmail_address=f"inv_both_{uuid.uuid4().hex[:10]}@gmail.com",
            app_password="pw",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr = HRContact(
            id=uuid.uuid4(),
            name="H",
            company="C",
            email=f"inv_both_{uuid.uuid4().hex[:10]}@co.com",
            status="active",
            is_valid=True,
            is_fixture_test_data=True,
        )
        db.add_all([st, hr])
        db.commit()
        db.add(Assignment(student_id=st.id, hr_id=hr.id, status="active"))
        sent_initial = _utc_naive(datetime.now(timezone.utc) - timedelta(days=30))
        due_sched = _utc_naive(datetime.now(timezone.utc) - timedelta(hours=1))
        db.add(
            EmailCampaign(
                student_id=st.id,
                hr_id=hr.id,
                sequence_number=1,
                email_type="initial",
                scheduled_at=sent_initial,
                sent_at=sent_initial,
                status="sent",
                replied=False,
            )
        )
        db.add(
            EmailCampaign(
                student_id=st.id,
                hr_id=hr.id,
                sequence_number=2,
                email_type="followup_1",
                scheduled_at=due_sched,
                status="pending",
                subject="s",
                body="b",
            )
        )
        db.commit()

        out = compute_priority_queue(db, student_id=st.id, limit=50)
        row = _row(out, st.id, hr.id)
        assert row["queue_bucket"] == "FOLLOW_UP_DUE"
        assert row["followup_status"] == "DUE_NOW"
    finally:
        db.close()


def test_invariant_followup_due_with_gmail_auth_cooldown_is_wait_not_followup_bucket():
    """Cooldown is per-student; must not label FOLLOW_UP_DUE while scheduler would skip sends."""
    db = SessionLocal()
    try:
        st = Student(
            id=uuid.uuid4(),
            name="Cd",
            gmail_address=f"inv_cd_{uuid.uuid4().hex[:10]}@gmail.com",
            app_password="pw",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr_main = HRContact(
            id=uuid.uuid4(),
            name="H1",
            company="C",
            email=f"inv_cd1_{uuid.uuid4().hex[:10]}@co.com",
            status="active",
            is_valid=True,
            is_fixture_test_data=True,
        )
        hr_other = HRContact(
            id=uuid.uuid4(),
            name="H2",
            company="C",
            email=f"inv_cd2_{uuid.uuid4().hex[:10]}@co.com",
            status="active",
            is_valid=True,
            is_fixture_test_data=True,
        )
        db.add_all([st, hr_main, hr_other])
        db.commit()
        db.add(Assignment(student_id=st.id, hr_id=hr_main.id, status="active"))
        db.add(Assignment(student_id=st.id, hr_id=hr_other.id, status="active"))
        sent_initial = _utc_naive(datetime.now(timezone.utc) - timedelta(days=30))
        db.add(
            EmailCampaign(
                student_id=st.id,
                hr_id=hr_main.id,
                sequence_number=1,
                email_type="initial",
                scheduled_at=sent_initial,
                sent_at=sent_initial,
                status="sent",
                replied=False,
            )
        )
        # Same student, other pair: recent Gmail auth block (eligible engine ignores this row's pair)
        db.add(
            EmailCampaign(
                student_id=st.id,
                hr_id=hr_other.id,
                sequence_number=1,
                email_type="initial",
                scheduled_at=_utc_naive(datetime.now(timezone.utc)),
                sent_at=_utc_naive(datetime.now(timezone.utc) - timedelta(minutes=2)),
                status="paused",
                error="gmail_auth_block",
                subject="x",
                body="y",
            )
        )
        db.commit()

        out = compute_priority_queue(db, student_id=st.id, limit=50)
        row = _row(out, st.id, hr_main.id)
        assert row["queue_bucket"] == "WAIT_FOR_COOLDOWN"
        assert row["followup_status"] == "DUE_NOW"
        assert "cooldown" in row["recommended_action"].lower() or (
            row.get("cooldown_status") and "cooldown" in (row["cooldown_status"] or "").lower()
        )
    finally:
        db.close()


def test_invariant_followup_due_pair_sorts_before_send_now_pair():
    """Global ordering: lower BUCKET_ORDER wins; FOLLOW_UP_DUE before SEND_NOW at equal tie-break layers."""
    db = SessionLocal()
    try:
        st = Student(
            id=uuid.uuid4(),
            name="Sort",
            gmail_address=f"inv_sort_{uuid.uuid4().hex[:10]}@gmail.com",
            app_password="pw",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr_fu = HRContact(
            id=uuid.uuid4(),
            name="A",
            company="A",
            email=f"inv_sort_a_{uuid.uuid4().hex[:10]}@a.com",
            status="active",
            is_valid=True,
            is_fixture_test_data=True,
        )
        hr_sn = HRContact(
            id=uuid.uuid4(),
            name="B",
            company="B",
            email=f"inv_sort_b_{uuid.uuid4().hex[:10]}@b.com",
            status="active",
            is_valid=True,
            is_fixture_test_data=True,
        )
        db.add_all([st, hr_fu, hr_sn])
        db.commit()
        db.add(Assignment(student_id=st.id, hr_id=hr_fu.id, status="active"))
        db.add(Assignment(student_id=st.id, hr_id=hr_sn.id, status="active"))
        ts = _utc_naive(datetime.now(timezone.utc) - timedelta(days=30))
        db.add(
            EmailCampaign(
                student_id=st.id,
                hr_id=hr_fu.id,
                sequence_number=1,
                email_type="initial",
                scheduled_at=ts,
                sent_at=ts,
                status="sent",
                replied=False,
            )
        )
        due_sched = _utc_naive(datetime.now(timezone.utc) - timedelta(minutes=30))
        db.add(
            EmailCampaign(
                student_id=st.id,
                hr_id=hr_sn.id,
                sequence_number=1,
                email_type="initial",
                scheduled_at=due_sched,
                status="pending",
                subject="s",
                body="b",
            )
        )
        db.commit()

        out = compute_priority_queue(db, student_id=st.id, limit=50)
        order = [(r["queue_bucket"], str(r["hr"]["id"])) for r in out["rows"]]
        fu_idx = next(i for i, (_, hid) in enumerate(order) if hid == str(hr_fu.id))
        sn_idx = next(i for i, (_, hid) in enumerate(order) if hid == str(hr_sn.id))
        assert order[fu_idx][0] == "FOLLOW_UP_DUE"
        assert order[sn_idx][0] == "SEND_NOW"
        assert fu_idx < sn_idx
    finally:
        db.close()
