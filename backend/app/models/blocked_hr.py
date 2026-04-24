"""Global blocked HR registry (created from bounce classification)."""

import uuid
from sqlalchemy import Column, String, DateTime, Boolean, UniqueConstraint

from app.database.config import Base, UuidType
from app.utils.datetime_utils import utc_now


class BlockedHR(Base):
    __tablename__ = "blocked_hrs"

    __table_args__ = (
        UniqueConstraint("email", name="uq_blocked_hrs_email"),
    )

    id = Column(UuidType(), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), nullable=False, index=True)
    company = Column(String(255), nullable=True)
    reason = Column(String(100), nullable=False, default="bounce")
    exported_to_sheet = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utc_now)

