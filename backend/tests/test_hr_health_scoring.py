"""HR health / opportunity scoring and tier mapping tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.database.config import SessionLocal
from app.models import HRContact, EmailCampaign, Student
from app.services.assignment_service import validate_and_assign
from app.services.hr_health_scoring import (
    _batch_campaign_aggregates,
    score_hr,
    tier_at_or_above,
    tier_rank,
)


def _utc_naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def test_tier_d_when_invalid():
    db = SessionLocal()
    try:
        hr = HRContact(
            id=uuid.uuid4(),
            name="X",
            company="Y",
            email=f"x_{uuid.uuid4().hex[:8]}@acme.com",
            status="active",
            is_valid=False,
            is_fixture_test_data=True,
        )
        db.add(hr)
        db.commit()
        agg = _batch_campaign_aggregates(db, [hr.id]).get(hr.id)
        r = score_hr(hr, agg, {})
        assert r["tier"] == "D"
        assert r["health_score"] == 0.0
        codes = [x["code"] for x in r["health_reasons"]]
        assert "invalid_or_suppressed" in codes
    finally:
        db.close()


def test_delivery_problem_single_bucket_no_double_count():
    """Bounce OR delivery failed counts once per row (SQL OR), not twice."""
    db = SessionLocal()
    try:
        hr = HRContact(
            id=uuid.uuid4(),
            name="H",
            company="C",
            email=f"h_{uuid.uuid4().hex[:8]}@corp.com",
            status="active",
            is_valid=True,
            is_fixture_test_data=True,
        )
        st = Student(
            id=uuid.uuid4(),
            name="S",
            gmail_address=f"s_{uuid.uuid4().hex[:8]}@test.com",
            app_password="x",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        db.add(hr)
        db.add(st)
        db.commit()
        c = EmailCampaign(
            student_id=st.id,
            hr_id=hr.id,
            sequence_number=1,
            email_type="initial",
            scheduled_at=_utc_naive(datetime.now(timezone.utc)),
            status="failed",
            reply_status="BOUNCED",
            delivery_status="FAILED",
        )
        db.add(c)
        db.commit()

        agg = _batch_campaign_aggregates(db, [hr.id]).get(hr.id)
        assert agg is not None
        assert agg.n_delivery_problem == 1
        assert agg.n_failed_other == 0
    finally:
        db.close()


def test_tier_at_or_above_ordering():
    assert tier_rank("A") < tier_rank("B")
    assert tier_at_or_above("A", "B") is True
    assert tier_at_or_above("B", "B") is True
    assert tier_at_or_above("C", "B") is False
    assert tier_at_or_above("D", "A") is False


def test_assignment_rejects_below_min_tier():
    db = SessionLocal()
    try:
        st = Student(
            id=uuid.uuid4(),
            name="St",
            gmail_address=f"st_{uuid.uuid4().hex[:8]}@example.com",
            app_password="pw",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr = HRContact(
            id=uuid.uuid4(),
            name="H",
            company="Co",
            email=f"hr_{uuid.uuid4().hex[:8]}@example.com",
            status="active",
            is_valid=True,
            is_fixture_test_data=True,
        )
        db.add(st)
        db.add(hr)
        db.commit()

        _created, _rej_a, _rej_nf, _rej_inv, rej_tier = validate_and_assign(db, st.id, [hr.id], min_hr_tier="A")
        assert hr.id in rej_tier
    finally:
        db.close()


def test_positive_reply_signal_increases_opportunity():
    db = SessionLocal()
    try:
        hr = HRContact(
            id=uuid.uuid4(),
            name="Good",
            company="Co",
            email=f"good_{uuid.uuid4().hex[:8]}@corp.com",
            status="active",
            is_valid=True,
            last_contacted_at=_utc_naive(datetime.now(timezone.utc) - timedelta(days=2)),
            is_fixture_test_data=True,
        )
        st = Student(
            id=uuid.uuid4(),
            name="St2",
            gmail_address=f"s2_{uuid.uuid4().hex[:8]}@test.com",
            app_password="x",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        db.add(hr)
        db.add(st)
        db.commit()
        for seq, rep in enumerate([False, False, True, True], start=1):
            db.add(
                EmailCampaign(
                    student_id=st.id,
                    hr_id=hr.id,
                    sequence_number=seq,
                    email_type="initial",
                    scheduled_at=_utc_naive(datetime.now(timezone.utc)),
                    status="sent",
                    replied=rep,
                    reply_type="INTERVIEW" if rep else None,
                )
            )
        db.commit()

        agg = _batch_campaign_aggregates(db, [hr.id]).get(hr.id)
        r = score_hr(hr, agg, {})
        opp_codes = [x["code"] for x in r["opportunity_reasons"]]
        assert "positive_reply_signal" in opp_codes or r["opportunity_score"] >= 55
    finally:
        db.close()
