"""Assignment model - maps HR contacts to students (same HR may be linked to many students)."""
import uuid
from datetime import datetime, date
from sqlalchemy import Column, String, DateTime, Date, ForeignKey
from sqlalchemy.orm import relationship
from app.database.config import Base, UuidType


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(UuidType(), primary_key=True, default=uuid.uuid4)
    student_id = Column(UuidType(), ForeignKey("students.id"), nullable=False)
    hr_id = Column(UuidType(), ForeignKey("hr_contacts.id"), nullable=False)
    assigned_date = Column(Date, default=date.today)
    status = Column(String(50), default="active")  # active | completed | reassigned

    student = relationship("Student", backref="assignments")
    hr_contact = relationship("HRContact", backref="assignments")
