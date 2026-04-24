from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    assert "docs" in r.json()


def test_health_schema_launch_gate():
    r = client.get("/health/schema-launch-gate")
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") in ("ok", "degraded", "critical")
    assert isinstance(body.get("tables"), list)


def test_analytics_summary():
    r = client.get("/analytics/summary")
    assert r.status_code == 200
    data = r.json()
    for k in [
        "students",
        "hrs",
        "assignments",
        "emails_sent",
        "emails_failed",
        "success_rate",
        "campaigns_sent",
        "campaigns_scheduled",
        "campaigns_total",
        "responses",
        "reply_rate",
        "total_emails_all_time",
        "total_sent",
        "total_failed",
        "total_cancelled",
        "total_replied",
    ]:
        assert k in data


def test_analytics_summary_semantics():
    r = client.get("/analytics/summary")
    assert r.status_code == 200
    d = r.json()

    sent = int(d.get("emails_sent", 0) or 0)
    failed = int(d.get("emails_failed", 0) or 0)
    bounced = int(d.get("total_bounced", d.get("bounced", 0)) or 0)

    # success_rate = sent / (sent + failed) * 100
    attempted = sent + failed
    expected_success = round((sent / attempted * 100) if attempted > 0 else 0.0, 2)
    assert abs(float(d.get("success_rate", 0.0)) - expected_success) < 0.01

    # bounce_rate = bounced / sent * 100  (as implemented in backend)
    expected_bounce = round(min(100.0, (100.0 * bounced / sent) if sent > 0 else 0.0), 2)
    assert abs(float(d.get("bounce_rate", 0.0)) - expected_bounce) < 0.01


def test_delivery_buckets_are_exclusive_when_present():
    r = client.get("/analytics/summary")
    assert r.status_code == 200
    d = r.json()

    # New exclusive buckets (may be absent on older deployments).
    if not all(k in d for k in ("delivery_sent", "delivery_failed_other", "delivery_bounced", "delivery_blocked")):
        return

    sent = int(d.get("delivery_sent") or 0)
    failed_other = int(d.get("delivery_failed_other") or 0)
    bounced = int(d.get("delivery_bounced") or 0)
    blocked = int(d.get("delivery_blocked") or 0)

    assert sent >= 0 and failed_other >= 0 and bounced >= 0 and blocked >= 0
    # If total delivery_failed is reported, it must reconcile.
    if "delivery_failed" in d:
        assert int(d.get("delivery_failed") or 0) == failed_other + bounced + blocked


def test_precreated_four_step_sequence_backfills_after_initial_sent():
    """Rows 2–4 are materialized even when env follow-ups are off; sending is gated elsewhere."""
    from app.services.campaign_generator import generate_campaigns_for_assignment
    from app.database.config import SessionLocal
    from app.models import Student, HRContact, Assignment, EmailCampaign
    from datetime import datetime, timezone
    import uuid

    db = SessionLocal()
    try:
        st = Student(id=uuid.uuid4(), name="T", gmail_address="t@example.com", app_password="x", status="active", is_demo=False, is_fixture_test_data=True)
        hr = HRContact(id=uuid.uuid4(), name="H", company="C", email="h@example.com", status="active", is_valid=True, is_demo=False, is_fixture_test_data=True)
        db.add(st); db.add(hr); db.commit()
        a = Assignment(student_id=st.id, hr_id=hr.id, status="active")
        db.add(a); db.commit(); db.refresh(a)

        initial = EmailCampaign(
            student_id=st.id,
            hr_id=hr.id,
            sequence_number=1,
            email_type="initial",
            scheduled_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status="sent",
            sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
            subject="s",
            body="b",
        )
        db.add(initial); db.commit()

        created = generate_campaigns_for_assignment(db, a)
        assert len(created) == 1
        assert int(created[0].sequence_number) == 1

        rows = (
            db.query(EmailCampaign)
            .filter(EmailCampaign.student_id == st.id, EmailCampaign.hr_id == hr.id)
            .order_by(EmailCampaign.sequence_number.asc())
            .all()
        )
        assert len(rows) == 4
        assert [r.sequence_number for r in rows] == [1, 2, 3, 4]
        assert {r.email_type.lower() for r in rows} == {"initial", "followup_1", "followup_2", "followup_3"}
    finally:
        db.close()


