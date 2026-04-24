"""Response model - for reply tracking."""
import uuid
from datetime import date
from sqlalchemy import Column, String, DateTime, Date, Text, ForeignKey, Integer
from app.database.config import Base, UuidType
from app.utils.datetime_utils import utc_now


class Response(Base):
    __tablename__ = "responses"

    id = Column(UuidType(), primary_key=True, default=uuid.uuid4)
    student_id = Column(UuidType(), ForeignKey("students.id"), nullable=False)
    hr_id = Column(UuidType(), ForeignKey("hr_contacts.id"), nullable=False)
    response_date = Column(Date, nullable=False)
    response_type = Column(String(50), nullable=False)  # positive | negative | refer_contact | not_hiring | other
    notes = Column(Text, nullable=True)
    # Which outreach email the HR reply belongs to (from thread → EmailCampaign match)
    source_email_type = Column(String(50), nullable=True)  # initial | followup_1 | followup_2 | followup_3
    source_sequence_number = Column(Integer, nullable=True)  # 1-4
    source_campaign_id = Column(UuidType(), ForeignKey("email_campaigns.id"), nullable=True)
    # Gmail API message id (users.messages id) — dedupe reply processing
    gmail_message_id = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
