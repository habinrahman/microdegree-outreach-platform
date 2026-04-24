"""Send outreach email via Gmail SMTP (STARTTLS)."""
import os
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid
import uuid
from typing import Iterable

# Backend app root (backend/app/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Backend folder for resume paths relative to backend/
BACKEND_DIR = os.path.dirname(BASE_DIR)


def _sanitize_rfc_header_value(s: str | None, *, max_len: int = 998) -> str:
    """Prevent header injection (CR/LF) and bound length for In-Reply-To / References."""
    t = (s or "").replace("\r", " ").replace("\n", " ").strip()
    if len(t) > max_len:
        return t[:max_len]
    return t


def build_email_message(
    *,
    student_email: str,
    hr_email: str,
    student_name: str,
    company: str,
    experience_years: int | float | None = None,
    resume_path: str | None = None,
    subject: str | None = None,
    body: str | None = None,
    use_stored_campaign_content: bool = False,
    in_reply_to: str | None = None,
    references: Iterable[str] | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    # IMPORTANT: Don't spoof sender formatting. From must match authenticated Gmail account.
    msg["From"] = student_email
    msg["To"] = hr_email
    message_id = make_msgid(idstring=str(uuid.uuid4()))
    msg["Message-ID"] = message_id

    irt = _sanitize_rfc_header_value(in_reply_to)
    if irt:
        msg["In-Reply-To"] = irt
    refs = [_sanitize_rfc_header_value(str(r).strip()) for r in (references or []) if str(r).strip()]
    if refs:
        msg["References"] = " ".join(refs)

    if use_stored_campaign_content:
        msg["Subject"] = subject or ""
        msg.set_content(body or "")
    else:
        msg["Subject"] = subject or f"Application for Opportunities – {student_name}"

        exp_line = ""
        if experience_years is not None:
            try:
                exp_val = float(experience_years)
                if exp_val >= 0:
                    exp_line = f"I have {exp_val:g} years of experience.\n\n"
            except Exception:
                exp_line = ""

        msg.set_content(
            body
            or f"""
Hello,

My name is {student_name}. I am reaching out to explore potential opportunities at {company}.

{exp_line}I have attached my resume for your consideration.

Looking forward to hearing from you.

Best regards,
{student_name}
"""
        )

    if not resume_path:
        raise RuntimeError("Resume attachment is required (missing resume_path)")

    full_resume_path = os.path.join(BACKEND_DIR, resume_path) if not os.path.isabs(resume_path) else resume_path
    if not os.path.isfile(full_resume_path):
        raise FileNotFoundError(f"Resume file not found: {full_resume_path}")

    with open(full_resume_path, "rb") as f:
        file_data = f.read()

    msg.add_attachment(
        file_data,
        maintype="application",
        subtype="pdf",
        filename=f"{student_name}.pdf",
    )
    return msg


def send_email(
    student_email: str,
    app_password: str,
    hr_email: str,
    student_name: str,
    company: str,
    experience_years: int | float | None = None,
    resume_path: str | None = None,
    subject: str | None = None,
    body: str | None = None,
    *,
    use_stored_campaign_content: bool = False,
    in_reply_to: str | None = None,
    references: Iterable[str] | None = None,
) -> dict:
    """Send one outreach email from student to HR. Resume attachment is required for every email."""
    msg = build_email_message(
        student_email=student_email,
        hr_email=hr_email,
        student_name=student_name,
        company=company,
        experience_years=experience_years,
        resume_path=resume_path,
        subject=subject,
        body=body,
        use_stored_campaign_content=use_stored_campaign_content,
        in_reply_to=in_reply_to,
        references=references,
    )

    smtp_server = "smtp.gmail.com"
    port = 587
    with smtplib.SMTP(smtp_server, port) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(student_email, app_password)
        smtp.send_message(msg)

    return {
        "ok": True,
        "message_id": msg["Message-ID"],
    }
