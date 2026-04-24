"""Audit log model - record security/events for admin visibility."""
import uuid
from sqlalchemy import Column, String, DateTime, Text

from app.database.config import Base, UuidType
from app.utils.datetime_utils import utc_now


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UuidType(), primary_key=True, default=uuid.uuid4)
    actor = Column(String(255), nullable=True)  # e.g. admin, system, user email
    action = Column(String(100), nullable=False)  # e.g. gmail_reply_detected, oauth_connected
    entity_type = Column(String(100), nullable=True)  # Student, HRContact, Campaign, etc.
    entity_id = Column(String(64), nullable=True)  # store UUID as string
    meta = Column(Text, nullable=True)  # JSON string
    created_at = Column(DateTime, default=utc_now)

