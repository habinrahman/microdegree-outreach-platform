"""Placement team notifications (e.g., positive HR replies)."""
import uuid
from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from app.database.config import Base, UuidType
from app.utils.datetime_utils import utc_now


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UuidType(), primary_key=True, default=uuid.uuid4)
    type = Column(String(50), nullable=False)  # hr_positive_response, etc.
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    status = Column(String(20), default="unread")  # unread | read
    # Dedupe type="reply" alerts (one row per campaign)
    reply_for_campaign_id = Column(
        UuidType(),
        ForeignKey("email_campaigns.id"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, default=utc_now)

