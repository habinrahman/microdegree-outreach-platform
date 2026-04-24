"""Priority outreach queue engine (read-only) tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.database.config import SessionLocal
from app.models import Assignment, EmailCampaign, HRContact, Student
from app.services.priority_queue_engine import _normalize_weights, compute_priority_queue


def _row_for_pair(out: dict, st: Student, hr: HRContact) -> dict:
    return next(
        r
        for r in out["rows"]
        if str(r["student"]["id"]) == str(st.id) and str(r["hr"]["id"]) == str(hr.id)
    )


def _utc_naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def test_suppress_invalid_hr_and_safe_action():
    db = SessionLocal()
    try:
        st = Student(
            id=uuid.uuid4(),
            name="St",
            gmail_address=f"s_{uuid.uuid4().hex[:8]}@gmail.com",
            app_password="pw",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr = HRContact(
            id=uuid.uuid4(),
            name="H",
            company="Co",
            email=f"h_{uuid.uuid4().hex[:8]}@corp.com",
            status="active",
            is_valid=False,
            is_fixture_test_data=True,
        )
        db.add_all([st, hr])
        db.commit()
        db.add(Assignment(student_id=st.id, hr_id=hr.id, status="active"))
        db.commit()

        out = compute_priority_queue(db, student_id=st.id, limit=50)
        row = _row_for_pair(out, st, hr)
        assert row["queue_bucket"] == "SUPPRESS"
        assert "Do not contact" in row["recommended_action"]
        assert any("tier D" in x or "Invalid" in x or "invalid" in x.lower() for x in row["recommendation_reason"])
    finally:
        db.close()


def test_follow_up_due_bucket_and_reason():
    db = SessionLocal()
    try:
        st = Student(
            id=uuid.uuid4(),
            name="St2",
            gmail_address=f"s2_{uuid.uuid4().hex[:8]}@gmail.com",
            app_password="pw",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr = HRContact(
            id=uuid.uuid4(),
            name="H2",
            company="Co2",
            email=f"h2_{uuid.uuid4().hex[:8]}@corp2.com",
            status="active",
            is_valid=True,
            is_fixture_test_data=True,
        )
        db.add_all([st, hr])
        db.commit()
        db.add(Assignment(student_id=st.id, hr_id=hr.id, status="active"))
        db.commit()

        sent_initial = _utc_naive(datetime.now(timezone.utc) - timedelta(days=30))
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
        db.commit()

        out = compute_priority_queue(db, student_id=st.id, limit=50)
        row = _row_for_pair(out, st, hr)
        assert row["queue_bucket"] == "FOLLOW_UP_DUE"
        assert row["followup_status"] == "DUE_NOW"
        assert "Follow-up" in row["recommended_action"] or "follow-up" in row["recommended_action"].lower()
        assert any("due" in x.lower() for x in row["recommendation_reason"])
        dd = row.get("decision_diagnostics") or {}
        assert dd.get("decision_computed_at_utc")
        assert dd.get("bucket_rationale")
        assert dd.get("follow_up", {}).get("status") == "DUE_NOW"
        assert dd.get("scoring", {}).get("top_components")
    finally:
        db.close()


def test_ranking_determinism_tiebreak_stable():
    db = SessionLocal()
    try:
        st = Student(
            id=uuid.uuid4(),
            name="Tie",
            gmail_address=f"tb_{uuid.uuid4().hex[:6]}@gmail.com",
            app_password="pw",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        db.add(st)
        pairs = []
        for i in range(2):
            hr = HRContact(
                id=uuid.uuid4(),
                name="H",
                company=f"C{i}",
                email=f"tb{i}_{uuid.uuid4().hex[:6]}@samecorp.com",
                status="active",
                is_valid=True,
                is_fixture_test_data=True,
            )
            db.add(hr)
            pairs.append(hr)
        db.commit()
        for hr in pairs:
            db.add(Assignment(student_id=st.id, hr_id=hr.id, status="active"))
        db.commit()

        a1 = compute_priority_queue(db, student_id=st.id, limit=50)
        a2 = compute_priority_queue(db, student_id=st.id, limit=50)
        ids1 = [(r["student"]["id"], r["hr"]["id"]) for r in a1["rows"]]
        ids2 = [(r["student"]["id"], r["hr"]["id"]) for r in a2["rows"]]
        assert ids1 == ids2
    finally:
        db.close()


def test_suppress_replied_stopped():
    db = SessionLocal()
    try:
        st = Student(
            id=uuid.uuid4(),
            name="R",
            gmail_address=f"sr_{uuid.uuid4().hex[:8]}@gmail.com",
            app_password="pw",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr = HRContact(
            id=uuid.uuid4(),
            name="HR",
            company="Co",
            email=f"sr_{uuid.uuid4().hex[:8]}@co.com",
            status="active",
            is_valid=True,
            is_fixture_test_data=True,
        )
        db.add_all([st, hr])
        db.commit()
        db.add(Assignment(student_id=st.id, hr_id=hr.id, status="active"))
        t0 = _utc_naive(datetime.now(timezone.utc) - timedelta(days=5))
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
        row = _row_for_pair(out, st, hr)
        assert row["queue_bucket"] == "SUPPRESS"
        assert "Do not contact" in row["recommended_action"]
        wns = (row.get("decision_diagnostics") or {}).get("why_not_sent")
        assert wns and wns.get("is_suppressed") is True
        assert wns.get("blockers")
    finally:
        db.close()


def test_only_due_filter():
    db = SessionLocal()
    try:
        st = Student(
            id=uuid.uuid4(),
            name="OD",
            gmail_address=f"od_{uuid.uuid4().hex[:8]}@gmail.com",
            app_password="pw",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr1 = HRContact(
            id=uuid.uuid4(),
            name="A",
            company="A",
            email=f"od1_{uuid.uuid4().hex[:8]}@a.com",
            is_valid=True,
            is_fixture_test_data=True,
        )
        hr2 = HRContact(
            id=uuid.uuid4(),
            name="B",
            company="B",
            email=f"od2_{uuid.uuid4().hex[:8]}@b.com",
            is_valid=True,
            is_fixture_test_data=True,
        )
        db.add_all([st, hr1, hr2])
        db.commit()
        db.add(Assignment(student_id=st.id, hr_id=hr1.id, status="active"))
        db.add(Assignment(student_id=st.id, hr_id=hr2.id, status="active"))
        ts = _utc_naive(datetime.now(timezone.utc) - timedelta(days=30))
        db.add(
            EmailCampaign(
                student_id=st.id,
                hr_id=hr1.id,
                sequence_number=1,
                email_type="initial",
                scheduled_at=ts,
                sent_at=ts,
                status="sent",
                replied=False,
            )
        )
        db.add(
            EmailCampaign(
                student_id=st.id,
                hr_id=hr2.id,
                sequence_number=1,
                email_type="initial",
                scheduled_at=ts,
                sent_at=ts,
                status="sent",
                replied=False,
            )
        )
        db.commit()

        out = compute_priority_queue(db, student_id=st.id, only_due=True, limit=50)
        for r in out["rows"]:
            assert r["queue_bucket"] in ("SEND_NOW", "FOLLOW_UP_DUE")
    finally:
        db.close()


def test_weights_sum_to_one():
    wf, wo, wh, ws, ww = _normalize_weights()
    assert abs(wf + wo + wh + ws + ww - 1.0) < 1e-9


def test_dimension_scores_distinct_from_hr_scores():
    """Cooldown penalty is its own axis — not merged into health/opportunity."""
    db = SessionLocal()
    try:
        st = Student(
            id=uuid.uuid4(),
            name="Dim",
            gmail_address=f"dm_{uuid.uuid4().hex[:8]}@gmail.com",
            app_password="pw",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr = HRContact(
            id=uuid.uuid4(),
            name="H",
            company="C",
            email=f"dm_{uuid.uuid4().hex[:8]}@corp.com",
            status="paused",
            paused_until=_utc_naive(datetime.now(timezone.utc) + timedelta(days=7)),
            is_valid=True,
            is_fixture_test_data=True,
        )
        db.add_all([st, hr])
        db.commit()
        db.add(Assignment(student_id=st.id, hr_id=hr.id, status="active"))
        db.commit()

        out = compute_priority_queue(db, student_id=st.id, limit=50)
        row = _row_for_pair(out, st, hr)
        assert "cooldown_penalty" in row["dimension_scores"]
        assert row["dimension_scores"]["hr_health"] == row["health_score"]
        assert row["dimension_scores"]["hr_opportunity"] == row["opportunity_score"]
    finally:
        db.close()


def test_no_contradictory_suppress_send():
    db = SessionLocal()
    try:
        st = Student(
            id=uuid.uuid4(),
            name="X",
            gmail_address=f"xx_{uuid.uuid4().hex[:8]}@gmail.com",
            app_password="pw",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr = HRContact(
            id=uuid.uuid4(),
            name="Y",
            company="Z",
            email=f"xx_{uuid.uuid4().hex[:8]}@blk.com",
            is_valid=False,
            is_fixture_test_data=True,
        )
        db.add_all([st, hr])
        db.commit()
        db.add(Assignment(student_id=st.id, hr_id=hr.id, status="active"))
        db.commit()

        out = compute_priority_queue(db, student_id=st.id, limit=50)
        row = _row_for_pair(out, st, hr)
        assert row["queue_bucket"] == "SUPPRESS"
        assert "Send" not in row["recommended_action"] or "not" in row["recommended_action"].lower()
    finally:
        db.close()
