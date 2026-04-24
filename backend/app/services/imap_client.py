"""IMAP helpers for per-student inbox reads (Gmail app password)."""
import imaplib
import re
from email import message_from_bytes
from email.message import Message
from typing import Any

# Newer inboxes: fetch more headers for threading / dedupe.
_DEFAULT_FETCH_TAIL = 120


def _extract_plain_body(msg: Message) -> str:
    """Best-effort plain text from message (prefers text/plain, coarse strip for HTML-only)."""
    chunks: list[str] = []

    def decode_part(part: Message) -> str | None:
        raw = part.get_payload(decode=True)
        if raw is None:
            return None
        if isinstance(raw, str):
            return raw
        if isinstance(raw, bytes):
            cs = part.get_content_charset() or "utf-8"
            return raw.decode(cs, errors="replace")
        return None

    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain":
                t = decode_part(part)
                if t:
                    chunks.append(t)
            elif ctype == "text/html" and not chunks:
                t = decode_part(part)
                if t:
                    stripped = re.sub(r"<[^>]+>", " ", t)
                    chunks.append(stripped)
    else:
        ctype = msg.get_content_type()
        if ctype == "text/plain":
            t = decode_part(msg)
            if t:
                chunks.append(t)
        elif ctype == "text/html":
            t = decode_part(msg)
            if t:
                stripped = re.sub(r"<[^>]+>", " ", t)
                chunks.append(stripped)
        else:
            t = decode_part(msg)
            if t:
                chunks.append(t)

    if not chunks:
        return ""
    return "\n\n".join(" ".join(c.split()) for c in chunks).strip()


def fetch_inbox(student_email: str, app_password: str) -> tuple[list[bytes], imaplib.IMAP4_SSL]:
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(student_email, app_password)
    mail.select("inbox")

    status, messages = mail.search(None, "ALL")
    if status != "OK" or not messages or not messages[0]:
        return [], mail

    return messages[0].split(), mail


def fetch_messages(
    mail: imaplib.IMAP4_SSL,
    message_nums: list[bytes],
    *,
    tail: int = _DEFAULT_FETCH_TAIL,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    slice_nums = message_nums[-tail:] if len(message_nums) > tail else message_nums
    for num in slice_nums:
        status, data = mail.fetch(num, "(RFC822)")
        if status != "OK" or not data or not data[0]:
            continue

        payload = data[0]
        raw = payload[1] if isinstance(payload, tuple) and len(payload) > 1 else payload
        if not isinstance(raw, (bytes, bytearray)):
            continue

        msg = message_from_bytes(bytes(raw))
        body_plain = _extract_plain_body(msg)
        results.append(
            {
                "subject": msg.get("Subject"),
                "from": msg.get("From"),
                "in_reply_to": msg.get("In-Reply-To"),
                "references": msg.get("References"),
                "message_id": msg.get("Message-ID"),
                "body_plain": body_plain,
            }
        )

    return results
