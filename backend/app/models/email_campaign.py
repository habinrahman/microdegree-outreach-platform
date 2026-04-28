"""Email campaign model - scheduled outreach sequence (initial + 3 follow-ups)."""
import uuid
from sqlalchemy import Column, String, DateTime, Integer, Text, ForeignKey, Boolean, UniqueConstraint
from app.database.config import Base, UuidType
from app.utils.datetime_utils import utc_now

# IMPORTANT:
# email_campaigns is the ONLY source of truth.
# Legacy email log storage is deprecated and must never be used.


class EmailCampaign(Base):
    __tablename__ = "email_campaigns"
    __table_args__ = (
        # Allow multiple campaigns per student–HR over time (initial + followups / retries).
        UniqueConstraint(
            "student_id",
            "hr_id",
            "sequence_number",
            name="uq_email_campaigns_student_hr_seq",
        ),
    )

    id = Column(UuidType(), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(UuidType(), ForeignKey("campaigns.id"), nullable=True)
    student_id = Column(UuidType(), ForeignKey("students.id"), nullable=False)
    hr_id = Column(UuidType(), ForeignKey("hr_contacts.id"), nullable=False)
    sequence_number = Column(Integer, nullable=False)  # 1-4
    email_type = Column(String(50), nullable=False)  # initial | followup_1 | followup_2 | followup_3
    scheduled_at = Column(DateTime, nullable=False)
    sent_at = Column(DateTime, nullable=True)
    status = Column(String(50), default="pending")  # pending | scheduled | sent | cancelled | failed | expired | paused | replied
    subject = Column(String(512), nullable=True)
    body = Column(Text, nullable=True)
    error = Column(Text, nullable=True)  # error message when sending fails
    gmail_message_id = Column(String(128), nullable=True)
    gmail_thread_id = Column(String(128), nullable=True)
    # RFC Message-ID / thread identifier for strict bounce/reply matching.
    message_id = Column(String(256), nullable=True)
    thread_id = Column(String(256), nullable=True)
    replied = Column(Boolean, default=False)
    replied_at = Column(DateTime, nullable=True)
    # Inbound message time (IMAP INTERNALDATE / Date header); primary sort for Replies.
    reply_received_at = Column(DateTime, nullable=True)
    reply_detected_at = Column(DateTime, nullable=True)
    # Canonical: INTERESTED | INTERVIEW | REJECTED | AUTO_REPLY | BOUNCE | OTHER
    reply_type = Column(String(64), nullable=True)
    reply_snippet = Column(Text, nullable=True)
    # Cleaned reply body (API: reply_message); legacy rows may still contain threads until backfill.
    reply_text = Column(Text, nullable=True)
    reply_from = Column(String(512), nullable=True)
    last_reply_message_id = Column(String(128), nullable=True)
    # A/B or variant label for initial email (sequence 1), e.g. "V1", "funding_hook"
    template_label = Column(String(128), nullable=True)
    # Delivery / follow-up signals: BOUNCED | BLOCKED | TEMP_FAIL | INTERVIEW | INTERESTED |
    # REJECTED | AUTO_REPLY | OOO | UNKNOWN | REPLIED — do not use INITIAL.
    reply_status = Column(String(32), nullable=True)
    # Delivery outcome from bounce detection (e.g. FAILED)
    delivery_status = Column(String(32), nullable=True)
    # Sheets sync: reply body export (IMAP); separate flags so failed rows can still export later.
    exported_to_sheet = Column(Boolean, default=False, nullable=False)
    exported_failure_sheet = Column(Boolean, default=False, nullable=False)
    exported_bounce_sheet = Column(Boolean, default=False, nullable=False)
    # Set when outbound worker claims the row (stuck-processing recovery).
    processing_started_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    # 🔹 NEW — structured failure tracking (does not replace anything)
    failure_type = Column(String(32), nullable=True)
    processing_lock_acquired_at = Column(DateTime, nullable=True)
    # Operator / automation: why remaining steps were cancelled (reply, toggle, etc.)
    suppression_reason = Column(Text, nullable=True)
    # Manual triage on replies dashboard (OPEN | IN_PROGRESS | CLOSED).
    reply_workflow_status = Column(String(50), nullable=True, default="OPEN")
    reply_admin_notes = Column(Text, nullable=True)
    # Pair-level analytics terminal (canonical on sequence 1): REPLIED_AFTER_* | NO_RESPONSE_COMPLETED | BOUNCED | PAUSED_UNKNOWN_OUTCOME
    terminal_outcome = Column(String(64), nullable=True)
    # Autonomous Sequencer v1 — lifecycle FSM (canonical on sequence 1; NULL = legacy ACTIVE).
    sequence_state = Column(String(48), nullable=True)
    # Outage-safe: overdue queueable rows are flagged, never auto-expired for scheduler lag.
    overdue_late = Column(Boolean, default=False, nullable=False)
    overdue_first_seen_at = Column(DateTime, nullable=True)
    exported_sequencer_sheet = Column(Boolean, default=False, nullable=False)

