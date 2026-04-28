import csv
import io

from app.services.reply_export import REPLY_EXPORT_COLUMNS, write_reply_export_csv


def test_reply_export_csv_is_rectangular_with_nasty_text():
    rows = [
        {
            "student_name": "A",
            "company": "C, Inc",
            "hr_email": "hr@example.com",
            "campaign_id": "1111",
            "subject": 'Hello "World"\nSubject',
            "status": "replied",
            "email_type": "initial",
            "reply_status": "INTERESTED",
            "reply_preview_truncated": "line1\nline2\tline3",
            "reply_preview": "long\n" * 50 + 'comma, quote " ok',
            "reply_received_at": "2026-01-01T00:00:00Z",
            "reply_detected_at": "2026-01-01T00:00:01Z",
            "sequence_number": 1,
            "outbound_message_id": "<m@id>",
            "sent_at": "2025-12-31T00:00:00Z",
            "reply_from_header": "HR <hr@example.com>",
            "suppression_reason": "",
            "terminal_outcome": "",
            "audit_notes": "note\nwith newlines",
        },
        # Missing keys should not shift columns
        {"campaign_id": "2222", "reply_preview": "x\ny"},
    ]

    buf = io.StringIO()
    n = write_reply_export_csv(buf, rows)
    assert n == 2

    buf.seek(0)
    parsed = list(csv.reader(io.StringIO(buf.getvalue())))
    assert parsed, "csv should not be empty"

    header = parsed[0]
    assert header == REPLY_EXPORT_COLUMNS

    for row in parsed[1:]:
        assert len(row) == len(REPLY_EXPORT_COLUMNS)
        # No embedded newlines in any cell because we sanitize before writing.
        assert all("\n" not in cell and "\r" not in cell and "\t" not in cell for cell in row)

