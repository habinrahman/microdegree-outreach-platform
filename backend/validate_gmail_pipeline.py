"""
Validate Gmail sending pipeline.

Auth-only validation (default):
1) OAuth: attempt refresh token exchange (no email sent)
2) SMTP: attempt SMTP login (no email sent)

Send validation (--mode send):
1) OAuth: send one test email via Gmail API
2) SMTP: send one test email via SMTP
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

from app.database.config import SessionLocal
from app.models import Student, HRContact
from app.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from app.services.email_sender import send_email
from app.services.gmail_sender import send_via_gmail


@dataclass
class Candidate:
    student: Student
    method: str


def _pick_recipient(db) -> HRContact | None:
    return (
        db.query(HRContact)
        .filter(HRContact.is_valid.is_(True))
        .order_by(HRContact.created_at.desc())
        .first()
    )


def _pick_candidates(db) -> tuple[Candidate | None, Candidate | None]:
    oauth_student = (
        db.query(Student)
        .filter(Student.gmail_refresh_token.isnot(None))
        .filter(Student.gmail_refresh_token != "")
        .order_by(Student.created_at.desc())
        .first()
    )
    smtp_student = (
        db.query(Student)
        .filter(Student.app_password.isnot(None))
        .filter(Student.app_password != "")
        .order_by(Student.created_at.desc())
        .first()
    )

    oauth = Candidate(student=oauth_student, method="oauth") if oauth_student else None
    smtp = Candidate(student=smtp_student, method="smtp") if smtp_student else None
    return oauth, smtp


def oauth_auth_check(*, refresh_token: str) -> tuple[bool, str]:
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return False, "GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET not configured"

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
        )
        creds.refresh(Request())
        return True, "OAuth refresh successful"
    except Exception as e:
        return False, str(e)


def smtp_auth_check(*, student_email: str, app_password: str) -> tuple[bool, str]:
    import smtplib

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(student_email, app_password)
        return True, "SMTP login successful"
    except Exception as e:
        return False, str(e)


def send_oauth_test(
    *,
    refresh_token: str,
    from_email: str,
    to_email: str,
    resume_drive_file_id: str | None = None,
    resume_path: str | None = None,
    student_name: str | None = None,
) -> tuple[bool, str]:
    try:
        res = send_via_gmail(
            from_email=from_email,
            to_email=to_email,
            subject="Pipeline test (OAuth)",
            body="This is a single test email to validate Gmail OAuth sending.",
            refresh_token=refresh_token,
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            drive_file_id=resume_drive_file_id,
            resume_path=resume_path,
            student_name=student_name,
        )
        return True, f"OAuth send ok (message_id={res.get('message_id')})"
    except Exception as e:
        return False, str(e)


def send_smtp_test(
    *,
    student_email: str,
    app_password: str,
    to_email: str,
    student_name: str,
    company: str,
    resume_path: str,
) -> tuple[bool, str]:
    try:
        send_email(
            student_email,
            app_password,
            to_email,
            student_name,
            company,
            experience_years=0,
            resume_path=resume_path,
            subject="Pipeline test (SMTP)",
            body="This is a single test email to validate Gmail SMTP sending.",
            use_stored_campaign_content=True,
        )
        return True, "SMTP send ok"
    except Exception as e:
        return False, str(e)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["auth", "send"], default="auth", help="auth: validate login; send: actually send one email")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        total_students = db.query(Student).count()
        oauth_count = (
            db.query(Student)
            .filter(Student.gmail_refresh_token.isnot(None))
            .filter(Student.gmail_refresh_token != "")
            .count()
        )
        smtp_count = (
            db.query(Student)
            .filter(Student.app_password.isnot(None))
            .filter(Student.app_password != "")
            .count()
        )
        oauth_connected_count = db.query(Student).filter(Student.gmail_connected.is_(True)).count()

        oauth, smtp = _pick_candidates(db)
        recipient = _pick_recipient(db)

        print(f"[{datetime.now(timezone.utc).isoformat()}] Pipeline validation mode={args.mode}")
        print(f"Students total={total_students} | OAuth refresh tokens={oauth_count} | SMTP app passwords={smtp_count} | gmail_connected=true={oauth_connected_count}")

        if not recipient:
            print("No HRContact recipient found (all invalid?)")
            return

        print(f"Recipient HR: {recipient.email} (company={recipient.company}, status={recipient.status})")
        print(f"OAuth candidate: {oauth.student.gmail_address if oauth else None}")
        print(f"SMTP candidate: {smtp.student.gmail_address if smtp else None}")

        if oauth:
            ok, msg = oauth_auth_check(refresh_token=oauth.student.gmail_refresh_token)
            print(f"OAuth auth: {'OK' if ok else 'FAIL'} - {msg}")
            if args.mode == "send" and ok:
                ok2, msg2 = send_oauth_test(
                    refresh_token=oauth.student.gmail_refresh_token,
                    from_email=oauth.student.gmail_address,
                    to_email=recipient.email,
                    resume_drive_file_id=(oauth.student.resume_drive_file_id or None),
                    resume_path=(oauth.student.resume_path or None),
                    student_name=(oauth.student.name or None),
                )
                print(f"OAuth send: {'OK' if ok2 else 'FAIL'} - {msg2}")

        if smtp:
            ok, msg = smtp_auth_check(student_email=smtp.student.gmail_address, app_password=smtp.student.app_password)
            print(f"SMTP auth: {'OK' if ok else 'FAIL'} - {msg}")
            if args.mode == "send" and ok:
                ok2, msg2 = send_smtp_test(
                    student_email=smtp.student.gmail_address,
                    app_password=smtp.student.app_password,
                    to_email=recipient.email,
                    student_name=smtp.student.name,
                    company=recipient.company,
                    resume_path=smtp.student.resume_path,
                )
                print(f"SMTP send: {'OK' if ok2 else 'FAIL'} - {msg2}")

    finally:
        db.close()


if __name__ == "__main__":
    main()

