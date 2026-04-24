"""SMTP-only outbound email (student Gmail + app password)."""

from app.services.email_sender import send_email


def send_with_fallback(
    *,
    student_email: str,
    hr_email: str,
    subject: str,
    body: str,
    gmail_refresh_token: str | None = None,
    smtp_app_password: str | None = None,
    resume_drive_file_id: str | None = None,
    resume_path: str | None = None,
    student_name: str | None = None,
    in_reply_to: str | None = None,
    references: list[str] | None = None,
) -> dict:
    """
    Send via Gmail SMTP using the student's app password.
    gmail_refresh_token / drive_file_id are ignored (legacy signature preserved).
    Returns dict with message_id (RFC Message-ID header).
    """
    from_email = (student_email or "").strip()
    app_password = (smtp_app_password or "").strip()
    local_path = (resume_path or "").strip()

    if from_email and app_password:
        return send_email(
            student_email=from_email,
            app_password=app_password,
            hr_email=hr_email,
            student_name=student_name or "",
            company="",
            experience_years=None,
            resume_path=(local_path or None),
            subject=subject,
            body=body,
            use_stored_campaign_content=True,
            in_reply_to=in_reply_to,
            references=references,
        )

    raise Exception("No valid email sending method available (need app_password)")
