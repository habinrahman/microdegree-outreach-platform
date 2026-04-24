"""
Investigate EmailCampaign send failures.

Prints all EmailCampaign rows with status="failed", including:
- error
- student_id
- hr_id
- hr email

Then categorizes failures and prints category counts + suggested fixes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

from app.database.config import SessionLocal
from app.models import EmailCampaign, HRContact, Student


@dataclass
class FailureRow:
    campaign_id: str
    error: str
    student_id: str
    hr_id: str
    hr_email: str
    student_email: str | None


def categorize(error: str) -> str:
    e = (error or "").lower()

    # Gmail auth / OAuth / login issues
    if "gmail_auth_block" in e or "web login required" in e or "webbloginrequired" in e:
        return "Gmail auth error"
    if "invalid_grant" in e or "invalid token" in e or "oauth" in e or "auth" in e:
        return "Gmail auth error"

    # SMTP auth (Gmail app password login errors often include 534)
    if "smtp" in e and ("auth" in e or "authentication" in e):
        return "SMTP auth error"
    if "534" in e or "5.7.9" in e or "please log in with your web browser" in e:
        return "SMTP auth error"

    # Invalid / bounced emails (hard bounces)
    if "bounce" in e or "bounced" in e:
        return "invalid email"
    if "550" in e or "invalid" in e or "permanent" in e:
        return "invalid email"

    # Connection issues
    if "connection" in e or "timeout" in e or "could not connect" in e or "temporarily unavailable" in e:
        return "connection issue"
    if "psycopg2" in e or "operationalerror" in e or "server at" in e:
        return "connection issue"

    return "unknown"


def main() -> None:
    db = SessionLocal()
    try:
        rows = (
            db.query(EmailCampaign, HRContact.email, Student.gmail_address)
            .join(HRContact, EmailCampaign.hr_id == HRContact.id)
            .join(Student, EmailCampaign.student_id == Student.id)
            .filter(EmailCampaign.status == "failed")
            .order_by(EmailCampaign.sent_at.desc().nullslast(), EmailCampaign.id.desc())
            .all()
        )

        if not rows:
            print("No EmailCampaign rows with status='failed' found.")
            return

        failure_rows: list[FailureRow] = []
        categories: dict[str, int] = {}

        print(f"Found {len(rows)} failed EmailCampaign rows:\n")
        for ec, hr_email, student_email in rows:
            error = ec.error or ""
            cat = categorize(error)
            categories[cat] = categories.get(cat, 0) + 1
            failure_rows.append(
                FailureRow(
                    campaign_id=str(ec.id),
                    error=error,
                    student_id=str(ec.student_id),
                    hr_id=str(ec.hr_id),
                    hr_email=hr_email,
                    student_email=student_email,
                )
            )

            print("----")
            print(f"campaign_id: {ec.id}")
            print(f"error: {error}")
            print(f"student_id: {ec.student_id}")
            print(f"hr_id: {ec.hr_id}")
            print(f"hr_email: {hr_email}")
            print(f"student_email: {student_email}")
            print(f"category: {cat}")

        print("\n====================")
        print("Failure category counts")
        print("====================")
        for k, v in sorted(categories.items(), key=lambda x: x[0]):
            print(f"{k}: {v}")

        print("\n====================")
        print("Suggested fixes by category")
        print("====================")
        suggestions: dict[str, str] = {
            "Gmail auth error": (
                "Check Gmail OAuth configuration: refresh tokens validity, GOOGLE_CLIENT_ID/SECRET correctness, "
                "and ensure the sender Google account is allowed. If you see 'WebLoginRequired' then "
                "reauthorize the Gmail OAuth for affected students."
            ),
            "SMTP auth error": (
                "Replace/refresh Gmail app passwords for affected students, or switch those students to OAuth. "
                "If errors include 534 / 5.7.9 / WebLoginRequired, the app password is no longer accepted—reconnect or reauth."
            ),
            "invalid email": (
                "Validate HR email addresses on input, and consider adding stricter email normalization. "
                "Ensure bounce handling marks HR 'invalid' (it should already be based on 550/bounce/permanent)."
            ),
            "connection issue": (
                "If failures show DB connection errors, verify DATABASE_URL, network, and retry/backoff strategy. "
                "If failures show Gmail/API connection issues, add targeted retries with exponential backoff."
            ),
            "unknown": (
                "Inspect the raw error strings printed above. Add more substring patterns to categorize, and ensure failures are committed correctly."
            ),
        }

        for cat in sorted(categories.keys()):
            print(f"\n[{cat}]")
            print(suggestions.get(cat, suggestions['unknown']))

    finally:
        db.close()


if __name__ == "__main__":
    main()

