"""Outbound suppression list (hard block on recipient email)."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, String, Text

from app.database.config import Base, UuidType
from app.utils.datetime_utils import utc_now


class OutboundSuppression(Base):
    __tablename__ = "outbound_suppressions"

    id = Column(UuidType(), primary_key=True, default=uuid.uuid4)
    email = Column(String(320), nullable=False)
    # Stored lowercase for deterministic unique index + fast equality checks.
    email_lower = Column(String(320), nullable=False, unique=True, index=True)

    reason = Column(Text, nullable=True)
    source = Column(Text, nullable=True)  # e.g. "bounce", "invalid_email", "manual"

    is_active = Column(Boolean, nullable=False, default=True)
    suppressed_until = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