def test_scheduler_stale_processing_is_paused_not_rescheduled():
    """
    Idempotency safety: a campaign stuck in processing may have been sent already
    (crash after SMTP accepted, before DB commit). Scheduler must not auto-resend it.
    """
    from app.database.config import SessionLocal
    from app.models import Student, HRContact, EmailCampaign
    from app.services.campaign_scheduler import run_campaign_job
    from datetime import datetime, timezone, timedelta
    import uuid

    db = SessionLocal()
    try:
        st = Student(id=uuid.uuid4(), name="T", gmail_address="t@example.com", app_password="x", status="active", is_demo=False, is_fixture_test_data=True)
        hr = HRContact(id=uuid.uuid4(), name="H", company="C", email="h@example.com", status="active", is_valid=True, is_demo=False, is_fixture_test_data=True)
        db.add(st); db.add(hr); db.commit()

        old = datetime.now(timezone.utc) - timedelta(minutes=30)
        c = EmailCampaign(
            student_id=st.id,
            hr_id=hr.id,
            sequence_number=1,
            email_type="initial",
            scheduled_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status="processing",
            processing_started_at=old.replace(tzinfo=None),
            processing_lock_acquired_at=old.replace(tzinfo=None),
            subject="s",
            body="b",
        )
        db.add(c); db.commit(); db.refresh(c)

        # Run scheduler tick; it should pause the stale processing row.
        run_campaign_job(
            ignore_window=True,
            ignore_scheduled_time=True,
            skip_delay=True,
            limit=0,
            ignore_deliverability_pause=True,
        )
        db.refresh(c)
        assert c.status == "paused"
        assert c.error and "stale_processing_unknown_outcome" in (c.error or "")
        assert (c.terminal_outcome or "") == "PAUSED_UNKNOWN_OUTCOME"
    finally:
        db.close()


def test_followup_funnel_includes_terminal_outcome_on_pairs():
    r = client.get("/followups/funnel/summary")
    assert r.status_code == 200
    d = r.json()
    assert "terminal_outcome_on_pairs" in d
    toc = d["terminal_outcome_on_pairs"]
    for k in (
        "REPLIED_AFTER_INITIAL",
        "REPLIED_AFTER_FU1",
        "REPLIED_AFTER_FU2",
        "REPLIED_AFTER_FU3",
        "NO_RESPONSE_COMPLETED",
        "BOUNCED",
        "PAUSED_UNKNOWN_OUTCOME",
        "UNSET",
    ):
        assert k in toc
        assert isinstance(toc[k], int)


def test_record_pair_terminal_outcome_does_not_downgrade_replied_to_no_response():
    from app.database.config import SessionLocal
    from app.models import Student, HRContact, EmailCampaign
    from datetime import datetime, timezone
    from app.services.campaign_terminal_outcomes import (
        NO_RESPONSE_COMPLETED,
        REPLIED_AFTER_FU1,
        record_pair_terminal_outcome,
    )
    import uuid

    db = SessionLocal()
    try:
        st = Student(
            id=uuid.uuid4(),
            name="T",
            gmail_address="t@example.com",
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
        db.add(st)
        db.add(hr)
        db.commit()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        initial = EmailCampaign(
            student_id=st.id,
            hr_id=hr.id,
            sequence_number=1,
            email_type="initial",
            scheduled_at=now,
            status="sent",
            sent_at=now,
            subject="s",
            body="b",
            terminal_outcome=REPLIED_AFTER_FU1,
        )
        fu3 = EmailCampaign(
            student_id=st.id,
            hr_id=hr.id,
            sequence_number=4,
            email_type="followup_3",
            scheduled_at=now,
            status="sent",
            sent_at=now,
            subject="s",
            body="b",
        )
        db.add(initial)
        db.add(fu3)
        db.commit()

        record_pair_terminal_outcome(
            db,
            student_id=st.id,
            hr_id=hr.id,
            outcome=NO_RESPONSE_COMPLETED,
            tag_campaign=fu3,
        )
        db.commit()
        db.refresh(initial)
        db.refresh(fu3)
        assert initial.terminal_outcome == REPLIED_AFTER_FU1
        assert fu3.terminal_outcome is None or fu3.terminal_outcome == ""
    finally:
        db.close()

