"""High-level campaign entity for campaign-level controls."""

import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey

from app.database.config import Base, UuidType
from app.utils.datetime_utils import utc_now


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(UuidType(), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    student_id = Column(UuidType(), ForeignKey("students.id"), nullable=False)
    status = Column(String(50), default="running")  # running | paused | completed
    created_at = Column(DateTime, default=utc_now)
