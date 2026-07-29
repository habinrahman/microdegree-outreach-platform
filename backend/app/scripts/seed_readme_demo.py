"""Seed operator-console data for README demo GIF recording.

Creates realistic (non-demo) students, HR contacts, and campaigns visible in the UI.
Safe to re-run — cleans prior rows tagged with @readme-demo.local emails.

Usage (from backend/):
  APP_ENV=dev ADMIN_API_KEY=demo-readme-recording-key python -m app.scripts.seed_readme_demo
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.database.config import SessionLocal, init_db
from app.models import Assignment, EmailCampaign, HRContact, Student

TAG = "readme-demo"
EMAIL_DOMAIN = f"{TAG}.local"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _cleanup(db) -> None:
    like = f"%@{EMAIL_DOMAIN}"
    hrs = db.query(HRContact).filter(HRContact.email.like(like)).all()
    hr_ids = [h.id for h in hrs]
    students = db.query(Student).filter(Student.gmail_address.like(like)).all()
    student_ids = [s.id for s in students]

    if student_ids or hr_ids:
        q = db.query(EmailCampaign)
        if student_ids and hr_ids:
            q = q.filter(
                (EmailCampaign.student_id.in_(student_ids)) | (EmailCampaign.hr_id.in_(hr_ids))
            )
        elif student_ids:
            q = q.filter(EmailCampaign.student_id.in_(student_ids))
        else:
            q = q.filter(EmailCampaign.hr_id.in_(hr_ids))
        q.delete(synchronize_session=False)

    if student_ids:
        db.query(Assignment).filter(Assignment.student_id.in_(student_ids)).delete(synchronize_session=False)
        db.query(Student).filter(Student.id.in_(student_ids)).delete(synchronize_session=False)
    if hr_ids:
        db.query(HRContact).filter(HRContact.id.in_(hr_ids)).delete(synchronize_session=False)
    db.commit()


def seed() -> None:
    init_db()
    db = SessionLocal()
    now = _now()

    try:
        _cleanup(db)

        student = Student(
            name="Aisha Khan",
            gmail_address=f"aisha.khan@{EMAIL_DOMAIN}",
            gmail_connected=True,
            gmail_refresh_token="readme-demo-token",
            status="active",
            email_health_status="healthy",
            skills="Python, FastAPI, React, PostgreSQL",
            experience_years=2,
            is_demo=False,
            is_fixture_test_data=False,
        )
        db.add(student)
        db.flush()

        hr_specs = [
            ("Priya Sharma", "Razorpay", "INTERESTED"),
            ("Rahul Mehta", "Flipkart", "REJECTED"),
            ("Neha Reddy", "Swiggy", None),
            ("Arjun Patel", "Freshworks", None),
            ("Kavya Iyer", "Zoho", None),
        ]

        hrs: list[HRContact] = []
        for idx, (name, company, _reply) in enumerate(hr_specs, start=1):
            hr = HRContact(
                name=name,
                company=company,
                email=f"hr{idx}.{TAG}@{EMAIL_DOMAIN}",
                designation="Talent Acquisition",
                status="active",
                is_valid=True,
                is_demo=False,
                is_fixture_test_data=False,
            )
            hrs.append(hr)
            db.add(hr)
        db.flush()

        for hr in hrs:
            db.add(Assignment(student_id=student.id, hr_id=hr.id, status="active"))
        db.commit()

        for idx, hr in enumerate(hrs, start=1):
            sent_at = now - timedelta(hours=6 - idx)
            reply_type = hr_specs[idx - 1][2]

            initial = EmailCampaign(
                student_id=student.id,
                hr_id=hr.id,
                sequence_number=1,
                email_type="initial",
                status="replied" if reply_type else "sent",
                scheduled_at=sent_at - timedelta(minutes=30),
                sent_at=sent_at,
                subject=f"Placement outreach — {student.name} × {hr.company}",
                body=f"Hi {hr.name}, sharing {student.name}'s profile for backend roles at {hr.company}.",
                message_id=f"<readme-demo-{idx}@mail.local>",
                thread_id=f"thread-readme-{idx}",
                template_label="V1",
                replied=reply_type is not None,
                replied_at=sent_at + timedelta(hours=2) if reply_type else None,
                reply_received_at=sent_at + timedelta(hours=2) if reply_type else None,
                reply_type=reply_type,
                reply_status=reply_type,
                reply_snippet=(
                    "Thanks for reaching out — we'd like to schedule a technical round."
                    if reply_type == "INTERESTED"
                    else "Not hiring for this profile right now."
                    if reply_type == "REJECTED"
                    else None
                ),
                reply_text=(
                    "Thanks for reaching out — we'd like to schedule a technical round."
                    if reply_type == "INTERESTED"
                    else "Not hiring for this profile right now."
                    if reply_type == "REJECTED"
                    else None
                ),
                reply_from=hr.email if reply_type else None,
                reply_workflow_status="OPEN" if reply_type else None,
                sequence_state="REPLIED" if reply_type else "ACTIVE",
            )
            db.add(initial)

            follow = EmailCampaign(
                student_id=student.id,
                hr_id=hr.id,
                sequence_number=2,
                email_type="followup_1",
                status="cancelled" if reply_type else "scheduled",
                scheduled_at=sent_at + timedelta(days=7),
                subject=f"Following up — {hr.company} opportunity",
                body="Quick follow-up on my earlier note.",
                suppression_reason="reply_received" if reply_type else None,
            )
            db.add(follow)

        db.commit()

        sent = (
            db.query(EmailCampaign)
            .filter(EmailCampaign.student_id == student.id, EmailCampaign.sequence_number == 1)
            .count()
        )
        replied = (
            db.query(EmailCampaign)
            .filter(EmailCampaign.student_id == student.id, EmailCampaign.replied.is_(True))
            .count()
        )
        print(f"[SEED] student=1 hr_contacts={len(hrs)} initial_campaigns={sent} replies={replied}")
        print("[SEED] README demo data ready (is_demo=false — visible in operator UI).")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
