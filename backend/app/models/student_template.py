"""Per-student email templates (storage only; no sending behavior here)."""

from __future__ import annotations

import uuid
from sqlalchemy import Column, DateTime, ForeignKey, String, Text, UniqueConstraint

from app.database.config import Base, UuidType
from app.utils.datetime_utils import utc_now


class StudentTemplate(Base):
    __tablename__ = "student_templates"
    __table_args__ = (
        UniqueConstraint("student_id", "template_type", name="uq_student_templates_student_type"),
    )

    id = Column(UuidType(), primary_key=True, default=uuid.uuid4)
    student_id = Column(UuidType(), ForeignKey("students.id"), nullable=False, index=True)
    template_type = Column(String(20), nullable=False)  # INITIAL | FOLLOWUP_1..3
    subject = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

