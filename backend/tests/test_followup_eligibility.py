from datetime import datetime, timedelta, timezone
import uuid


def _utc_naive(dt: datetime) -> datetime:
    # Tests use SQLite; existing code often stores naive UTC.
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def test_reply_suppresses_eligibility():
    from app.database.config import SessionLocal
    from app.models import Student, HRContact, Assignment, EmailCampaign
    from app.services.followup_eligibility import compute_followup_eligibility_for_pair

    db = SessionLocal()
    try:
        uid = uuid.uuid4().hex[:12]
        st = Student(
            id=uuid.uuid4(),
            name="S",
            gmail_address=f"s_reply_{uid}@example.com",
            app_password="x",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr = HRContact(
            id=uuid.uuid4(),
            name="H",
            company="C",
            email=f"h_reply_{uid}@example.com",
            status="active",
            is_valid=True,
            is_demo=False,
            is_fixture_test_data=True,
        )
        db.add(st); db.add(hr); db.commit()
        db.add(Assignment(student_id=st.id, hr_id=hr.id, status="active")); db.commit()

        initial = EmailCampaign(
            student_id=st.id,
            hr_id=hr.id,
            sequence_number=1,
            email_type="initial",
            scheduled_at=_utc_naive(datetime.now(timezone.utc)),
            sent_at=_utc_naive(datetime.now(timezone.utc) - timedelta(days=10)),
            status="sent",
            subject="s",
            body="b",
            replied=True,
            replied_at=_utc_naive(datetime.now(timezone.utc) - timedelta(days=1)),
        )
        db.add(initial); db.commit()

        state = compute_followup_eligibility_for_pair(db, student_id=st.id, hr_id=hr.id)
        assert state.eligible_for_followup is False
        assert state.blocked_reason == "Already replied"
        assert state.followup_status == "REPLIED_STOPPED"
    finally:
        db.close()


def test_bounce_blocks_eligibility():
    from app.database.config import SessionLocal
    from app.models import Student, HRContact, Assignment, EmailCampaign
    from app.services.followup_eligibility import compute_followup_eligibility_for_pair

    db = SessionLocal()
    try:
        uid = uuid.uuid4().hex[:12]
        st = Student(
            id=uuid.uuid4(),
            name="S",
            gmail_address=f"s_bounce_{uid}@example.com",
            app_password="x",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr = HRContact(
            id=uuid.uuid4(),
            name="H",
            company="C",
            email=f"h_bounce_{uid}@example.com",
            status="active",
            is_valid=True,
            is_demo=False,
            is_fixture_test_data=True,
        )
        db.add(st); db.add(hr); db.commit()
        db.add(Assignment(student_id=st.id, hr_id=hr.id, status="active")); db.commit()

        initial = EmailCampaign(
            student_id=st.id,
            hr_id=hr.id,
            sequence_number=1,
            email_type="initial",
            scheduled_at=_utc_naive(datetime.now(timezone.utc)),
            sent_at=_utc_naive(datetime.now(timezone.utc) - timedelta(days=10)),
            status="sent",
            subject="s",
            body="b",
            reply_status="BOUNCED",
            delivery_status="FAILED",
        )
        db.add(initial); db.commit()

        state = compute_followup_eligibility_for_pair(db, student_id=st.id, hr_id=hr.id)
        assert state.eligible_for_followup is False
        assert state.blocked_reason == "Bounced/blocked recipient"
        assert state.followup_status == "BOUNCED_STOPPED"
    finally:
        db.close()


def test_step_progression_and_due_date():
    from app.database.config import SessionLocal
    from app.models import Student, HRContact, Assignment, EmailCampaign
    from app.services.followup_eligibility import compute_followup_eligibility_for_pair

    db = SessionLocal()
    try:
        uid = uuid.uuid4().hex[:12]
        st = Student(
            id=uuid.uuid4(),
            name="S",
            gmail_address=f"s_step_{uid}@example.com",
            app_password="x",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr = HRContact(
            id=uuid.uuid4(),
            name="H",
            company="C",
            email=f"h_step_{uid}@example.com",
            status="active",
            is_valid=True,
            is_demo=False,
            is_fixture_test_data=True,
        )
        db.add(st); db.add(hr); db.commit()
        db.add(Assignment(student_id=st.id, hr_id=hr.id, status="active")); db.commit()

        base_sent = datetime.now(timezone.utc) - timedelta(days=8)
        initial = EmailCampaign(
            student_id=st.id,
            hr_id=hr.id,
            sequence_number=1,
            email_type="initial",
            scheduled_at=_utc_naive(datetime.now(timezone.utc)),
            sent_at=_utc_naive(base_sent),
            status="sent",
            subject="s",
            body="b",
        )
        db.add(initial); db.commit()

        state1 = compute_followup_eligibility_for_pair(db, student_id=st.id, hr_id=hr.id)
        assert state1.eligible_for_followup is True
        assert state1.next_followup_step == 1
        assert state1.next_template_type == "FOLLOWUP_1"
        assert state1.followup_status == "DUE_NOW"
        assert state1.days_until_due == 0

        fu1 = EmailCampaign(
            student_id=st.id,
            hr_id=hr.id,
            sequence_number=2,
            email_type="followup_1",
            scheduled_at=_utc_naive(datetime.now(timezone.utc)),
            sent_at=_utc_naive(datetime.now(timezone.utc) - timedelta(days=1)),
            status="sent",
            subject="s",
            body="b",
        )
        db.add(fu1); db.commit()

        state2 = compute_followup_eligibility_for_pair(db, student_id=st.id, hr_id=hr.id)
        assert state2.current_step == 1
        assert state2.next_followup_step == 2
        assert state2.next_template_type == "FOLLOWUP_2"
        # step2 is 14d from FU1; FU1 was sent 1d ago so should be blocked
        assert state2.eligible_for_followup is False
        assert state2.blocked_reason and "14-day interval" in state2.blocked_reason
        assert state2.followup_status == "WAITING"
    finally:
        db.close()


def test_manual_pause_blocks_eligibility():
    from app.database.config import SessionLocal
    from app.models import Student, HRContact, Assignment, EmailCampaign
    from app.services.followup_eligibility import compute_followup_eligibility_for_pair

    db = SessionLocal()
    try:
        uid = uuid.uuid4().hex[:12]
        st = Student(
            id=uuid.uuid4(),
            name="S",
            gmail_address=f"s_pause_{uid}@example.com",
            app_password="x",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr = HRContact(
            id=uuid.uuid4(),
            name="H",
            company="C",
            email=f"h_pause_{uid}@example.com",
            status="active",
            is_valid=True,
            is_demo=False,
            is_fixture_test_data=True,
        )
        db.add(st); db.add(hr); db.commit()
        db.add(Assignment(student_id=st.id, hr_id=hr.id, status="active")); db.commit()

        initial = EmailCampaign(
            student_id=st.id,
            hr_id=hr.id,
            sequence_number=1,
            email_type="initial",
            scheduled_at=_utc_naive(datetime.now(timezone.utc)),
            sent_at=_utc_naive(datetime.now(timezone.utc) - timedelta(days=10)),
            status="sent",
            subject="s",
            body="b",
        )
        paused = EmailCampaign(
            student_id=st.id,
            hr_id=hr.id,
            sequence_number=2,
            email_type="followup_1",
            scheduled_at=_utc_naive(datetime.now(timezone.utc)),
            status="paused",
            subject="s",
            body="b",
        )
        db.add(initial); db.add(paused); db.commit()

        state = compute_followup_eligibility_for_pair(db, student_id=st.id, hr_id=hr.id)
        assert state.eligible_for_followup is False
        assert state.blocked_reason == "Manual pause enabled"
        assert state.followup_status == "PAUSED"
    finally:
        db.close()


def test_send_in_progress_blocks_eligibility():
    from app.database.config import SessionLocal
    from app.models import Student, HRContact, Assignment, EmailCampaign
    from app.services.followup_eligibility import compute_followup_eligibility_for_pair

    db = SessionLocal()
    try:
        uid = uuid.uuid4().hex[:12]
        st = Student(
            id=uuid.uuid4(),
            name="S",
            gmail_address=f"s_inflight_{uid}@example.com",
            app_password="x",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr = HRContact(
            id=uuid.uuid4(),
            name="H",
            company="C",
            email=f"h_inflight_{uid}@example.com",
            status="active",
            is_valid=True,
            is_demo=False,
            is_fixture_test_data=True,
        )
        db.add(st); db.add(hr); db.commit()
        db.add(Assignment(student_id=st.id, hr_id=hr.id, status="active")); db.commit()

        initial = EmailCampaign(
            student_id=st.id,
            hr_id=hr.id,
            sequence_number=1,
            email_type="initial",
            scheduled_at=_utc_naive(datetime.now(timezone.utc)),
            sent_at=_utc_naive(datetime.now(timezone.utc) - timedelta(days=10)),
            status="sent",
            subject="s",
            body="b",
        )
        inflight = EmailCampaign(
            student_id=st.id,
            hr_id=hr.id,
            sequence_number=2,
            email_type="followup_1",
            scheduled_at=_utc_naive(datetime.now(timezone.utc)),
            status="processing",
            subject="s",
            body="b",
        )
        db.add(initial); db.add(inflight); db.commit()

        state = compute_followup_eligibility_for_pair(db, student_id=st.id, hr_id=hr.id)
        assert state.eligible_for_followup is False
        assert state.followup_status == "SEND_IN_PROGRESS"
        assert state.send_in_progress is True
        assert state.blocked_reason == "Send in progress"
    finally:
        db.close()


def test_list_followup_eligibility_includes_uppercase_initial_email_type():
    """Regression: /followups/eligible must find rows when DB stores ``INITIAL`` not ``initial``."""
    from app.database.config import SessionLocal
    from app.models import Student, HRContact, Assignment, EmailCampaign
    from app.services.followup_eligibility import list_followup_eligibility

    db = SessionLocal()
    try:
        uid = uuid.uuid4().hex[:8]
        st = Student(
            id=uuid.uuid4(),
            name="FUList",
            gmail_address=f"fulist_{uid}@example.com",
            app_password="x",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr = HRContact(
            id=uuid.uuid4(),
            name="HRList",
            company="CoList",
            email=f"hrl_{uid}@example.com",
            status="active",
            is_valid=True,
            is_demo=False,
            is_fixture_test_data=True,
        )
        db.add(st)
        db.add(hr)
        db.commit()
        db.add(Assignment(student_id=st.id, hr_id=hr.id, status="active"))
        db.commit()

        base_sent = datetime.now(timezone.utc) - timedelta(days=10)
        initial = EmailCampaign(
            student_id=st.id,
            hr_id=hr.id,
            sequence_number=1,
            email_type="INITIAL",
            scheduled_at=_utc_naive(datetime.now(timezone.utc)),
            sent_at=_utc_naive(base_sent),
            status="sent",
            subject="s",
            body="b",
        )
        db.add(initial)
        db.commit()

        payload = list_followup_eligibility(db, include_demo=False, limit=500)
        ours = [r for r in payload["rows"] if r["student_id"] == str(st.id) and r["hr_id"] == str(hr.id)]
        assert len(ours) == 1
        assert "status_breakdown" in payload
        assert "pagination" in payload
        assert payload["pagination"]["total_pairs"] >= 1
        assert ours[0]["followup_status"] in ("WAITING", "DUE_NOW")
    finally:
        db.close()


def test_list_followup_eligibility_dedupes_duplicate_sent_initials_same_pair():
    """Invariant: one list row per student–HR (matches priority queue one-row-per-pair surface)."""
    from app.database.config import SessionLocal
    from app.models import Student, HRContact, Assignment, EmailCampaign
    from app.services.followup_eligibility import list_followup_eligibility

    db = SessionLocal()
    try:
        uid = uuid.uuid4().hex[:10]
        st = Student(
            id=uuid.uuid4(),
            name="Dedup",
            gmail_address=f"dedup_s_{uid}@example.com",
            app_password="x",
            status="active",
            is_demo=False,
            is_fixture_test_data=True,
        )
        hr = HRContact(
            id=uuid.uuid4(),
            name="HR",
            company="Co",
            email=f"dedup_h_{uid}@example.com",
            status="active",
            is_valid=True,
            is_demo=False,
            is_fixture_test_data=True,
        )
        db.add(st)
        db.add(hr)
        db.commit()
        db.add(Assignment(student_id=st.id, hr_id=hr.id, status="active"))
        db.commit()

        older = _utc_naive(datetime.now(timezone.utc) - timedelta(days=60))
        newer = _utc_naive(datetime.now(timezone.utc) - timedelta(days=20))
        db.add(
            EmailCampaign(
                student_id=st.id,
                hr_id=hr.id,
                sequence_number=1,
                email_type="initial",
                scheduled_at=older,
                sent_at=older,
                status="sent",
                subject="a",
                body="b",
            )
        )
        db.add(
            EmailCampaign(
                student_id=st.id,
                hr_id=hr.id,
                sequence_number=10,
                email_type="initial",
                scheduled_at=newer,
                sent_at=newer,
                status="sent",
                subject="a2",
                body="b2",
            )
        )
        db.commit()

        payload = list_followup_eligibility(db, include_demo=False, limit=500)
        ours = [r for r in payload["rows"] if r["student_id"] == str(st.id) and r["hr_id"] == str(hr.id)]
        assert len(ours) == 1
        assert ours[0]["initial_campaign_id"]  # canonical row references one initial
        assert payload["pagination"]["total_pairs"] == 1

        p2 = list_followup_eligibility(db, include_demo=False, limit=1, offset=0)
        assert p2["pagination"]["has_more"] is False
        assert len(p2["rows"]) == 1
    finally:
        db.close()


def test_thread_headers_are_preserved_in_email_message(tmp_path):
    """
    Unit test: ensure follow-up sends can preserve threading headers
    (In-Reply-To + References). We validate message construction only.
    """
    from app.services.email_sender import build_email_message

    # create dummy resume
    resume = tmp_path / "r.pdf"
    resume.write_bytes(b"%PDF-1.4 test")

    msg = build_email_message(
        student_email="s@example.com",
        hr_email="h@example.com",
        student_name="S",
        company="C",
        resume_path=str(resume),
        subject="Subj",
        body="Body",
        use_stored_campaign_content=True,
        in_reply_to="<mid0@example>",
        references=["<mid0@example>", "<mid1@example>"],
    )
    assert msg["In-Reply-To"] == "<mid0@example>"
    assert "<mid0@example>" in str(msg.get("References", ""))
    assert "<mid1@example>" in str(msg.get("References", ""))

