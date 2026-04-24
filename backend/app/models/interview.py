"""Interview model - for placement tracking."""
import uuid
from datetime import date
from sqlalchemy import Column, String, DateTime, Date, Text, ForeignKey
from app.database.config import Base, UuidType
from app.utils.datetime_utils import utc_now


class Interview(Base):
    __tablename__ = "interviews"

    id = Column(UuidType(), primary_key=True, default=uuid.uuid4)
    student_id = Column(UuidType(), ForeignKey("students.id"), nullable=False)
    hr_id = Column(UuidType(), ForeignKey("hr_contacts.id"), nullable=False)
    company = Column(String(255), nullable=False)
    interview_date = Column(Date, nullable=True)
    status = Column(String(50), nullable=False)  # interview_scheduled | interview_completed | offer_received | rejected
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
