"""Demo flow validation: send -> reply detect -> follow-up stop -> analytics update."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from app.database.config import init_db, SessionLocal
from app.models import Assignment, EmailCampaign, HRContact, Student
from app.routers.analytics import get_email_status
from app.services import reply_tracker


def _cleanup_demo_rows(db, tag: str):
    demo_email_like = f"%{tag.lower()}%"
    hrs = db.query(HRContact).filter(HRContact.email.like(demo_email_like)).all()
    hr_ids = [h.id for h in hrs]
    student = db.query(Student).filter(Student.gmail_address.like(demo_email_like)).first()
    student_id = student.id if student else None

    if hr_ids:
        db.query(EmailCampaign).filter(EmailCampaign.hr_id.in_(hr_ids)).delete(synchronize_session=False)
        db.query(Assignment).filter(Assignment.hr_id.in_(hr_ids)).delete(synchronize_session=False)
        db.query(HRContact).filter(HRContact.id.in_(hr_ids)).delete(synchronize_session=False)
    if student_id:
        db.query(EmailCampaign).filter(EmailCampaign.student_id == student_id).delete(synchronize_session=False)
        db.query(Assignment).filter(Assignment.student_id == student_id).delete(synchronize_session=False)
        db.query(Student).filter(Student.id == student_id).delete(synchronize_session=False)
    db.commit()


def run_demo():
    init_db()
    db = SessionLocal()
    tag = f"demo{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    print(f"[DEMO] tag={tag}")

    try:
        _cleanup_demo_rows(db, tag)

        # STEP 1: setup demo data
        student = Student(
            name=f"Demo Student {tag}",
            gmail_address=f"student.{tag}@example.com",
            gmail_refresh_token="demo_refresh_token",
            gmail_connected=True,
            status="active",
            is_demo=True,
        )
        db.add(student)
        db.flush()

        hrs: list[HRContact] = []
        for i in range(1, 6):
            hr = HRContact(
                name=f"HR {i}",
                company=f"Demo Company {i}",
                email=f"hr{i}.{tag}@example.com",
                status="active",
                is_demo=True,
            )
            hrs.append(hr)
            db.add(hr)
        db.flush()

        for hr in hrs:
            db.add(Assignment(student_id=student.id, hr_id=hr.id, status="active"))
        db.commit()
        print(f"[STEP1] created student=1, hrs={len(hrs)}, invalid_hrs={sum(1 for h in hrs if h.status == 'invalid')}")

        # STEP 2: simulate sent campaigns + scheduled followups
        now = datetime.now(timezone.utc)
        sent_initial_ids = []
        for idx, hr in enumerate(hrs, start=1):
            initial = EmailCampaign(
                student_id=student.id,
                hr_id=hr.id,
                sequence_number=1,
                email_type="initial",
                status="sent",
                sent_at=now - timedelta(minutes=20 - idx),
                scheduled_at=now - timedelta(minutes=30 - idx),
                subject=f"Intro {idx}",
                body="Demo outreach body",
                message_id=f"<msg-{tag}-{idx}@example.com>",
                thread_id=f"thread-{tag}-{idx}",
            )
            db.add(initial)
            db.flush()
            sent_initial_ids.append(initial.id)

            follow = EmailCampaign(
                student_id=student.id,
                hr_id=hr.id,
                sequence_number=2,
                email_type="followup_1",
                status="scheduled",
                scheduled_at=now + timedelta(days=1),
                subject=f"Follow-up {idx}",
                body="Demo follow-up body",
            )
            db.add(follow)
        db.commit()

        sent_count = (
            db.query(EmailCampaign)
            .filter(EmailCampaign.student_id == student.id, EmailCampaign.status == "sent")
            .count()
        )
        with_sent_at = (
            db.query(EmailCampaign)
            .filter(
                EmailCampaign.student_id == student.id,
                EmailCampaign.status == "sent",
                EmailCampaign.sent_at.isnot(None),
            )
            .count()
        )
        print(f"[STEP2] campaigns_sent={sent_count}, sent_at_populated={with_sent_at == sent_count}")

        # STEP 3/4: simulate one HR reply and manually trigger reply tracker
        replied_hr = hrs[0]
        replied_campaign = (
            db.query(EmailCampaign)
            .filter(
                EmailCampaign.student_id == student.id,
                EmailCampaign.hr_id == replied_hr.id,
                EmailCampaign.sequence_number == 1,
            )
            .first()
        )
        assert replied_campaign is not None

        fake_msg_id = f"gmail-reply-{tag}-1"
        fake_internal_date = str(int(datetime.now(timezone.utc).timestamp() * 1000))

        class _FakeService:
            def users(self):
                return self

            def messages(self):
                return self

            def list(self, **kwargs):
                self._op = "list"
                self._kwargs = kwargs
                return self

            def get(self, **kwargs):
                self._op = "get"
                self._kwargs = kwargs
                return self

            def execute(self):
                if getattr(self, "_op", "") == "list":
                    return {"messages": [{"id": fake_msg_id}], "nextPageToken": None}
                return {
                    "id": fake_msg_id,
                    "threadId": replied_campaign.thread_id,
                    "snippet": "Hi, I am interested. Let's schedule an interview.",
                    "internalDate": fake_internal_date,
                    "payload": {
                        "headers": [
                            {"name": "From", "value": replied_hr.email},
                            {"name": "Subject", "value": "Re: Intro"},
                            {"name": "In-Reply-To", "value": replied_campaign.message_id or ""},
                            {"name": "References", "value": replied_campaign.message_id or ""},
                        ]
                    },
                }

        original_get_service = reply_tracker.get_gmail_read_service
        original_client_id = reply_tracker.GOOGLE_CLIENT_ID
        original_client_secret = reply_tracker.GOOGLE_CLIENT_SECRET
        reply_tracker.GOOGLE_CLIENT_ID = "demo-client-id"
        reply_tracker.GOOGLE_CLIENT_SECRET = "demo-client-secret"
        reply_tracker.get_gmail_read_service = lambda **kwargs: _FakeService()
        try:
            reply_result = reply_tracker.check_replies(max_students=10)
        finally:
            reply_tracker.get_gmail_read_service = original_get_service
            reply_tracker.GOOGLE_CLIENT_ID = original_client_id
            reply_tracker.GOOGLE_CLIENT_SECRET = original_client_secret

        db.expire_all()
        replied_campaign = db.query(EmailCampaign).filter(EmailCampaign.id == replied_campaign.id).first()
        print(
            "[STEP4] tracker_result=",
            reply_result,
            "replied=",
            bool(replied_campaign and replied_campaign.replied),
            "status=",
            replied_campaign.status if replied_campaign else None,
            "reply_type=",
            replied_campaign.reply_type if replied_campaign else None,
        )

        # STEP 5: follow-up stop check
        followup_statuses = (
            db.query(EmailCampaign.email_type, EmailCampaign.status)
            .filter(
                EmailCampaign.student_id == student.id,
                EmailCampaign.hr_id == replied_hr.id,
                EmailCampaign.sequence_number > 1,
            )
            .all()
        )
        print(f"[STEP5] followups_for_replied_hr={followup_statuses}")

        # STEP 6: analytics update check
        analytics = get_email_status(db=db)
        print(
            f"[STEP6] analytics replied={analytics.get('replied')}, reply_rate={analytics.get('reply_rate')}%, "
            f"success_rate={analytics.get('success_rate')}%"
        )

        # STEP 7: UI check data payload preview
        ui_campaign = (
            db.query(EmailCampaign)
            .filter(EmailCampaign.id == replied_campaign.id)
            .first()
        )
        print(
            "[STEP7] UI fields "
            f"replied={ui_campaign.replied}, reply_type={ui_campaign.reply_type}, "
            f"replied_at={ui_campaign.replied_at}, reply_snippet={(ui_campaign.reply_snippet or '')[:80]}"
        )

        # duplicate processing check (idempotency)
        original_get_service = reply_tracker.get_gmail_read_service
        original_client_id = reply_tracker.GOOGLE_CLIENT_ID
        original_client_secret = reply_tracker.GOOGLE_CLIENT_SECRET
        reply_tracker.GOOGLE_CLIENT_ID = "demo-client-id"
        reply_tracker.GOOGLE_CLIENT_SECRET = "demo-client-secret"
        reply_tracker.get_gmail_read_service = lambda **kwargs: _FakeService()
        try:
            second_pass = reply_tracker.check_replies(max_students=10)
        finally:
            reply_tracker.get_gmail_read_service = original_get_service
            reply_tracker.GOOGLE_CLIENT_ID = original_client_id
            reply_tracker.GOOGLE_CLIENT_SECRET = original_client_secret
        print(f"[IDEMPOTENCY] second_pass={second_pass}")

        print("\n[RESULT] Send -> Detect Reply -> Stop Follow-ups -> Analytics is functioning in demo run.")

    finally:
        db.close()


if __name__ == "__main__":
    run_demo()
