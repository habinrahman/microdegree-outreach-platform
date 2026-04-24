"""Send emails via Gmail API with OAuth. Attach resume from Google Drive."""
import base64
import io
import logging
import os
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.utils import make_msgid

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


def _get_gmail_service(refresh_token: str, client_id: str, client_secret: str):
    """Build Gmail API service from refresh token."""
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=[
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )
    service = build("gmail", "v1", credentials=creds)
    return service


def get_gmail_read_service(*, refresh_token: str, client_id: str, client_secret: str):
    """Gmail API service with readonly scope for inbox monitoring."""
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=[
            "https://www.googleapis.com/auth/gmail.readonly",
        ],
    )
    return build("gmail", "v1", credentials=creds)


def _download_drive_file(creds: Credentials, file_id: str) -> tuple[bytes, str]:
    """Download file from Google Drive by file_id. Returns (raw_bytes, filename)."""
    from googleapiclient.discovery import build
    drive = build("drive", "v3", credentials=creds)
    meta = drive.files().get(fileId=file_id, fields="name").execute()
    name = meta.get("name", "resume.pdf")
    data = drive.files().get_media(fileId=file_id).execute()
    return data, name


def send_via_gmail(
    *,
    from_email: str,
    to_email: str,
    subject: str,
    body: str,
    refresh_token: str,
    client_id: str,
    client_secret: str,
    drive_file_id: str | None = None,
    resume_path: str | None = None,
    student_name: str | None = None,
) -> dict:
    """
    Send one email via Gmail API. A resume PDF attachment is required for every email.
    Attach priority: Drive (drive_file_id) -> local file (resume_path).
    Returns dict with Gmail API fields plus "message_id" (RFC) and "gmail_thread_id" (sent["threadId"]).
    Raises on auth/send failure; on permanent bounce the caller should set hr status invalid.
    """
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=[
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )
    service = build("gmail", "v1", credentials=creds)

    message = MIMEMultipart()
    message["to"] = to_email
    message["from"] = from_email
    message["subject"] = subject
    # RFC Message-ID for strict bounce/reply mapping.
    message["Message-ID"] = make_msgid(idstring=str(uuid.uuid4()))
    message.attach(MIMEText(body, "plain"))

    attached = False
    if drive_file_id:
        try:
            drive = build("drive", "v3", credentials=creds)
            meta = drive.files().get(fileId=drive_file_id, fields="name,mimeType").execute()
            name = f"{student_name}.pdf" if student_name else meta.get("name", "resume.pdf")
            mime_type = meta.get("mimeType", "application/pdf")
            data = drive.files().get_media(fileId=drive_file_id).execute()
            part = MIMEBase(*mime_type.split("/", 1))
            part.set_payload(data)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{name}"')
            message.attach(part)
            attached = True
        except HttpError as e:
            raise RuntimeError(f"Could not attach Drive resume file {drive_file_id}: {e}") from e

    # Fallback: attach local resume_path when Drive attachment isn't available.
    if (not attached) and resume_path:
        try:
            full_path = resume_path if os.path.isabs(resume_path) else os.path.abspath(resume_path)
            if not os.path.isfile(full_path):
                raise FileNotFoundError(full_path)
            with open(full_path, "rb") as f:
                data = f.read()
            part = MIMEBase("application", "pdf")
            part.set_payload(data)
            encoders.encode_base64(part)
            filename = f"{student_name}.pdf" if student_name else (os.path.basename(full_path) or "resume.pdf")
            part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
            message.attach(part)
            attached = True
        except Exception as e:
            raise RuntimeError(f"Could not attach local resume {resume_path}: {e}") from e

    if not attached:
        raise RuntimeError("Resume attachment is required (missing drive_file_id and resume_path)")

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    thread_id = sent["threadId"]
    return {
        **sent,
        "message_id": message.get("Message-ID"),
        "gmail_thread_id": thread_id,
    }
